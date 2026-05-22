"""Mongo-backed storage adapter for SaaS tenant bootstrap."""

from __future__ import annotations

from typing import Any

from pymongo import ReturnDocument


class MongoTenantBootstrapStore:
    """Persistence adapter for the clean v2 tenant bootstrap use case.

    Bootstrap runs before a normal tenant request context exists, so every
    write uses explicit `academy_id` fields instead of TenantScopedRepository.
    """

    def __init__(self, db: Any) -> None:
        self._academies = db["academies"]
        self._users = db["users"]
        self._memberships = db["academy_memberships"]
        self._settings = db["academy_settings"]
        self._billing_policies = db["billing_policies"]
        self._waiver_templates = db["waiver_templates"]
        self._roles = db["academy_roles"]
        self._feature_flags = db["academy_feature_flags"]

    async def find_academy_by_slug(self, slug: str) -> dict[str, Any] | None:
        return await self._academies.find_one({"slug": slug})

    async def find_academy_by_domain(self, domain: str) -> dict[str, Any] | None:
        return await self._academies.find_one(
            {"$or": [{"primary_domain": domain}, {"custom_domain": domain}]}
        )

    async def create_academy(self, academy: dict[str, Any]) -> dict[str, Any]:
        doc = {
            **academy,
            # The current tenant resolver reads `custom_domain`; keep it in
            # sync with the initial primary domain until custom-domain flows
            # add a dedicated `academy_domains` collection.
            "custom_domain": academy["primary_domain"],
        }
        await self._academies.insert_one(doc)
        return doc

    async def ensure_owner_user(self, user: dict[str, Any]) -> dict[str, Any]:
        doc = await self._users.find_one_and_update(
            {"normalized_email": user["normalized_email"]},
            {
                "$setOnInsert": user,
                "$set": {
                    "display_name": user["display_name"],
                    "global_status": user["global_status"],
                    "updated_at": user["updated_at"],
                },
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        if doc is None:
            doc = await self._users.find_one({"normalized_email": user["normalized_email"]})
        return doc

    async def ensure_owner_membership(self, membership: dict[str, Any]) -> dict[str, Any]:
        doc = await self._memberships.find_one_and_update(
            {"academy_id": membership["academy_id"], "user_id": membership["user_id"]},
            {
                "$setOnInsert": membership,
                "$set": {
                    "roles": membership["roles"],
                    "status": membership["status"],
                    "updated_at": membership["updated_at"],
                },
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        if doc is None:
            doc = await self._memberships.find_one(
                {"academy_id": membership["academy_id"], "user_id": membership["user_id"]}
            )
        return doc

    async def ensure_academy_settings(self, settings: dict[str, Any]) -> dict[str, Any]:
        return await self._ensure_one(self._settings, "academy_id", settings)

    async def ensure_billing_policy(self, policy: dict[str, Any]) -> dict[str, Any]:
        return await self._ensure_one(self._billing_policies, "academy_id", policy)

    async def ensure_waiver_template(self, waiver: dict[str, Any]) -> dict[str, Any]:
        return await self._ensure_one(self._waiver_templates, "academy_id", waiver)

    async def ensure_default_roles(
        self, academy_id: str, roles: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        stored: list[dict[str, Any]] = []
        for role in roles:
            doc = await self._roles.find_one_and_update(
                {"academy_id": academy_id, "role": role["role"]},
                {"$setOnInsert": role},
                upsert=True,
                return_document=ReturnDocument.AFTER,
            )
            if doc is None:
                doc = await self._roles.find_one({"academy_id": academy_id, "role": role["role"]})
            stored.append(doc)
        return stored

    async def ensure_feature_flags(self, flags: dict[str, Any]) -> dict[str, Any]:
        return await self._ensure_one(self._feature_flags, "academy_id", flags)

    @staticmethod
    async def _ensure_one(collection: Any, key: str, doc: dict[str, Any]) -> dict[str, Any]:
        stored = await collection.find_one_and_update(
            {key: doc[key]},
            {"$setOnInsert": doc},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        if stored is None:
            stored = await collection.find_one({key: doc[key]})
        return stored
