"""Mongo repository for ``crm_contacts`` (migration 0192)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from pymongo.errors import DuplicateKeyError

from backend.v2.contexts.crm.domain.models import (
    ContactConsent,
    CrmContact,
    PipelineOverride,
    PipelineStatus,
)
from backend.v2.shared.tenancy import TenantScopedRepository, current_academy_id
from backend.v2.shared.time import ensure_utc

#: Built by migration 0192. Named here so a duplicate on any OTHER unique
#: index (a contact_id collision) is re-raised, not mistaken for a repeat.
DEDUPE_INDEX_NAME = "crm_contacts_academy_dedupe_unique"


class MongoCrmContactRepository(TenantScopedRepository):
    collection_name = "crm_contacts"

    @staticmethod
    def _to_doc(contact: CrmContact) -> dict[str, Any]:
        doc = contact.model_dump(mode="python")
        # Never trust a caller-built academy_id: the tenant context owns it.
        doc["academy_id"] = current_academy_id()
        return doc

    @staticmethod
    def _to_domain(doc: dict[str, Any]) -> CrmContact:
        consent_doc = dict(doc.get("consent") or {})
        if consent_doc.get("captured_at") is not None:
            consent_doc["captured_at"] = _utc(consent_doc["captured_at"])
        override_doc = doc.get("pipeline_override")
        override = None
        if override_doc:
            override = PipelineOverride(
                column=str(override_doc["column"]),
                set_by=str(override_doc["set_by"]),
                set_at=_utc(override_doc["set_at"]),
            )
        return CrmContact(
            contact_id=str(doc["contact_id"]),
            academy_id=str(doc["academy_id"]),
            name=str(doc["name"]),
            email=doc.get("email"),
            phone_digits=doc.get("phone_digits"),
            source=doc["source"],
            child_name=doc.get("child_name"),
            child_age=doc.get("child_age"),
            requested_session_id=doc.get("requested_session_id"),
            pipeline_status=doc.get("pipeline_status", "lead"),
            pipeline_override=override,
            referrer_parent_id=doc.get("referrer_parent_id"),
            converted_parent_id=doc.get("converted_parent_id"),
            linked_family_id=doc.get("linked_family_id"),
            linked_user_id=doc.get("linked_user_id"),
            consent=ContactConsent(**consent_doc),
            created_by=doc.get("created_by"),
            dedupe_key=str(doc["dedupe_key"]),
            created_at=_utc(doc["created_at"]),
            updated_at=_utc(doc.get("updated_at") or doc["created_at"]),
        )

    async def add_if_absent(self, contact: CrmContact) -> tuple[CrmContact, bool]:
        doc = self._to_doc(contact)
        try:
            await self._insert_one(doc)
        except DuplicateKeyError as exc:
            if not _is_dedupe_collision(exc):
                raise
            existing = await self.find_by_dedupe_key(contact.dedupe_key)
            if existing is None:  # pragma: no cover - index says it exists
                raise
            return existing, False
        return self._to_domain(doc), True

    async def get(self, contact_id: str) -> CrmContact | None:
        doc = await self._find_one({"contact_id": contact_id})
        return self._to_domain(doc) if doc else None

    async def find_by_dedupe_key(self, dedupe_key: str) -> CrmContact | None:
        # Equality on the partial index key: served by
        # crm_contacts_academy_dedupe_unique (partial filter {"$gt": ""}).
        doc = await self._find_one({"dedupe_key": dedupe_key})
        return self._to_domain(doc) if doc else None

    async def list_by_pipeline_status(
        self, status: PipelineStatus | None = None, *, limit: int = 200
    ) -> list[CrmContact]:
        query: dict[str, Any] = {} if status is None else {"pipeline_status": status}
        cursor = self._find_many(query, sort=[("created_at", -1)], limit=limit)
        return [self._to_domain(doc) async for doc in cursor]


def _is_dedupe_collision(exc: DuplicateKeyError) -> bool:
    details = exc.details or {}
    if details.get("keyPattern"):
        return "dedupe_key" in details["keyPattern"]
    return DEDUPE_INDEX_NAME in str(exc) or "dedupe_key" in str(exc)


def _utc(value: object) -> datetime:
    """A BSON datetime read back naive, as the aware UTC instant it always was (#706)."""
    return ensure_utc(cast(datetime, value))
