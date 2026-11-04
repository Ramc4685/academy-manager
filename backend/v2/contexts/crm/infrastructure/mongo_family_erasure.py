"""Erase a family's CRM records after a self-service account deletion (M5, D3).

Free-text notes, follow-ups, the contact log, extra guardians, the family's
address and the lead row it converted from carry nothing the academy must keep,
so they are deleted outright. Every query names its ``academy_id``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

_BY_PARENT = (
    "family_contacts",
    "family_details",
    "family_notes",
    "family_follow_ups",
    "family_contact_log",
)


class MongoFamilyErasure:
    def __init__(self, db: Any) -> None:
        self._db = db

    async def guardian_emails(self, *, academy_id: str, parent_ids: Sequence[str]) -> list[str]:
        """Emails of the family's other guardians (``family_contacts``)."""
        cursor = self._db["family_contacts"].find(
            {"academy_id": academy_id, "parent_id": {"$in": list(parent_ids)}},
            {"email": 1},
        )
        return [str(doc["email"]) async for doc in cursor if doc.get("email")]

    async def erase_family(self, *, academy_id: str, parent_ids: Sequence[str]) -> None:
        ids = list(parent_ids)
        for name in _BY_PARENT:
            await self._db[name].delete_many({"academy_id": academy_id, "parent_id": {"$in": ids}})
        await self._db["crm_contacts"].delete_many(
            {
                "academy_id": academy_id,
                "$or": [
                    {"converted_parent_id": {"$in": ids}},
                    {"linked_family_id": {"$in": ids}},
                ],
            }
        )
