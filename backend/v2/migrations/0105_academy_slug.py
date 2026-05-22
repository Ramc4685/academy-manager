"""Add slug + academy_id to academies collection (A2).

- slug: lowercased _id value (dashes preserved); used by TenantResolver.find_by_slug
- academy_id: equals _id; satisfies _AcademyLookupAdapter query pattern
- Creates unique sparse index on slug.
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0105_academy_slug"


async def up(db: AsyncIOMotorDatabase) -> None:
    async for doc in db.academies.find({}):
        _id = str(doc["_id"])
        slug = doc.get("slug") or _id.lower()
        academy_id = doc.get("academy_id") or _id
        await db.academies.update_one(
            {"_id": doc["_id"]},
            {"$set": {"slug": slug, "academy_id": academy_id}},
        )
    await db.academies.create_index(
        "slug",
        name="academies_slug_unique",
        unique=True,
        sparse=True,
    )
