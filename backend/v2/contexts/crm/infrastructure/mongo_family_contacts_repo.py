"""Mongo repositories for ``family_contacts`` and ``family_details`` (migration 0196).

Both extend ``TenantScopedRepository``: ``academy_id`` comes from the tenant
context on every query and every insert, never from the caller's object.
Every read also filters ``parent_id``, so a contact id from another family (or
another academy) is never found.

An empty ``email`` / ``phone`` is stored as an ABSENT field, never ``null`` or
``""``: the per-family email guard is a partial unique index filtered on
``{email: {$gt: ""}}`` (#878: never ``$type``), so a contact with no email
takes no slot in it.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any, cast

from pymongo.errors import DuplicateKeyError

from backend.v2.contexts.crm.domain.errors import (
    DuplicateCrmRecordId,
    DuplicateFamilyContactEmail,
)
from backend.v2.contexts.crm.domain.family_contacts import FamilyContact, FamilyDetails
from backend.v2.shared.tenancy import TenantScopedRepository, current_academy_id
from backend.v2.shared.time import ensure_utc

#: Contact fields that are dropped from the document when empty.
_OPTIONAL_CONTACT_FIELDS = ("email", "phone", "phone_digits")


def _utc(value: object) -> datetime:
    return ensure_utc(cast(datetime, value))


def _duplicate_error(exc: DuplicateKeyError, contact_id: str) -> Exception:
    key_pattern = (exc.details or {}).get("keyPattern") or {}
    if "email" in key_pattern or "email" in str(exc):
        return DuplicateFamilyContactEmail(
            "This family already has a contact with that email.", field="email"
        )
    return DuplicateCrmRecordId("contact id already exists", contact_id=contact_id)


class MongoFamilyContactRepository(TenantScopedRepository):
    collection_name = "family_contacts"

    @staticmethod
    def _to_domain(doc: Mapping[str, Any]) -> FamilyContact:
        return FamilyContact(
            contact_id=str(doc["contact_id"]),
            academy_id=str(doc["academy_id"]),
            parent_id=str(doc["parent_id"]),
            name=str(doc["name"]),
            relationship=doc.get("relationship") or "other",
            email=doc.get("email") or None,
            phone=doc.get("phone") or None,
            phone_digits=doc.get("phone_digits") or None,
            gets_notices=bool(doc.get("gets_notices", False)),
            gets_invoices=bool(doc.get("gets_invoices", False)),
            created_by=str(doc.get("created_by") or ""),
            created_at=_utc(doc["created_at"]),
            updated_at=_utc(doc.get("updated_at") or doc["created_at"]),
        )

    async def add(self, contact: FamilyContact) -> FamilyContact:
        doc = contact.model_dump(mode="python")
        for name in _OPTIONAL_CONTACT_FIELDS:
            if not doc.get(name):
                doc.pop(name, None)
        doc["academy_id"] = current_academy_id()
        try:
            await self._insert_one(doc)
        except DuplicateKeyError as exc:
            raise _duplicate_error(exc, contact.contact_id) from exc
        return self._to_domain(doc)

    async def get(self, parent_id: str, contact_id: str) -> FamilyContact | None:
        doc = await self._find_one({"contact_id": contact_id, "parent_id": parent_id})
        return self._to_domain(doc) if doc else None

    async def list_for_family(self, parent_id: str, *, limit: int = 50) -> list[FamilyContact]:
        cursor = self._find_many({"parent_id": parent_id}, sort=[("created_at", 1)], limit=limit)
        return [self._to_domain(doc) async for doc in cursor]

    async def find_by_email(self, email: str, *, limit: int = 5) -> list[FamilyContact]:
        """Contacts on ANY family of the academy with exactly this email.

        Equality on a non-empty string: served by the partial
        ``family_contacts_academy_email_lookup`` index (migration 0197).
        """
        if not email:
            return []
        cursor = self._find_many({"email": email}, limit=limit)
        return [self._to_domain(doc) async for doc in cursor]

    async def find_by_phone_digits(self, digits: str, *, limit: int = 5) -> list[FamilyContact]:
        """Contacts whose stored ``phone_digits`` equal ``digits`` exactly
        (one spelling per call); served by ``family_contacts_academy_phone_lookup``."""
        if not digits:
            return []
        cursor = self._find_many({"phone_digits": digits}, limit=limit)
        return [self._to_domain(doc) async for doc in cursor]

    async def count_for_family(self, parent_id: str) -> int:
        return await self._count({"parent_id": parent_id})

    async def update(
        self, parent_id: str, contact_id: str, *, changes: Mapping[str, object]
    ) -> FamilyContact | None:
        to_set = {k: v for k, v in changes.items() if v is not None and v != ""}
        to_unset = {k: "" for k, v in changes.items() if k in _OPTIONAL_CONTACT_FIELDS and not v}
        update: dict[str, Any] = {}
        if to_set:
            update["$set"] = to_set
        if to_unset:
            update["$unset"] = to_unset
        if not update:
            return await self.get(parent_id, contact_id)
        try:
            doc = await self._find_one_and_update(
                {"contact_id": contact_id, "parent_id": parent_id}, update
            )
        except DuplicateKeyError as exc:
            raise _duplicate_error(exc, contact_id) from exc
        return self._to_domain(doc) if doc else None

    async def delete(self, parent_id: str, contact_id: str) -> bool:
        result = await self._delete_one({"contact_id": contact_id, "parent_id": parent_id})
        return bool(result.deleted_count)


class MongoFamilyDetailsRepository(TenantScopedRepository):
    collection_name = "family_details"

    @staticmethod
    def _to_domain(doc: Mapping[str, Any]) -> FamilyDetails:
        updated_at = doc.get("updated_at")
        return FamilyDetails(
            academy_id=str(doc["academy_id"]),
            parent_id=str(doc["parent_id"]),
            address=doc.get("address") or None,
            preferred_channel=doc.get("preferred_channel") or None,
            heard_about_us=doc.get("heard_about_us") or None,
            tags=tuple(str(t) for t in doc.get("tags") or ()),
            updated_by=doc.get("updated_by"),
            updated_at=_utc(updated_at) if updated_at is not None else None,
        )

    async def get(self, parent_id: str) -> FamilyDetails | None:
        doc = await self._find_one({"parent_id": parent_id})
        return self._to_domain(doc) if doc else None

    async def upsert(
        self,
        parent_id: str,
        *,
        changes: Mapping[str, object],
        updated_by: str,
        updated_at: datetime,
    ) -> FamilyDetails:
        fields = {**changes, "updated_by": updated_by, "updated_at": updated_at}
        try:
            # The equality filter (academy_id from the tenant, parent_id) is
            # copied into the document an upsert inserts.
            doc = await self._find_one_and_update(
                {"parent_id": parent_id}, {"$set": fields}, upsert=True
            )
        except DuplicateKeyError:
            # Two first writes raced: the unique (academy_id, parent_id) index
            # let one insert win; the other is now a plain update.
            doc = await self._find_one_and_update({"parent_id": parent_id}, {"$set": fields})
        if doc is None:  # pragma: no cover - an upsert always returns a document
            raise RuntimeError("family details upsert returned no document")
        return self._to_domain(doc)
