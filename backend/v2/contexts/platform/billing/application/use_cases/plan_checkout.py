"""Growth tier self-serve: the academy owner's plan overview, Stripe Billing
checkout, and the webhook sync that keeps ``TenantSubscription`` current
(AI strategy Phase 2, slice A2).

The Stripe calls and the Stripe-volume read belong to the ``billing`` context;
they arrive here as the small protocols below so this context never imports
that one (structural ``test_no_cross_context_imports``).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from pydantic import BaseModel, Field

from backend.v2.contexts.platform.billing.application.ports import (
    PlatformPlanRepository,
    TenantSubscriptionRepository,
)
from backend.v2.contexts.platform.billing.application.use_cases.manage_platform_billing import (
    ENTITLED_BILLING_STATUSES,
    AuditRecorder,
    _emit_audit,
)
from backend.v2.contexts.platform.billing.domain.models import (
    BillingStatus,
    PlatformPlan,
    TenantSubscription,
)
from backend.v2.shared.http.errors import DomainError
from backend.v2.shared.ids import new_ulid

log = logging.getLogger(__name__)

GROWTH_PLAN_CODE = "growth"
PLATFORM_PLAN_METADATA_SOURCE = "platform_plan"
PLATFORM_PLAN_EVENT_TYPES = frozenset(
    {
        "checkout.session.completed",
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
    }
)
#: The webhook has no signed-in user; the audit row still needs an actor.
WEBHOOK_ACTOR = "stripe_webhook"
STRIPE_VOLUME_WINDOW = timedelta(days=90)

#: Stripe subscription status -> ``TenantSubscription.billing_status``.
_STRIPE_STATUS: dict[str, BillingStatus] = {
    "trialing": "trialing",
    "active": "active",
    "past_due": "past_due",
    "unpaid": "unpaid",
    "incomplete": "incomplete",
    "incomplete_expired": "cancelled",
    "canceled": "cancelled",
    "paused": "unpaid",
}

#: ``async (since) -> cents``: the academy's succeeded Stripe payments.
StripeVolumeReader = Callable[[datetime], Awaitable[int]]


class PlanCheckoutGateway(Protocol):
    async def create_platform_customer(
        self, *, name: str, email: str | None, metadata: dict[str, str]
    ) -> str: ...

    async def create_platform_plan_checkout_session(
        self,
        *,
        customer_id: str,
        price_id: str,
        success_url: str,
        cancel_url: str,
        metadata: dict[str, str],
    ) -> tuple[str, str]: ...


class GrowthPlanUnavailable(DomainError):
    code = "PlatformBilling.GrowthPlanUnavailable"
    status_code = 409


class AlreadyOnGrowth(DomainError):
    code = "PlatformBilling.AlreadyOnGrowth"
    status_code = 409


@dataclass(frozen=True)
class PlanOverview:
    subscription: TenantSubscription | None
    plan: PlatformPlan | None
    growth: PlatformPlan | None
    checkout_available: bool


class StartGrowthCheckoutCommand(BaseModel):
    academy_id: str = Field(min_length=1)
    academy_name: str = Field(min_length=1)
    actor_user_id: str = Field(min_length=1)
    actor_email: str | None = None
    success_url: str = Field(min_length=1)
    cancel_url: str = Field(min_length=1)
    request_id: str | None = None
    ip_address: str | None = None


async def _growth_plan(plans: PlatformPlanRepository) -> PlatformPlan | None:
    return next((p for p in await plans.list() if p.code == GROWTH_PLAN_CODE), None)


def _checkout_available(growth: PlatformPlan | None) -> bool:
    return growth is not None and growth.is_active and bool(growth.stripe_price_id)


class GetPlanOverview:
    def __init__(
        self, *, plans: PlatformPlanRepository, subscriptions: TenantSubscriptionRepository
    ) -> None:
        self._plans = plans
        self._subscriptions = subscriptions

    async def execute(self, academy_id: str) -> PlanOverview:
        subscription = await self._subscriptions.get_for_academy(academy_id)
        plan = await self._plans.get(subscription.plan_id) if subscription else None
        growth = await _growth_plan(self._plans)
        return PlanOverview(
            subscription=subscription,
            plan=plan,
            growth=growth,
            checkout_available=_checkout_available(growth),
        )


class StartGrowthCheckout:
    """Create the Stripe Billing Checkout for the Growth plan and record the
    ``tenant.plan_upgrade_started`` audit event with the academy's 90-day
    Stripe volume."""

    def __init__(
        self,
        *,
        plans: PlatformPlanRepository,
        subscriptions: TenantSubscriptionRepository,
        stripe: PlanCheckoutGateway,
        stripe_volume: StripeVolumeReader,
        audit_recorder: AuditRecorder | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._plans = plans
        self._subscriptions = subscriptions
        self._stripe = stripe
        self._stripe_volume = stripe_volume
        self._audit_recorder = audit_recorder
        self._clock = clock or (lambda: datetime.now(UTC))

    async def execute(self, command: StartGrowthCheckoutCommand) -> str:
        growth = await _growth_plan(self._plans)
        if not _checkout_available(growth) or growth is None or growth.stripe_price_id is None:
            raise GrowthPlanUnavailable(
                "The Growth plan is not available for self-serve checkout yet."
            )
        existing = await self._subscriptions.get_for_academy(command.academy_id)
        if existing is not None and existing.plan_id == growth.plan_id:
            if existing.billing_status in ENTITLED_BILLING_STATUSES:
                raise AlreadyOnGrowth("This academy is already on the Growth plan.")
            # A second Checkout would open a second Stripe subscription on the
            # same customer; the dunning one must be settled or cancelled first.
            if existing.stripe_subscription_id and existing.billing_status in (
                "past_due",
                "unpaid",
            ):
                raise AlreadyOnGrowth(
                    "This academy's Growth subscription has an unpaid invoice; "
                    "settle or cancel it before starting a new checkout."
                )

        now = self._clock()
        customer_id = existing.stripe_customer_id if existing else None
        if not customer_id:
            customer_id = await self._stripe.create_platform_customer(
                name=command.academy_name,
                email=command.actor_email,
                metadata={"academy_id": command.academy_id},
            )
        subscription = (
            existing.model_copy(update={"stripe_customer_id": customer_id, "updated_at": now})
            if existing
            else TenantSubscription(
                subscription_id=f"platform_sub_{new_ulid()}",
                academy_id=command.academy_id,
                plan_id=growth.plan_id,
                billing_status="incomplete",
                stripe_customer_id=customer_id,
                created_at=now,
                updated_at=now,
            )
        )
        await self._subscriptions.save(subscription)

        metadata = {
            "source": PLATFORM_PLAN_METADATA_SOURCE,
            "academy_id": command.academy_id,
            "plan_id": growth.plan_id,
        }
        _, url = await self._stripe.create_platform_plan_checkout_session(
            customer_id=customer_id,
            price_id=growth.stripe_price_id,
            success_url=command.success_url,
            cancel_url=command.cancel_url,
            metadata=metadata,
        )
        from_plan = await self._plans.get(existing.plan_id) if existing else None
        await _emit_audit(
            audit_recorder=self._audit_recorder,
            actor_user_id=command.actor_user_id,
            actor_membership_id=None,
            platform_actor_role=None,
            academy_id=command.academy_id,
            action="tenant.plan_upgrade_started",
            entity_type="tenant_subscription",
            entity_id=subscription.subscription_id,
            before_snapshot=existing.model_dump(mode="json") if existing else None,
            after_snapshot={
                "from_plan_code": from_plan.code if from_plan else "none",
                "to_plan_code": growth.code,
                "stripe_volume_90d_cents": await self._stripe_volume(now - STRIPE_VOLUME_WINDOW),
            },
            request_id=command.request_id,
            ip_address=command.ip_address,
        )
        return url


class SyncTenantSubscriptionFromStripe:
    """Project a ``source == "platform_plan"`` Stripe event onto the academy's
    ``TenantSubscription``. Idempotent: the row is a function of the Stripe
    object, so a replay converges."""

    def __init__(
        self,
        *,
        plans: PlatformPlanRepository,
        subscriptions: TenantSubscriptionRepository,
        stripe_volume: StripeVolumeReader | None = None,
        audit_recorder: AuditRecorder | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._plans = plans
        self._subscriptions = subscriptions
        self._stripe_volume = stripe_volume
        self._audit_recorder = audit_recorder
        self._clock = clock or (lambda: datetime.now(UTC))

    async def execute(self, event_type: str, event: dict[str, Any]) -> None:
        obj = event.get("data", {}).get("object", {})
        metadata = obj.get("metadata") or {}
        academy_id = str(metadata.get("academy_id") or "")
        plan_id = str(metadata.get("plan_id") or "")
        if not academy_id or not plan_id or event_type not in PLATFORM_PLAN_EVENT_TYPES:
            log.warning("platform_plan_sync_ignored type=%s obj=%s", event_type, obj.get("id"))
            return
        now = self._clock()
        existing = await self._subscriptions.get_for_academy(academy_id)
        updates: dict[str, Any] = {
            "plan_id": plan_id,
            "stripe_customer_id": _text(obj.get("customer"))
            or (existing.stripe_customer_id if existing else None),
            "updated_at": now,
        }
        if event_type == "checkout.session.completed":
            # The subscription event carries the status and period; the
            # session only tells us which Stripe subscription this now is.
            updates["stripe_subscription_id"] = _text(obj.get("subscription"))
        else:
            status = _STRIPE_STATUS.get(str(obj.get("status") or ""), "incomplete")
            if event_type == "customer.subscription.deleted":
                status = "cancelled"
            if (
                existing is not None
                and existing.stripe_subscription_id
                and existing.stripe_subscription_id != _text(obj.get("id"))
                and existing.billing_status in ENTITLED_BILLING_STATUSES
                and status not in ENTITLED_BILLING_STATUSES
            ):
                # A late event for an older subscription (cancelled, then
                # re-subscribed) must not take the live one off entitlement.
                log.warning(
                    "platform_plan_sync_stale_subscription academy=%s event_sub=%s current=%s",
                    academy_id,
                    obj.get("id"),
                    existing.stripe_subscription_id,
                )
                return
            cancel_at_period_end = bool(obj.get("cancel_at_period_end"))
            updates.update(
                stripe_subscription_id=_text(obj.get("id")),
                billing_status=status,
                current_period_start=_period(obj, "current_period_start"),
                current_period_end=_period(obj, "current_period_end"),
                cancel_at_period_end=cancel_at_period_end,
                cancellation_status=(
                    "cancelled"
                    if status == "cancelled"
                    else "scheduled"
                    if cancel_at_period_end
                    else "none"
                ),
                cancelled_at=_stamp(obj.get("canceled_at")) if status == "cancelled" else None,
                trial_status="converted"
                if existing and existing.trial_status == "active" and status == "active"
                else (existing.trial_status if existing else "none"),
            )
        subscription = (
            existing.model_copy(update=updates)
            if existing
            else TenantSubscription(
                **{
                    "subscription_id": f"platform_sub_{new_ulid()}",
                    "academy_id": academy_id,
                    "billing_status": "incomplete",
                    "created_at": now,
                    **updates,
                }
            )
        )
        await self._subscriptions.save(subscription)
        became_active = subscription.billing_status == "active" and (
            existing is None or existing.billing_status != "active"
        )
        if not became_active:
            return
        plan = await self._plans.get(plan_id)
        from_plan = (
            await self._plans.get(existing.plan_id)
            if existing and existing.plan_id != plan_id
            else None
        )
        await _emit_audit(
            audit_recorder=self._audit_recorder,
            actor_user_id=WEBHOOK_ACTOR,
            actor_membership_id=None,
            platform_actor_role=None,
            academy_id=academy_id,
            action="tenant.plan_activated",
            entity_type="tenant_subscription",
            entity_id=subscription.subscription_id,
            before_snapshot=existing.model_dump(mode="json") if existing else None,
            after_snapshot={
                "from_plan_code": from_plan.code if from_plan else "none",
                "to_plan_code": plan.code if plan else plan_id,
                "stripe_subscription_id": subscription.stripe_subscription_id,
                "stripe_volume_90d_cents": (
                    await self._stripe_volume(now - STRIPE_VOLUME_WINDOW)
                    if self._stripe_volume
                    else None
                ),
            },
            request_id=str(event.get("id") or "") or None,
            ip_address=None,
        )


def _text(value: Any) -> str | None:
    # Stripe expands some ids to objects; both shapes carry the id.
    if isinstance(value, dict):
        value = value.get("id")
    return str(value) if value else None


def _period(obj: dict[str, Any], key: str) -> datetime | None:
    # API versions from basil on carry the period on the subscription items.
    value = obj.get(key)
    if value is None:
        items = (obj.get("items") or {}).get("data") or []
        value = items[0].get(key) if items else None
    return _stamp(value)


def _stamp(value: Any) -> datetime | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return datetime.fromtimestamp(value, tz=UTC)
