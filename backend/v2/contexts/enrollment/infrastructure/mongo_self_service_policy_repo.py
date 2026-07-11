"""Tenant-scoped ParentSelfServicePolicy storage."""

from __future__ import annotations

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
