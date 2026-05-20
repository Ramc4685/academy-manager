from __future__ import annotations

from typing import Any, Optional
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ReturnDocument


class MongoAcademyRepository:
    def __init__(self, db: AsyncIOMotorDatabase[Any]) -> None:
        self.collection = db["academies"]

    async def find_by_id(self, academy_id: str) -> Optional[dict[str, Any]]:
        doc = await self.collection.find_one({"academy_id": academy_id})
        if not doc:
            return None
        return doc

    async def update_by_id(self, academy_id: str, fields: dict[str, Any]) -> Optional[dict[str, Any]]:
        doc = await self.collection.find_one_and_update(
            {"academy_id": academy_id},
            {"$set": fields},
            return_document=ReturnDocument.AFTER,
        )
        return doc

    async def upsert_defaults(self, academy_id: str) -> dict[str, Any]:
        """Upsert safe defaults for fresh local and tenant bootstrap DBs."""
        default_doc = {
            "academy_id": academy_id,
            "display_name": academy_id,
            "timezone": "UTC",
            "fees": {
                "default_monthly_cents": None,
                "late_fee_cents": None,
                "grace_days": None,
            },
            "manual_methods": ["cash", "check"],
            "notifications": {
                "dues_reminders": False,
                "attendance_alerts": False,
                "daily_digest_to_admin": False,
            },
        }

        doc = await self.collection.find_one_and_update(
            {"academy_id": academy_id},
            {"$setOnInsert": default_doc},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return doc
