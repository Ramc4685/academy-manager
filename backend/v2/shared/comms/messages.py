"""Shared comms module — messages + announcements.

Lives in shared/ rather than as a context because there are no invariants
worth a write-side aggregate; it's a thin CRUD module per ADR-0005
deferred-context rules.

Stored in `messages` and `announcements` collections.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.v2.shared.ids import new_ulid
from backend.v2.shared.tenancy import TenantScopedRepository, current_academy_id

MessageKind = Literal["dm", "announcement"]
Persona = Literal["admin", "coach", "parent"]
Urgency = Literal["routine", "urgent"]

#: ``scope_type`` value that makes an announcement session-scoped (#614).
#: Anything else — including the legacy ``"academy"`` and a missing/null
#: field — stays academy-wide and visible to everyone, which is what keeps
#: this change backward compatible with no data migration.
SESSION_SCOPE = "session"

#: Long enough for "the gym is flooded, here is where we are moving tonight",
#: short enough that the inbox stays scannable and the email stays an email.
MAX_ANNOUNCEMENT_BODY = 2000

#: Hard cap on every announcement cursor. ``for_session`` is unbounded in
#: principle (a busy class could accumulate hundreds of posts), so it takes the
#: same limit the inbox reads already use.
_READ_LIMIT = 200


class Message(BaseModel):
    model_config = {"frozen": True}
    message_id: str
    academy_id: str
    kind: MessageKind
    sender_id: str
    sender_persona: Persona
    recipient_id: str | None  # None for broadcasts
    body: str
    created_at: datetime
    read_by: list[str] = Field(default_factory=list)
    scope_type: str | None = None
    scope_label: str | None = None
    recipient_count: int | None = None
    delivery_status: str | None = None
    #: Session announcements (#614) carry the session they belong to. Read-time
    #: visibility is derived from this id, so it is the security-relevant field
    #: on the document — see :func:`_visibility_filter`.
    scope_id: str | None = None
    urgency: Urgency = "routine"
    author_display_name: str | None = None
    #: Soft delete. The email has already left the building, so the record of
    #: what was posted has to survive for support; the read predicate hides it.
    deleted_at: datetime | None = None
    deleted_by: str | None = None


def _visibility_filter(recipient_id: str, visible_session_ids: Sequence[str]) -> dict[str, Any]:
    """The one predicate deciding what a non-admin viewer may see.

    Built in a single place and shared by the read (`for_recipient`) and the
    write (`mark_read`) so the two can never disagree about who may see what.

    Three branches, and the middle one is what keeps existing data working:

    * the viewer's own DMs;
    * any announcement that is NOT session-scoped. ``$ne`` matches a missing
      or null field in Mongo, so every announcement written before #614
      (``scope_type`` null or ``"academy"``) stays visible to the whole
      academy exactly as it is today — no data migration, no behaviour change;
    * a session announcement whose ``scope_id`` is one of the sessions this
      viewer can see, resolved per request from live enrollment/assignment.

    Fail-closed: an empty ``visible_session_ids`` yields ``$in: []``, which
    matches nothing, so a viewer with no sessions sees no session
    announcements rather than all of them.
    """
    return {
        "deleted_at": None,
        "$or": [
            {"recipient_id": recipient_id},
            {"kind": "announcement", "scope_type": {"$ne": SESSION_SCOPE}},
            {
                "kind": "announcement",
                "scope_type": SESSION_SCOPE,
                "scope_id": {"$in": list(visible_session_ids)},
            },
        ],
    }


class MongoMessageRepository(TenantScopedRepository):
    collection_name = "messages"

    @staticmethod
    def _to_domain(doc: dict[str, Any]) -> Message:
        return Message(
            message_id=str(doc["message_id"]),
            academy_id=str(doc["academy_id"]),
            kind=doc.get("kind", "dm"),
            sender_id=str(doc["sender_id"]),
            sender_persona=doc.get("sender_persona", "admin"),
            recipient_id=doc.get("recipient_id"),
            body=str(doc.get("body", "")),
            created_at=doc["created_at"],
            read_by=list(doc.get("read_by", [])),
            scope_type=(str(doc["scope_type"]) if doc.get("scope_type") else None),
            scope_label=(str(doc["scope_label"]) if doc.get("scope_label") else None),
            recipient_count=(
                int(doc["recipient_count"]) if doc.get("recipient_count") is not None else None
            ),
            delivery_status=(str(doc["delivery_status"]) if doc.get("delivery_status") else None),
            # `doc.get` defaults throughout: every message written before #614
            # deserializes unchanged as a routine, non-deleted, unscoped one.
            scope_id=(str(doc["scope_id"]) if doc.get("scope_id") else None),
            urgency=doc.get("urgency") or "routine",
            author_display_name=(
                str(doc["author_display_name"]) if doc.get("author_display_name") else None
            ),
            deleted_at=doc.get("deleted_at"),
            deleted_by=(str(doc["deleted_by"]) if doc.get("deleted_by") else None),
        )

    async def insert(self, m: Message) -> None:
        await self._insert_one(
            {k: v for k, v in m.model_dump(mode="python").items() if k != "academy_id"}
        )

    async def for_recipient(
        self, recipient_id: str, *, visible_session_ids: Sequence[str]
    ) -> list[Message]:
        """The inbox for one non-admin viewer.

        ``visible_session_ids`` is keyword-only and has no default on purpose.
        Before #614 this method returned *every* announcement in the academy to
        every caller, which is exactly the leak a session-scoped announcement
        would have walked into. A defaulted "means everything" argument would
        put that leak one forgetful call site away; a required argument makes
        the omission a TypeError at wiring time instead. Admin's deliberately
        unrestricted read is the separately named :meth:`for_admin`.
        """
        cursor = self._find_many(
            _visibility_filter(recipient_id, visible_session_ids),
            sort=[("created_at", -1)],
            limit=_READ_LIMIT,
        )
        return [self._to_domain(d) async for d in cursor]

    async def for_admin(self, user_id: str) -> list[Message]:
        """Admin's inbox: their DMs plus every announcement in the academy.

        Admin may post to any session, so admin may read every session's
        announcements. Named differently from :meth:`for_recipient` so that
        "see everything" is always an explicit choice at the call site rather
        than something a missing argument can fall back into.
        """
        cursor = self._find_many(
            {
                "deleted_at": None,
                "$or": [{"recipient_id": user_id}, {"kind": "announcement"}],
            },
            sort=[("created_at", -1)],
            limit=_READ_LIMIT,
        )
        return [self._to_domain(d) async for d in cursor]

    async def list_announcements(self) -> list[Message]:
        cursor = self._find_many(
            {"kind": "announcement", "deleted_at": None},
            sort=[("created_at", -1)],
            limit=_READ_LIMIT,
        )
        return [self._to_domain(d) async for d in cursor]

    async def for_session(self, session_id: str) -> list[Message]:
        """One session's announcement history, newest first."""
        cursor = self._find_many(
            {
                "kind": "announcement",
                "scope_type": SESSION_SCOPE,
                "scope_id": session_id,
                "deleted_at": None,
            },
            sort=[("created_at", -1)],
            limit=_READ_LIMIT,
        )
        return [self._to_domain(d) async for d in cursor]

    async def get(self, message_id: str) -> Message | None:
        doc = await self._find_one({"message_id": message_id, "deleted_at": None})
        return self._to_domain(doc) if doc else None

    async def soft_delete(self, message_id: str, deleted_by: str) -> None:
        """Hide a message without losing it.

        A delete cannot recall an email that has already been sent, so the
        record of what was posted (and by whom) has to outlive the post. The
        read predicate carries the one extra clause that hides it.
        """
        await self._update_one(
            {"message_id": message_id, "deleted_at": None},
            {"$set": {"deleted_at": datetime.now(UTC), "deleted_by": deleted_by}},
        )

    async def mark_read(
        self, message_id: str, user_id: str, *, visible_session_ids: Sequence[str]
    ) -> None:
        """Idempotently record that ``user_id`` has read ``message_id``.

        Scoped to what the caller can actually read, through the *same*
        :func:`_visibility_filter` the read path uses, on top of the
        ``academy_id`` the tenant-scoped base class injects. The predicate is
        shared rather than repeated: the pre-#614 code wrote it out twice, and
        two copies of a security predicate are two chances for them to drift —
        a parent could otherwise stamp a read receipt onto an announcement for
        a class their child is not in. A non-matching id is simply a no-op:
        callers always get the same response, so this is not an existence
        oracle.
        """
        await self._update_one(
            {
                "message_id": message_id,
                **_visibility_filter(user_id, visible_session_ids),
            },
            {"$addToSet": {"read_by": user_id}},
        )


