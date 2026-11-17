"""Platform billing application ports."""

from __future__ import annotations

from datetime import datetime
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

    async def claim_pending_checkout(
        self, subscription: TenantSubscription, *, expected_token: str | None, now: datetime
    ) -> bool:
        """Compare-and-set: write ``subscription``'s ``pending_checkout_*``
        fields only while the stored ``pending_checkout_token`` still equals
        ``expected_token``; inserts the row when the academy has none. Returns
        whether this caller won, so two concurrent checkouts open one session."""
        ...


class StripeCanceller(Protocol):
    """Cancels a platform subscription at Stripe. A subscription Stripe no
    longer has counts as cancelled, so a retry is always safe."""

    async def cancel_subscription(
        self, stripe_subscription_id: str, *, at_period_end: bool
    ) -> None: ...
