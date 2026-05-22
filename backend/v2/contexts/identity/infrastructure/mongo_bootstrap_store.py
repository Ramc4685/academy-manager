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
        await self._db.academies.insert_one(dict(academy))
        return academy

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
        result = []
        for role in roles:
            doc = await self._db.roles.find_one_and_update(
                {"academy_id": academy_id, "name": role.get("name", role.get("role"))},
                {"$setOnInsert": role},
                upsert=True,
                return_document=ReturnDocument.AFTER,
            )
            result.append(doc)
        return result

    async def ensure_feature_flags(self, flags: dict[str, Any]) -> dict[str, Any]:
        doc = await self._db.feature_flags.find_one_and_update(
            {"academy_id": flags["academy_id"]},
            {"$setOnInsert": flags},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return doc
