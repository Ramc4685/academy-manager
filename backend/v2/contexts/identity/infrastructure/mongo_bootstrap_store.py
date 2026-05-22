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

    async def ensure_academy_settings(self, settings: dict[str, Any]) -> dict[str, Any]:
        doc = await self._db.academy_settings.find_one_and_update(
            {"academy_id": settings["academy_id"]},
            {"$setOnInsert": settings},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return doc

    async def ensure_billing_policy(self, policy: dict[str, Any]) -> dict[str, Any]:
        doc = await self._db.billing_policies.find_one_and_update(
            {"academy_id": policy["academy_id"]},
            {"$setOnInsert": policy},
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

    async def ensure_default_roles(
        self, academy_id: str, roles: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        # Tenant-owned collection name is `academy_roles` (see
        # tests/test_no_raw_tenant_mongo_access.py canonical list).
        result = []
        for role in roles:
            doc = await self._db.academy_roles.find_one_and_update(
                {"academy_id": academy_id, "role": role["role"]},
                {"$setOnInsert": role},
                upsert=True,
                return_document=ReturnDocument.AFTER,
            )
            result.append(doc)
        return result

    async def ensure_feature_flags(self, flags: dict[str, Any]) -> dict[str, Any]:
        # Tenant-owned collection name is `academy_feature_flags`.
        doc = await self._db.academy_feature_flags.find_one_and_update(
            {"academy_id": flags["academy_id"]},
            {"$setOnInsert": flags},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return doc
