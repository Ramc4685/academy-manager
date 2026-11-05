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
    _lapsed,
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
#: Stripe expires a Checkout Session 24h after creation.
PENDING_CHECKOUT_TTL = timedelta(hours=24)
#: A claim whose Stripe call never finished (process died) is abandoned after this.
PENDING_CLAIM_GRACE = timedelta(minutes=10)
#: Metadata key carrying ``TenantSubscription.pending_checkout_token``.
CHECKOUT_TOKEN_METADATA_KEY = "checkout_token"

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

    async def retrieve_checkout_session(self, checkout_session_id: str) -> dict[str, Any]: ...

    async def expire_checkout_session(self, checkout_session_id: str) -> None: ...


class PlanSyncGateway(Protocol):
    async def cancel_subscription(
        self, stripe_subscription_id: str, *, at_period_end: bool
    ) -> None: ...


class GrowthPlanUnavailable(DomainError):
    code = "PlatformBilling.GrowthPlanUnavailable"
    status_code = 409


class AlreadyOnGrowth(DomainError):
    code = "PlatformBilling.AlreadyOnGrowth"
    status_code = 409


class CheckoutInProgress(DomainError):
    code = "PlatformBilling.CheckoutInProgress"
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
        now = self._clock()
        if existing is not None and existing.plan_id == growth.plan_id:
            # A local trial (no Stripe subscription) or a lapsed one may buy.
            if (
                existing.billing_status in ENTITLED_BILLING_STATUSES
                and existing.stripe_subscription_id
                and not _lapsed(existing, now)
            ):
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

        if existing is not None:
            open_url = await self._continue_pending_checkout(existing, now)
            if open_url:
                return open_url

        # Claim before any Stripe call: the loser of a concurrent pair creates
        # nothing (one payable session per academy, repo billing rule).
        token = f"pco_{new_ulid()}"
        claim = {
            "pending_checkout_token": token,
            "pending_checkout_session_id": None,
            "pending_checkout_url": None,
            "pending_checkout_created_at": now,
            "updated_at": now,
        }
        subscription = (
            existing.model_copy(update=claim)
            if existing
            else TenantSubscription(
                subscription_id=f"platform_sub_{new_ulid()}",
                academy_id=command.academy_id,
                plan_id=growth.plan_id,
                billing_status="incomplete",
                created_at=now,
                **claim,
            )
        )
        if not await self._subscriptions.claim_pending_checkout(
            subscription,
            expected_token=existing.pending_checkout_token if existing else None,
            now=now,
        ):
            raise CheckoutInProgress(
                "A Growth checkout is already being opened for this academy; try again in a moment."
            )

        try:
            customer_id = existing.stripe_customer_id if existing else None
            if not customer_id:
                customer_id = await self._stripe.create_platform_customer(
                    name=command.academy_name,
                    email=command.actor_email,
                    metadata={"academy_id": command.academy_id},
                )
            metadata = {
                "source": PLATFORM_PLAN_METADATA_SOURCE,
                "academy_id": command.academy_id,
                "plan_id": growth.plan_id,
                CHECKOUT_TOKEN_METADATA_KEY: token,
            }
            session_id, url = await self._stripe.create_platform_plan_checkout_session(
                customer_id=customer_id,
                price_id=growth.stripe_price_id,
                success_url=command.success_url,
                cancel_url=command.cancel_url,
                metadata=metadata,
            )
        except Exception:
            # Release the claim so the next request is not held for the grace window.
            await self._subscriptions.save(
                subscription.model_copy(
                    update={"pending_checkout_token": None, "pending_checkout_created_at": None}
                )
            )
            raise
        subscription = subscription.model_copy(
            update={
                "stripe_customer_id": customer_id,
                "pending_checkout_session_id": session_id,
                "pending_checkout_url": url,
            }
        )
        await self._subscriptions.save(subscription)
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

    async def _continue_pending_checkout(
        self, existing: TenantSubscription, now: datetime
    ) -> str | None:
        """The url of the Checkout an earlier request opened while Stripe still
        has it open; ``None`` once it is gone (expired or never finished), so the
        caller opens a new one. A completed one whose webhook has not landed
        yet must not be followed by a second subscription: that raises."""
        session_id = existing.pending_checkout_session_id
        started = existing.pending_checkout_created_at
        if existing.pending_checkout_token is None or started is None:
            return None
        age = now - started
        if session_id is None:
            if age < PENDING_CLAIM_GRACE:
                raise CheckoutInProgress(
                    "A Growth checkout is already being opened for this academy; "
                    "try again in a moment."
                )
            return None
        if age < PENDING_CHECKOUT_TTL:
            session = await self._stripe.retrieve_checkout_session(session_id)
            status = session.get("status")
            if status == "open" and existing.pending_checkout_url:
                return existing.pending_checkout_url
            if status == "complete":
                raise CheckoutInProgress(
                    "This academy's Growth checkout was completed and is being confirmed; "
                    "refresh in a moment."
                )
        try:
            await self._stripe.expire_checkout_session(session_id)
        except Exception as exc:
            # Already complete or expired on Stripe, or unreachable: it cannot
            # be paid twice either way once the new session replaces it here.
            log.info("platform_plan_checkout_expire_skipped session=%s err=%s", session_id, exc)
        return None


