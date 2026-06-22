"""Process due scheduled enrollment resume actions."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import BaseModel

from backend.v2.contexts.enrollment.application.use_cases.billing_deferrals import (
    BillingDeferralRepository,
)
from backend.v2.contexts.enrollment.application.use_cases.scheduled_actions import (
    ScheduledEnrollmentActionRepository,
)
from backend.v2.contexts.enrollment.domain.errors import CapacityExceeded


class ResumeEnrollmentRunner(Protocol):
    async def execute(
        self,
        enrollment_id: str,
        *,
        actor_id: str | None = None,
        reason: str | None = None,
        close_billing_deferral: bool = True,
    ) -> None: ...


class EnrollmentSubscriptionLookup(Protocol):
    async def latest_for_enrollment(self, enrollment_id: str) -> Any | None: ...


class SubscriptionCollectionGateway(Protocol):
    async def resume_subscription_collection(self, stripe_subscription_id: str) -> None: ...


class ProcessScheduledResumeActionsResult(BaseModel):
    model_config = {"frozen": True}

    processed: int = 0
    succeeded: int = 0
    blocked_capacity: int = 0
    failed: int = 0


class ProcessScheduledResumeActions:
    def __init__(
        self,
        *,
        scheduled_actions: ScheduledEnrollmentActionRepository,
        resume_enrollment: ResumeEnrollmentRunner,
        subscriptions: EnrollmentSubscriptionLookup,
        stripe: SubscriptionCollectionGateway,
        billing_deferrals: BillingDeferralRepository | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._scheduled_actions = scheduled_actions
        self._resume_enrollment = resume_enrollment
        self._billing_deferrals = billing_deferrals
        self._subscriptions = subscriptions
        self._stripe = stripe
        self._now = clock

    async def execute(
        self,
        *,
        now: datetime | None = None,
        limit: int = 50,
    ) -> ProcessScheduledResumeActionsResult:
        attempted_at = now or self._now()
        actions = await self._scheduled_actions.list_due(now=attempted_at, limit=limit)
        succeeded = 0
        blocked_capacity = 0
        failed = 0

        for action in actions:
            try:
                await self._resume_enrollment.execute(
                    action.enrollment_id,
                    actor_id="system",
                    reason="scheduled resume from approved pause",
                    close_billing_deferral=False,
                )
            except CapacityExceeded:
                await self._scheduled_actions.mark_blocked_capacity(
                    action.action_id,
                    attempted_at=attempted_at,
                )
                blocked_capacity += 1
                continue

            try:
                subscription = await self._subscriptions.latest_for_enrollment(action.enrollment_id)
                stripe_subscription_id = getattr(subscription, "stripe_subscription_id", None)
                if stripe_subscription_id:
                    await self._stripe.resume_subscription_collection(str(stripe_subscription_id))
                if self._billing_deferrals is not None:
                    await self._billing_deferrals.close_active_for_enrollment(
                        action.enrollment_id,
                        closed_at=attempted_at,
                        closed_by="system",
                        reason="resume_succeeded",
                    )
                await self._scheduled_actions.mark_succeeded(
                    action.action_id,
                    attempted_at=attempted_at,
                )
                succeeded += 1
            except Exception as exc:
                await self._scheduled_actions.mark_failed(
                    action.action_id,
                    attempted_at=attempted_at,
                    error=str(exc),
                )
                failed += 1

        return ProcessScheduledResumeActionsResult(
            processed=len(actions),
            succeeded=succeeded,
            blocked_capacity=blocked_capacity,
            failed=failed,
        )
