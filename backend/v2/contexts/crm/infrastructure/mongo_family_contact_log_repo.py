"""Mongo repository for ``family_contact_log`` (migration 0203, People CRM L4c).

``TenantScopedRepository``: ``academy_id`` comes from the tenant context on
every query and every insert, never from the caller's object. Every read also
filters ``parent_id``, so a log id from another family (or another academy)
is never found.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any, cast

from pymongo.errors import DuplicateKeyError

from backend.v2.contexts.crm.domain.errors import DuplicateCrmRecordId
from backend.v2.contexts.crm.domain.family_messages import MESSAGES_CAP, FamilyContactLog
from backend.v2.shared.tenancy import TenantScopedRepository, current_academy_id
from backend.v2.shared.time import ensure_utc


def _utc(value: object) -> datetime:
    return ensure_utc(cast(datetime, value))


class MongoFamilyContactLogRepository(TenantScopedRepository):
    collection_name = "family_contact_log"

    @staticmethod
    def _to_domain(doc: Mapping[str, Any]) -> FamilyContactLog:
        logged_at = doc.get("logged_at")
        return FamilyContactLog(
            log_id=str(doc["log_id"]),
            academy_id=str(doc["academy_id"]),
            parent_id=str(doc["parent_id"]),
            channel=doc["channel"],
            status=doc.get("status", "logged"),
            note=doc.get("note") or None,
            author_user_id=str(doc["author_user_id"]),
            created_at=_utc(doc["created_at"]),
            updated_at=_utc(doc.get("updated_at") or doc["created_at"]),
            logged_at=_utc(logged_at) if logged_at is not None else None,
        )

    async def add(self, entry: FamilyContactLog) -> FamilyContactLog:
        doc = entry.model_dump(mode="python")
        doc["academy_id"] = current_academy_id()
        try:
            await self._insert_one(doc)
        except DuplicateKeyError as exc:
            raise DuplicateCrmRecordId("log id already exists", log_id=entry.log_id) from exc
        return self._to_domain(doc)

    async def get(self, parent_id: str, log_id: str) -> FamilyContactLog | None:
        doc = await self._find_one({"log_id": log_id, "parent_id": parent_id})
        return self._to_domain(doc) if doc else None

    async def list_for_family(
        self, parent_id: str, *, limit: int = MESSAGES_CAP
    ) -> list[FamilyContactLog]:
        # Served by family_contact_log_academy_parent_created (0203).
        cursor = self._find_many({"parent_id": parent_id}, sort=[("created_at", -1)], limit=limit)
        return [self._to_domain(doc) async for doc in cursor]

    async def mark_logged(
        self, parent_id: str, log_id: str, *, note: str | None, logged_at: datetime
    ) -> FamilyContactLog | None:
        changes: dict[str, Any] = {
            "status": "logged",
            "logged_at": logged_at,
            "updated_at": logged_at,
        }
        if note is not None:
            changes["note"] = note
        # Conditional on not_logged: two staff completing at once write once.
        doc = await self._find_one_and_update(
            {"log_id": log_id, "parent_id": parent_id, "status": "not_logged"},
            {"$set": changes},
        )
        return self._to_domain(doc) if doc else None
