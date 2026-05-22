"""Platform billing application ports."""

from __future__ import annotations

from typing import Protocol

from backend.v2.contexts.platform.billing.domain.models import (
    PlatformPlan,
    TenantSubscription,
)


class PlatformPlanRepository(Protocol):
    async def get(self, plan_id: str) -> PlatformPlan | None: ...
    async def list(self) -> list[PlatformPlan]: ...
    async def save(self, plan: PlatformPlan) -> None: ...


class TenantSubscriptionRepository(Protocol):
    async def get_for_academy(self, academy_id: str) -> TenantSubscription | None: ...
    async def save(self, subscription: TenantSubscription) -> None: ...