@dataclass
class CommsService:
    """Thin CRUD service used by admin/parent/coach BFFs alike."""

    messages: MongoMessageRepository
    academy_id: str

    async def send_dm(
        self,
        *,
        sender_id: str,
        sender_persona: Persona,
        recipient_id: str,
        body: str,
    ) -> Message:
        m = Message(
            message_id=str(new_ulid()),
            academy_id=self.academy_id,
            kind="dm",
            sender_id=sender_id,
            sender_persona=sender_persona,
            recipient_id=recipient_id,
            body=body,
            created_at=datetime.now(UTC),
        )
        await self.messages.insert(m)
        return m

    async def send_broadcast(
        self,
        *,
        sender_id: str,
        body: str,
        scope_type: str = "academy",
        scope_label: str | None = None,
    ) -> Message:
        m = Message(
            message_id=str(new_ulid()),
            academy_id=self.academy_id,
            kind="announcement",
            sender_id=sender_id,
            sender_persona="admin",
            recipient_id=None,
            body=body,
            created_at=datetime.now(UTC),
            scope_type=scope_type,
            scope_label=scope_label or "Whole academy announcement",
            recipient_count=None,
            delivery_status="recorded",
        )
        await self.messages.insert(m)
        return m

    async def post_session_announcement(
        self,
        *,
        session_id: str,
        session_title: str,
        author_id: str,
        author_persona: Persona,
        author_display_name: str | None,
        body: str,
        urgency: Urgency = "routine",
    ) -> Message:
        """Write a session-scoped announcement to the shared messages store.

        Deliberately the same collection, the same ``Message`` and the same
        service as DMs and academy broadcasts: an announcement is a message
        with a narrower audience, not a second messaging system. The body is
        stored RAW — escaping is a render concern, and pre-escaping here would
        double-escape in the portal, which renders it as a React text child.
        """
        m = Message(
            message_id=str(new_ulid()),
            # Read live rather than from `self.academy_id`: this service is
            # built once per composition with a settings-derived fallback, and
            # in multi-academy mode that value is not the request's tenant.
            # (The stored document is scoped by the repository either way —
            # `insert` drops this field — but the returned object is rendered.)
            academy_id=current_academy_id(),
            kind="announcement",
            sender_id=author_id,
            sender_persona=author_persona,
            recipient_id=None,
            body=body,
            created_at=datetime.now(UTC),
            scope_type=SESSION_SCOPE,
            scope_id=session_id,
            scope_label=session_title,
            urgency=urgency,
            author_display_name=author_display_name,
            delivery_status="recorded",
        )
        await self.messages.insert(m)
        return m

    async def list_session_announcements(self, session_id: str) -> list[Message]:
        return await self.messages.for_session(session_id)

    async def get_message(self, message_id: str) -> Message | None:
        return await self.messages.get(message_id)

    async def soft_delete_message(self, message_id: str, *, deleted_by: str) -> None:
        await self.messages.soft_delete(message_id, deleted_by)

    async def list_for(self, user_id: str) -> list[Message]:
        """Admin's inbox. Admin composition is the only caller."""
        return await self.messages.for_admin(user_id)
