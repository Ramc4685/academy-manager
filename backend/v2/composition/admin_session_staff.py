"""Admin: a session's coaching staff beyond the primary coach.

Assistant coaches (role ``assistant_coach``) are listed per session in
``Session.assistant_coach_ids``. That list is what scopes the coach surface
for a helper, so changing it has to (a) only ever name people who really hold
a coaching role in this academy and (b) reach the dated occurrences the
attendance use cases check — future ones only; past occurrences keep the
staff they actually ran with.

Kept out of ``composition/admin.py`` (at its line cap); wired from there.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any, Protocol

from bson import ObjectId as BsonObjectId

from backend.v2.contexts.enrollment.domain.errors import SessionNotFound
from backend.v2.contexts.enrollment.domain.models import Session
from backend.v2.contexts.identity.domain.identity_aliases import identity_aliases
from backend.v2.contexts.identity.domain.models import AcademyMembership
from backend.v2.shared.http.errors import DomainError
from backend.v2.shared.tenancy.context import current_academy_id

log = logging.getLogger(__name__)

#: Academy roles that may be listed as a session assistant. A full coach may
#: assist on someone else's class; parents/students/admins never appear here
#: (an admin covers sessions through supervision, not by being listed).
ASSISTANT_ELIGIBLE_ROLES: frozenset[str] = frozenset({"coach", "assistant_coach"})


class InvalidSessionAssistant(DomainError):
    code = "Enrollment.InvalidSessionAssistant"
    status_code = 422


class _SessionStore(Protocol):
    async def get(self, session_id: str) -> Session | None: ...
    async def update(self, session: Session) -> None: ...


class _OccurrenceSync(Protocol):
    async def sync_assistant_coach_ids_for_session(
        self, *, session_id: str, assistant_coach_ids: Sequence[str], since: datetime
    ) -> int: ...


class _MembershipLookup(Protocol):
    async def get_membership(
        self, academy_id: str, user_id: str, *, aliases: Sequence[str] | None = None
    ) -> AcademyMembership | None: ...


class _UserLookup(Protocol):
    async def get_by_id(self, user_id: str) -> Any: ...


def normalize_assistant_ids(values: Sequence[str]) -> tuple[str, ...]:
    """Trim, drop blanks, dedupe preserving order."""
    seen: dict[str, None] = {}
    for value in values:
        cleaned = str(value or "").strip()
        if cleaned:
            seen.setdefault(cleaned, None)
    return tuple(seen)


class SetSessionAssistants:
    """Replace a session's assistant list and re-sync its future occurrences."""

    def __init__(
        self,
        *,
        sessions: _SessionStore,
        occurrences: _OccurrenceSync,
        memberships: _MembershipLookup,
        users: _UserLookup,
        academy_id: Callable[[], str],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._sessions = sessions
        self._occurrences = occurrences
        self._memberships = memberships
        self._users = users
        self._academy_id = academy_id
        self._clock = clock

    async def execute(
        self,
        *,
        session_id: str,
        assistant_coach_ids: Sequence[str],
        actor_id: str,
        reason: str | None = None,
    ) -> Session:
        session = await self._sessions.get(session_id)
        if session is None:
            raise SessionNotFound("session missing", session_id=session_id)

        ids = normalize_assistant_ids(assistant_coach_ids)
        if session.coach_id in ids:
            raise InvalidSessionAssistant(
                "the session's primary coach cannot also be listed as its assistant",
                session_id=session_id,
                user_id=session.coach_id,
            )
        academy_id = self._academy_id()
        for user_id in ids:
            await self._ensure_eligible(academy_id, user_id, session_id=session_id)

        updated = session.model_copy(update={"assistant_coach_ids": ids})
        await self._sessions.update(updated)
        synced = await self._occurrences.sync_assistant_coach_ids_for_session(
            session_id=session_id, assistant_coach_ids=ids, since=self._clock()
        )
        log.info(
            "admin.session_assistants_set",
            extra={
                "academy_id": academy_id,
                "session_id": session_id,
                "assistant_coach_ids": list(ids),
                "future_occurrences_synced": synced,
                "actor_id": actor_id,
                "reason": reason,
            },
        )
        return updated

    async def _ensure_eligible(self, academy_id: str, user_id: str, *, session_id: str) -> None:
        # Same alias-aware membership read `load_auth_claims` builds request
        # claims from, so "eligible here" and "will get coach claims here"
        # can never disagree.
        user = await self._users.get_by_id(user_id)
        aliases = identity_aliases(user.user_id, user.firebase_uid, user.auth_uid) if user else ()
        membership = await self._memberships.get_membership(academy_id, user_id, aliases=aliases)
        if membership is None or not membership.is_active():
            raise InvalidSessionAssistant(
                "assistant must be an active member of this academy",
                session_id=session_id,
                user_id=user_id,
            )
        if not any(role in ASSISTANT_ELIGIBLE_ROLES for role in membership.roles):
            raise InvalidSessionAssistant(
                "assistant must hold the coach or assistant_coach role",
                session_id=session_id,
                user_id=user_id,
            )


async def attach_session_staff_names(db: Any, rows: list[dict[str, Any]]) -> None:
    """Fill ``coach_name`` and ``assistant_coach_names`` on admin session rows.

    Two batched queries for every coach and assistant id across ``rows`` (no
    N+1): one ``users`` ``$in`` for the candidate accounts, then one
    ``academy_memberships`` ``$in`` carrying an explicit ``academy_id``.
    ``users`` is global (an identity spans academies), so a membership row in
    the *current* academy is the only thing that makes a name attachable here
    — without that gate an id reused by, or colliding with, another academy
    renders that academy's person on this roster. Same shape as
    ``MongoAuditActorDirectory``; the tenant is read at execution time, never
    captured when the composition is wired.

    Ids are matched the way the directory keys users: ``user_id``,
    ``firebase_uid`` or the raw ``_id``, and the membership hop is alias-aware
    for the same reason ``get_membership`` is (a roster ``user_id`` on the
    session, a provisioned ``firebase_uid`` on the membership row). Ids with
    no membership in this academy stay unresolvable: ``None`` for the coach,
    skipped for assistants, so the view stays well-typed.
    """
    wanted: set[str] = set()
    for row in rows:
        if row.get("coach_id"):
            wanted.add(str(row["coach_id"]))
        wanted.update(str(uid) for uid in row.get("assistant_coach_ids") or [] if uid)

    names: dict[str, str] = {}
    if wanted:
        academy_id = current_academy_id()
        ids = sorted(wanted)
        or_filter: list[dict[str, object]] = [
            {"user_id": {"$in": ids}},
            {"auth_uid": {"$in": ids}},
            {"firebase_uid": {"$in": ids}},
        ]
        oid_ids = [BsonObjectId(uid) for uid in ids if BsonObjectId.is_valid(uid)]
        if oid_ids:
            or_filter.append({"_id": {"$in": oid_ids}})

        # (aliases this account may be keyed by, its display name)
        candidates: list[tuple[tuple[str, ...], str]] = []
        alias_pool: set[str] = set(wanted)
        async for user_doc in db["users"].find({"$or": or_filter}):
            name = str(
                user_doc.get("display_name")
                or f"{user_doc.get('first_name', '')} {user_doc.get('last_name', '')}".strip()
                or ""
            )
            doc_aliases = identity_aliases(
                user_doc.get("user_id"),
                user_doc.get("auth_uid"),
                user_doc.get("firebase_uid"),
                user_doc.get("_id"),
            )
            candidates.append((doc_aliases, name))
            alias_pool.update(doc_aliases)

        member_ids = {
            str(doc.get("user_id"))
            async for doc in db["academy_memberships"].find(
                {"academy_id": academy_id, "user_id": {"$in": sorted(alias_pool)}},
                {"user_id": 1},
            )
        }

        for doc_aliases, name in candidates:
            if not member_ids.intersection(doc_aliases):
                continue
            for key in doc_aliases:
                if key in wanted:
                    names[key] = name

    for row in rows:
        row["coach_name"] = names.get(str(row.get("coach_id") or ""))
        row["assistant_coach_names"] = [
            names[str(uid)] for uid in row.get("assistant_coach_ids") or [] if str(uid) in names
        ]


def compose_set_session_assistants(
    *,
    sessions: _SessionStore,
    occurrences: _OccurrenceSync,
    memberships: _MembershipLookup,
    users: _UserLookup,
    academy_id: Callable[[], str],
) -> SetSessionAssistants:
    return SetSessionAssistants(
        sessions=sessions,
        occurrences=occurrences,
        memberships=memberships,
        users=users,
        academy_id=academy_id,
    )
