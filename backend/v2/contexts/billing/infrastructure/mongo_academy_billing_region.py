"""Mongo reader for the country / currency a connected account is created in.

Reads two optional fields of the (global) ``academies`` record by
``academy_id``. Absent record or field -> US / USD, the same defaults the
academy profile reads ``currency`` with. Read-only.
"""

from __future__ import annotations

from typing import Any

from backend.v2.contexts.billing.domain.connect_region import ConnectAccountRegion


class MongoAcademyBillingRegionReader:
    def __init__(self, db: Any) -> None:  # AsyncIOMotorDatabase
        self._db = db

    async def get_region(self, academy_id: str) -> ConnectAccountRegion:
        doc = await self._db["academies"].find_one(
            {"academy_id": academy_id},
            projection={"_id": 0, "country": 1, "currency": 1},
        )
        doc = doc or {}
        return ConnectAccountRegion.from_stored(
            country=doc.get("country"), currency=doc.get("currency")
        )
