"""Mongo implementation of TenantBootstrapStore."""

from __future__ import annotations

from typing import Any

from pymongo import ReturnDocument


class MongoTenantBootstrapStore:
    """Implements TenantBootstrapStore protocol for Mongo.

    Each `ensure_*` method is idempotent — safe to call on re-bootstrap.
    """

    def __init__(self, db: Any) -> None:
        self._db = db

    async def find_academy_by_slug(self, slug: str) -> dict[str, Any] | None:
        return await self._db.academies.find_one({"slug": slug})

    async def find_academy_by_domain(self, domain: str) -> dict[str, Any] | None:
        return await self._db.academies.find_one({"primary_domain": domain})

    async def create_academy(self, academy: dict[str, Any]) -> dict[str, Any]:
        # Use find_one_and_update to be race-safe against the slug unique index.
        # `_AcademyLookupAdapter.find_by_domain` (in main.py) queries
        # `custom_domain`, so we mirror `primary_domain` into `custom_domain`
        # at bootstrap time until the dedicated `academy_domains` collection
        # lands. Without this, tenant resolution by custom domain breaks.
        to_insert = {
            **academy,
            "custom_domain": academy["primary_domain"],
        }
        doc = await self._db.academies.find_one_and_update(
            {"slug": academy["slug"]},
            {"$setOnInsert": to_insert},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return doc

    async def ensure_owner_user(self, user: dict[str, Any]) -> dict[str, Any]:
        doc = await self._db.users.find_one_and_update(
            {"email": user["email"]},
            {"$setOnInsert": user},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return doc

    async def ensure_owner_membership(self, membership: dict[str, Any]) -> dict[str, Any]:
        doc = await self._db.academy_memberships.find_one_and_update(
            {"academy_id": membership["academy_id"], "user_id": membership["user_id"]},
            {"$setOnInsert": membership},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return doc

    async def ensure_waiver_template(self, waiver: dict[str, Any]) -> dict[str, Any]:
        doc = await self._db.waiver_templates.find_one_and_update(
            {"academy_id": waiver["academy_id"]},
            {"$setOnInsert": waiver},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return doc
