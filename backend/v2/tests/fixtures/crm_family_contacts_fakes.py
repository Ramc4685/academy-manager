"""In-memory stand-ins for the family contacts / details stores (migration 0196).

They mirror the Mongo repositories, not a permissive dict:

* the academy comes from the tenant ContextVar on every read and write;
* ``(academy_id, contact_id)`` is unique (``DuplicateCrmRecordId``);
* ``(academy_id, parent_id, email)`` is unique only for rows that HAVE an
  email (the partial ``{email: {$gt: ""}}`` index), on add and on update
  (``DuplicateFamilyContactEmail``);
* an empty email / phone is an absent field; every read filters ``parent_id``;
* the details store keeps one row per ``(academy_id, parent_id)``.

``test_crm_family_contacts_real_mongo.py`` runs the same rules against the
real repositories on a real ``mongod``.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from backend.v2.contexts.crm.domain.errors import (
    DuplicateCrmRecordId,
    DuplicateFamilyContactEmail,
)
from backend.v2.contexts.crm.domain.family_contacts import FamilyContact, FamilyDetails
from backend.v2.shared.tenancy import current_academy_id


class FakeFamilyContactRepository:
    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], FamilyContact] = {}

    def _email_taken(self, academy: str, row: FamilyContact) -> bool:
        if not row.email:
            return False
        return any(
            a == academy
            and other.contact_id != row.contact_id
            and other.parent_id == row.parent_id
            and other.email == row.email
            for (a, _), other in self.rows.items()
        )

    async def add(self, contact: FamilyContact) -> FamilyContact:
        academy = current_academy_id()
        key = (academy, contact.contact_id)
        if key in self.rows:
            raise DuplicateCrmRecordId("contact id already exists", contact_id=contact.contact_id)
        stored = contact.model_copy(update={"academy_id": academy})
        if self._email_taken(academy, stored):
            raise DuplicateFamilyContactEmail(
                "This family already has a contact with that email.", field="email"
            )
        self.rows[key] = stored
        return stored

    async def get(self, parent_id: str, contact_id: str) -> FamilyContact | None:
        row = self.rows.get((current_academy_id(), contact_id))
        return row if row is not None and row.parent_id == parent_id else None

    async def list_for_family(self, parent_id: str, *, limit: int = 50) -> list[FamilyContact]:
        academy = current_academy_id()
        rows = [r for (a, _), r in self.rows.items() if a == academy and r.parent_id == parent_id]
        return sorted(rows, key=lambda r: r.created_at)[:limit]

    async def count_for_family(self, parent_id: str) -> int:
        return len(await self.list_for_family(parent_id, limit=10_000))

    async def update(
        self, parent_id: str, contact_id: str, *, changes: Mapping[str, object]
    ) -> FamilyContact | None:
        row = await self.get(parent_id, contact_id)
        if row is None:
            return None
        new = row.model_copy(update={k: (v if v != "" else None) for k, v in changes.items()})
        academy = current_academy_id()
        if self._email_taken(academy, new):
            raise DuplicateFamilyContactEmail(
                "This family already has a contact with that email.", field="email"
            )
        self.rows[(academy, contact_id)] = new
        return new

    async def delete(self, parent_id: str, contact_id: str) -> bool:
        if await self.get(parent_id, contact_id) is None:
            return False
        del self.rows[(current_academy_id(), contact_id)]
        return True


class FakeFamilyDetailsRepository:
    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], FamilyDetails] = {}

    async def get(self, parent_id: str) -> FamilyDetails | None:
        return self.rows.get((current_academy_id(), parent_id))

    async def upsert(
        self,
        parent_id: str,
        *,
        changes: Mapping[str, object],
        updated_by: str,
        updated_at: datetime,
    ) -> FamilyDetails:
        academy = current_academy_id()
        current = self.rows.get((academy, parent_id)) or FamilyDetails(
            academy_id=academy, parent_id=parent_id
        )
        update = dict(changes)
        if "tags" in update:
            update["tags"] = tuple(update["tags"] or ())  # type: ignore[arg-type]
        new = current.model_copy(
            update={**update, "updated_by": updated_by, "updated_at": updated_at}
        )
        self.rows[(academy, parent_id)] = new
        return new
