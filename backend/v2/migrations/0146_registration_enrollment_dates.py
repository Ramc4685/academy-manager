"""Backfill enrollment dates created by parent registration approval."""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0146_registration_enrollment_dates"


async def up(db: AsyncIOMotorDatabase) -> None:
    applications = db["onboarding_applications"].find(
        {
            "status": "APPROVED",
            "enrollment_id": {"$exists": True, "$ne": None},
            "created_at": {"$type": "date"},
        },
        {"academy_id": 1, "enrollment_id": 1, "created_at": 1},
    )
    async for application in applications:
        await db["enrollments"].update_one(
            {
                "academy_id": application["academy_id"],
                "enrollment_id": application["enrollment_id"],
                "$or": [
                    {"enrolled_at": {"$exists": False}},
                    {"enrolled_at": None},
                ],
            },
            {"$set": {"enrolled_at": application["created_at"]}},
        )
