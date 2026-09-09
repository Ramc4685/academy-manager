"""Tenant-scoped EnrollmentDeparturePolicy storage.

Structurally a copy of ``mongo_self_service_policy_repo.py`` — same pattern,
sibling model, separate collection (see ``domain/departure_policy.py``).
"""

from __future__ import annotations

from backend.v2.contexts.enrollment.domain.departure_policy import EnrollmentDeparturePolicy
from backend.v2.shared.tenancy import TenantScopedRepository, current_academy_id


class MongoDeparturePolicyRepository(TenantScopedRepository):
    collection_name = "enrollment_departure_policies"

    async def get_or_default(self) -> EnrollmentDeparturePolicy:
        doc = await self._find_one()
        academy_id = current_academy_id()
        if not doc:
            return EnrollmentDeparturePolicy.default(academy_id)
        doc = dict(doc)
        doc.pop("_id", None)
        doc.setdefault("academy_id", academy_id)
        return EnrollmentDeparturePolicy.model_validate(doc)

    async def save(self, policy: EnrollmentDeparturePolicy) -> None:
        payload = policy.model_dump(mode="python")
        payload.pop("academy_id", None)
        await self._update_one({}, {"$set": payload}, upsert=True)