class SyncTenantSubscriptionFromStripe:
    """Project a ``source == "platform_plan"`` Stripe event onto the academy's
    ``TenantSubscription``. Idempotent: the row is a function of the Stripe
    object, so a replay converges."""

    def __init__(
        self,
        *,
        plans: PlatformPlanRepository,
        subscriptions: TenantSubscriptionRepository,
        stripe: PlanSyncGateway | None = None,
        stripe_volume: StripeVolumeReader | None = None,
        audit_recorder: AuditRecorder | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._plans = plans
        self._subscriptions = subscriptions
        self._stripe = stripe
        self._stripe_volume = stripe_volume
        self._audit_recorder = audit_recorder
        self._clock = clock or (lambda: datetime.now(UTC))

    async def execute(self, event_type: str, event: dict[str, Any]) -> None:
        obj = event.get("data", {}).get("object", {})
        metadata = obj.get("metadata") or {}
        academy_id = str(metadata.get("academy_id") or "")
        if not academy_id or event_type not in PLATFORM_PLAN_EVENT_TYPES:
            log.warning("platform_plan_sync_ignored type=%s obj=%s", event_type, obj.get("id"))
            return
        now = self._clock()
        existing = await self._subscriptions.get_for_academy(academy_id)
        customer_id = _text(obj.get("customer"))
        if existing and existing.stripe_customer_id and customer_id != existing.stripe_customer_id:
            log.warning(
                "platform_plan_sync_customer_mismatch academy=%s event_customer=%s current=%s",
                academy_id,
                customer_id,
                existing.stripe_customer_id,
            )
            return
        is_checkout = event_type == "checkout.session.completed"
        event_sub_id = _text(obj.get("subscription") if is_checkout else obj.get("id"))
        from_pending = existing is not None and _from_pending_checkout(existing, obj, is_checkout)
        # Another subscription than the one on file.
        superseded_id = (
            existing.stripe_subscription_id
            if existing is not None
            and existing.stripe_subscription_id
            and existing.stripe_subscription_id != event_sub_id
            else None
        )
        if (
            existing is not None
            and superseded_id
            and not from_pending
            and not _supersedes(existing, _stamp(obj.get("created")))
        ):
            # Another subscription than the one on file: only a newer one after
            # the stored one was cancelled (re-subscribe) may replace it.
            log.warning(
                "platform_plan_sync_stale_subscription academy=%s event_sub=%s current=%s",
                academy_id,
                event_sub_id,
                existing.stripe_subscription_id,
            )
            return
        updates: dict[str, Any] = {
            "stripe_customer_id": customer_id
            or (existing.stripe_customer_id if existing else None),
            "updated_at": now,
        }
        if from_pending:
            updates.update(
                pending_checkout_token=None,
                pending_checkout_session_id=None,
                pending_checkout_url=None,
                pending_checkout_created_at=None,
            )
        if is_checkout:
            # The session only tells us which customer and Stripe subscription
            # this now is; plan and entitlement come from the subscription event.
            # The row itself is written by StartGrowthCheckout before Checkout.
            if existing is None or not (
                obj.get("payment_status") == "paid" or obj.get("status") == "complete"
            ):
                log.warning("platform_plan_sync_checkout_ignored session=%s", obj.get("id"))
                return
            updates["stripe_subscription_id"] = event_sub_id
        else:
            price_id = _price_id(obj)
            plan = next(
                (p for p in await self._plans.list() if price_id and p.stripe_price_id == price_id),
                None,
            )
            if plan is None:
                log.warning(
                    "platform_plan_sync_unknown_price academy=%s sub=%s price=%s",
                    academy_id,
                    event_sub_id,
                    price_id,
                )
                return
            status = _STRIPE_STATUS.get(str(obj.get("status") or ""), "incomplete")
            if event_type == "customer.subscription.deleted":
                status = "cancelled"
            if superseded_id and from_pending and status not in ENTITLED_BILLING_STATUSES:
                # An upgrade that did not go through keeps the live subscription.
                log.warning(
                    "platform_plan_sync_successor_not_entitled academy=%s sub=%s status=%s",
                    academy_id,
                    event_sub_id,
                    status,
                )
                return
            cancel_at_period_end = bool(obj.get("cancel_at_period_end"))
            updates.update(
                plan_id=plan.plan_id,
                stripe_subscription_id=event_sub_id,
                stripe_subscription_created_at=_stamp(obj.get("created")),
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
        if superseded_id and from_pending:
            # The checkout the academy opened produced this subscription: it
            # succeeds the live one, which Stripe must stop billing (upgrade).
            await self._cancel_superseded(superseded_id, academy_id)
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
            existing is None
            or existing.billing_status != "active"
            or existing.plan_id != subscription.plan_id
        )
        if not became_active:
            return
        plan_id = subscription.plan_id
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

    async def _cancel_superseded(self, stripe_subscription_id: str, academy_id: str) -> None:
        if self._stripe is None:
            log.warning(
                "platform_plan_sync_superseded_not_cancelled academy=%s sub=%s (no gateway)",
                academy_id,
                stripe_subscription_id,
            )
            return
        try:
            await self._stripe.cancel_subscription(stripe_subscription_id, at_period_end=False)
        except Exception as exc:
            # Best effort: the row already moved on; the old subscription's own
            # events are ignored as stale, so this only needs a follow-up in Stripe.
            log.warning(
                "platform_plan_sync_superseded_cancel_failed academy=%s sub=%s err=%s",
                academy_id,
                stripe_subscription_id,
                exc,
            )


def _text(value: Any) -> str | None:
    # Stripe expands some ids to objects; both shapes carry the id.
    if isinstance(value, dict):
        value = value.get("id")
    return str(value) if value else None


def _price_id(obj: dict[str, Any]) -> str | None:
    items = (obj.get("items") or {}).get("data") or []
    return _text(items[0].get("price")) if items else None


def _from_pending_checkout(
    existing: TenantSubscription, obj: dict[str, Any], is_checkout: bool
) -> bool:
    """The event belongs to the Checkout the academy opened through
    ``StartGrowthCheckout``: the session id on a checkout event, the token the
    session put on the subscription's metadata otherwise. Either order of
    arrival works."""
    if is_checkout:
        return bool(existing.pending_checkout_session_id) and (
            obj.get("id") == existing.pending_checkout_session_id
        )
    token = (obj.get("metadata") or {}).get(CHECKOUT_TOKEN_METADATA_KEY)
    return bool(existing.pending_checkout_token) and token == existing.pending_checkout_token


def _supersedes(existing: TenantSubscription, event_created: datetime | None) -> bool:
    """A different subscription may replace the stored one only once that one
    is cancelled and the event's object is newer than it."""
    if existing.billing_status != "cancelled" or event_created is None:
        return False
    stored = existing.stripe_subscription_created_at
    return stored is None or event_created > stored


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
