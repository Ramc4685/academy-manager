"""Mongo repository for platform tenant lifecycle state."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError
from pymongo import ReturnDocument

from backend.v2.contexts.platform.domain.models import Tenant, TenantLimits

log = logging.getLogger(__name__)


class MongoTenantLifecycleRepository:
    """Persists Platform tenant state in the `academies` collection.

    The tenant identifier remains `academy_id` so tenant-scoped v2 contexts
    can continue using the same request-scoped key while platform owns status
    and plan lifecycle mutations.
    """

    def __init__(self, db: Any) -> None:
        self._collection = db["academies"]
        self._domains = db["academy_domains"]

    async def get_by_id(self, academy_id: str) -> Tenant | None:
        doc = await self._collection.find_one({"academy_id": academy_id})
        return self._to_tenant(doc) if doc else None

    async def list_tenants(self) -> list[Tenant]:
        """Return every academy doc that parses as a platform tenant.

        The `academies` collection predates the platform context, so some docs
        were written without the fields `Tenant` requires (notably a domain).
        Those are skipped with a warning rather than failing the whole list —
        one legacy row must not take the operator tenant list down.
        """
        tenants: list[Tenant] = []
        async for doc in self._collection.find({}):
            try:
                tenants.append(self._to_tenant(doc))
            except ValidationError:
                log.warning(
                    "skipping academy doc that is not a valid platform tenant: %s",
                    doc.get("academy_id"),
                )
        return tenants

    async def get_by_slug(self, slug: str) -> Tenant | None:
        doc = await self._collection.find_one({"slug": slug})
        return self._to_tenant(doc) if doc else None

    async def get_by_domain(self, domain: str) -> Tenant | None:
        doc = await self._collection.find_one(
            {"$or": [{"primary_domain": domain}, {"custom_domain": domain}]}
        )
        return self._to_tenant(doc) if doc else None

    async def create(self, tenant: Tenant) -> Tenant:
        now = datetime.now(UTC)
        await self._collection.insert_one(self._to_doc(tenant))
        if tenant.primary_domain:
            await self._domains.update_one(
                {"domain": tenant.primary_domain},
                {
                    "$set": {
                        "academy_id": tenant.academy_id,
                        "slug": tenant.slug,
                        "status": "verified",
                        "kind": "tenant_subdomain",
                        "created_at": now,
                    }
                },
                upsert=True,
            )
        return tenant

    async def save(self, tenant: Tenant) -> Tenant:
        doc = await self._collection.find_one_and_update(
            {"academy_id": tenant.academy_id},
            {"$set": self._to_doc(tenant)},
            return_document=ReturnDocument.AFTER,
        )
        return self._to_tenant(doc) if doc else tenant

    def _to_tenant(self, doc: dict[str, Any]) -> Tenant:
        now = datetime.now(UTC)
        return Tenant(
            academy_id=str(doc["academy_id"]),
            display_name=str(doc.get("display_name") or doc["academy_id"]),
            slug=str(doc.get("slug") or doc["academy_id"]),
            primary_domain=str(doc.get("primary_domain") or doc.get("custom_domain") or ""),
            status=str(doc.get("status") or "provisioning"),
            plan_code=str(doc.get("plan_code") or "starter"),
            limits=TenantLimits.model_validate(doc.get("limits") or {}),
            status_reason=doc.get("status_reason"),
            created_by=str(doc.get("created_by") or "system"),
            updated_by=str(doc.get("updated_by") or doc.get("created_by") or "system"),
            created_at=doc.get("created_at") or now,
            updated_at=doc.get("updated_at") or doc.get("created_at") or now,
            activated_at=doc.get("activated_at"),
            suspended_at=doc.get("suspended_at"),
            cancelled_at=doc.get("cancelled_at"),
            reactivated_at=doc.get("reactivated_at"),
        )

    @staticmethod
    def _to_doc(tenant: Tenant) -> dict[str, Any]:
        return tenant.model_dump()
