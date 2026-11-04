"""Mongo repositories for ``family_notes`` and ``family_follow_ups`` (migration 0195).

Both extend ``TenantScopedRepository``: ``academy_id`` comes from the tenant
context on every query and every insert, never from the caller's object.
Every read also filters ``parent_id``, so a note or follow-up id from another
family (or another academy) is never found. ``due_on`` is stored as an ISO
``YYYY-MM-DD`` string, which sorts and range-compares as the date does.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from typing import Any, cast

from pymongo.errors import DuplicateKeyError

from backend.v2.contexts.crm.domain.errors import DuplicateCrmRecordId
from backend.v2.contexts.crm.domain.family_notes import (
    FamilyFollowUp,
    FamilyNote,
    FollowUpStatus,
)
from backend.v2.shared.tenancy import TenantScopedRepository, current_academy_id
from backend.v2.shared.time import ensure_utc

#: A live note: never soft-deleted. ``None`` also matches a missing field.
_LIVE: dict[str, Any] = {"deleted_at": None}


def _utc(value: object) -> datetime:
    return ensure_utc(cast(datetime, value))


def _opt_utc(value: object) -> datetime | None:
    return None if value is None else _utc(value)


class MongoFamilyNoteRepository(TenantScopedRepository):
    collection_name = "family_notes"

    @staticmethod
    def _to_domain(doc: Mapping[str, Any]) -> FamilyNote:
        return FamilyNote(
            note_id=str(doc["note_id"]),
            academy_id=str(doc["academy_id"]),
            parent_id=str(doc["parent_id"]),
            body=str(doc["body"]),
            author_user_id=str(doc["author_user_id"]),
            created_at=_utc(doc["created_at"]),
            updated_at=_utc(doc.get("updated_at") or doc["created_at"]),
            deleted_at=_opt_utc(doc.get("deleted_at")),
            deleted_by=doc.get("deleted_by"),
        )

    async def add(self, note: FamilyNote) -> FamilyNote:
        doc = note.model_dump(mode="python")
        doc["academy_id"] = current_academy_id()
        try:
            await self._insert_one(doc)
        except DuplicateKeyError as exc:
            raise DuplicateCrmRecordId("note id already exists", note_id=note.note_id) from exc
        return self._to_domain(doc)

    async def get(self, parent_id: str, note_id: str) -> FamilyNote | None:
        doc = await self._find_one({"note_id": note_id, "parent_id": parent_id, **_LIVE})
        return self._to_domain(doc) if doc else None

    async def list_for_family(self, parent_id: str, *, limit: int = 200) -> list[FamilyNote]:
        cursor = self._find_many(
            {"parent_id": parent_id, **_LIVE}, sort=[("created_at", -1)], limit=limit
        )
        return [self._to_domain(doc) async for doc in cursor]

    async def update_body(
        self, parent_id: str, note_id: str, *, body: str, updated_at: datetime
    ) -> FamilyNote | None:
        doc = await self._find_one_and_update(
            {"note_id": note_id, "parent_id": parent_id, **_LIVE},
            {"$set": {"body": body, "updated_at": updated_at}},
        )
        return self._to_domain(doc) if doc else None

    async def soft_delete(
        self, parent_id: str, note_id: str, *, deleted_by: str, deleted_at: datetime
    ) -> bool:
        result = await self._update_one(
            {"note_id": note_id, "parent_id": parent_id, **_LIVE},
            {"$set": {"deleted_at": deleted_at, "deleted_by": deleted_by}},
        )
        return bool(result.matched_count)


def _date_key(value: date) -> str:
    return value.isoformat()


class MongoFamilyFollowUpRepository(TenantScopedRepository):
    collection_name = "family_follow_ups"

    @staticmethod
    def _to_doc(follow_up: FamilyFollowUp) -> dict[str, Any]:
        doc = follow_up.model_dump(mode="python")
        doc["academy_id"] = current_academy_id()
        doc["due_on"] = _date_key(follow_up.due_on)
        return doc

    @staticmethod
    def _to_domain(doc: Mapping[str, Any]) -> FamilyFollowUp:
        return FamilyFollowUp(
            follow_up_id=str(doc["follow_up_id"]),
            academy_id=str(doc["academy_id"]),
            parent_id=str(doc["parent_id"]),
            title=str(doc["title"]),
            due_on=date.fromisoformat(str(doc["due_on"])),
            assignee_user_id=str(doc["assignee_user_id"]),
            status=doc.get("status", "open"),
            created_by=str(doc["created_by"]),
            created_at=_utc(doc["created_at"]),
            updated_at=_utc(doc.get("updated_at") or doc["created_at"]),
            done_at=_opt_utc(doc.get("done_at")),
            done_by=doc.get("done_by"),
            source_key=doc.get("source_key") or None,
        )

    async def add_once(self, follow_up: FamilyFollowUp) -> bool:
        """Insert a job-created follow-up unless one with its ``source_key``
        already exists in this academy. True when this call inserted it.

        One upsert on ``(academy_id, source_key)``, backed by the unique
        partial index of migration 0201: two machines (or two ticks) racing
        on the same key insert one row, and the loser's duplicate-key error
        reads as "already there". A row a person later edited or marked done
        is matched too, so it is never recreated.
        """
        if not follow_up.source_key:
            raise ValueError("add_once needs a source_key")
        doc = self._to_doc(follow_up)
        doc.pop("academy_id", None)
        doc.pop("source_key", None)
        try:
            result = await self._update_one(
                {"source_key": follow_up.source_key}, {"$setOnInsert": doc}, upsert=True
            )
        except DuplicateKeyError:
            return False
        return result.upserted_id is not None

    async def add(self, follow_up: FamilyFollowUp) -> FamilyFollowUp:
        doc = self._to_doc(follow_up)
        try:
            await self._insert_one(doc)
        except DuplicateKeyError as exc:
            raise DuplicateCrmRecordId(
                "follow-up id already exists", follow_up_id=follow_up.follow_up_id
            ) from exc
        return self._to_domain(doc)

    async def get(self, parent_id: str, follow_up_id: str) -> FamilyFollowUp | None:
        doc = await self._find_one({"follow_up_id": follow_up_id, "parent_id": parent_id})
        return self._to_domain(doc) if doc else None

    async def list_for_family(self, parent_id: str, *, limit: int = 200) -> list[FamilyFollowUp]:
        cursor = self._find_many({"parent_id": parent_id}, sort=[("created_at", -1)], limit=limit)
        return [self._to_domain(doc) async for doc in cursor]

    async def update(
        self, parent_id: str, follow_up_id: str, *, changes: Mapping[str, object]
    ) -> FamilyFollowUp | None:
        fields = {
            key: (_date_key(value) if isinstance(value, date) and key == "due_on" else value)
            for key, value in changes.items()
        }
        doc = await self._find_one_and_update(
            {"follow_up_id": follow_up_id, "parent_id": parent_id}, {"$set": fields}
        )
        return self._to_domain(doc) if doc else None

    async def list_by_status(
        self,
        status: FollowUpStatus,
        *,
        assignee_user_id: str | None = None,
        due_before: date | None = None,
        due_on: date | None = None,
        due_after: date | None = None,
        limit: int = 200,
    ) -> list[FamilyFollowUp]:
        query: dict[str, Any] = {"status": status}
        if assignee_user_id is not None:
            query["assignee_user_id"] = assignee_user_id
        window: dict[str, str] = {}
        if due_before is not None:
            window["$lt"] = _date_key(due_before)
        if due_after is not None:
            window["$gt"] = _date_key(due_after)
        if due_on is not None:
            query["due_on"] = _date_key(due_on)
        elif window:
            query["due_on"] = window
        sort = [("done_at", -1)] if status == "done" else [("due_on", 1), ("created_at", 1)]
        cursor = self._find_many(query, sort=sort, limit=limit)
        return [self._to_domain(doc) async for doc in cursor]
