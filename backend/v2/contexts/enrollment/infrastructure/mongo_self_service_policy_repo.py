"""Tenant-scoped ParentSelfServicePolicy storage."""

from __future__ import annotations

from typing import Any

from backend.v2.contexts.enrollment.domain.self_service import ParentSelfServicePolicy
from backend.v2.shared.tenancy import TenantScopedRepository, current_academy_id


class MongoSelfServicePolicyRepository(TenantScopedRepository):
    collection_name = "parent_self_service_policies"

    async def get_or_default(self) -> ParentSelfServicePolicy:
        """Return this academy's self-service policy, or defaults if none exist."""
        doc = await self._find_one()
        academy_id = current_academy_id()
        if not doc:
            return ParentSelfServicePolicy.default(academy_id)
        doc = dict(doc)
        doc.pop("_id", None)
        doc.setdefault("academy_id", academy_id)
        return ParentSelfServicePolicy.model_validate(doc)

    async def save(self, policy: ParentSelfServicePolicy) -> None:
        payload = policy.model_dump(mode="python")
        payload.pop("academy_id", None)
        await self._update_one(
            {},
            {"$set": payload},
            upsert=True,
        )

    async def update_fields(self, fields: dict[str, Any]) -> None:
        """``$set`` only ``fields``, so two panels saving different fields of
        this one document never overwrite each other (money audit X5).
        ``academy_id`` is never accepted from the caller."""
        payload = {key: value for key, value in fields.items() if key != "academy_id"}
        if not payload:
            return
        await self._update_one({}, {"$set": payload}, upsert=True)
