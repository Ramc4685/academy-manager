"""CreateCustomerPortalSession + StartSubscriptionCheckout failure paths.

Production regressions showed two distinct portal failures: the parent has
no stored Stripe customer id yet (expected, must surface the friendly
prerequisite message) and Stripe itself rejecting the call (expired key,
missing live portal configuration). Both must map to CheckoutCreationFailed
(502) rather than an unhandled 500.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.contexts.billing.application.use_cases.parent_billing import (
    CreateCustomerPortalSession,
    CreateCustomerPortalSessionCommand,
    StartSubscriptionCheckout,
    StartSubscriptionCheckoutCommand,
)
from backend.v2.contexts.billing.domain.errors import CheckoutCreationFailed
from backend.v2.contexts.billing.domain.models import Subscription


class _PortalGateway:
    """Gateway double mirroring RealStripeGateway.create_customer_portal_session."""

    def __init__(self, *, error: Exception | None = None) -> None:
        self._error = error
        self.calls: list[dict[str, object]] = []

    async def create_customer_portal_session(
        self, *, parent_id: str, return_url: str, stripe_customer_id: str | None
    ) -> str:
        self.calls.append(
            {
                "parent_id": parent_id,
                "return_url": return_url,
                "stripe_customer_id": stripe_customer_id,
            }
        )
        if not stripe_customer_id:
            raise ValueError(
                "Billing portal will be available after the first successful autopay setup."
            )
        if self._error is not None:
            raise self._error
        return "https://billing.stripe.com/p/session/test"


@pytest.mark.asyncio
async def test_portal_without_stripe_customer_maps_to_checkout_creation_failed() -> None:
    uc = CreateCustomerPortalSession(stripe=_PortalGateway())
    with pytest.raises(CheckoutCreationFailed) as exc_info:
        await uc.execute(
            CreateCustomerPortalSessionCommand(
                parent_id="p1",
                return_url="https://app.example.com/parent/payments",
                stripe_customer_id=None,
            )
        )
    assert "autopay setup" in str(exc_info.value)


@pytest.mark.asyncio
async def test_portal_stripe_error_maps_to_checkout_creation_failed() -> None:
    uc = CreateCustomerPortalSession(
        stripe=_PortalGateway(error=RuntimeError("No configuration provided")),
    )
    with pytest.raises(CheckoutCreationFailed):
        await uc.execute(
            CreateCustomerPortalSessionCommand(
                parent_id="p1",
                return_url="https://app.example.com/parent/payments",
                stripe_customer_id="cus_live_1",
            )
        )


@pytest.mark.asyncio
async def test_portal_succeeds_with_stored_customer() -> None:
    gateway = _PortalGateway()
    uc = CreateCustomerPortalSession(stripe=gateway)
    result = await uc.execute(
        CreateCustomerPortalSessionCommand(
            parent_id="p1",
            return_url="https://app.example.com/parent/payments",
            stripe_customer_id="cus_live_1",
        )
    )
    assert result.redirect_url == "https://billing.stripe.com/p/session/test"
    assert gateway.calls[0]["stripe_customer_id"] == "cus_live_1"


class _SubscriptionRepo:
    def __init__(self) -> None:
        self.saved: list[Subscription] = []

    async def save(self, subscription: Subscription) -> None:
        self.saved.append(subscription)

    async def get_by_stripe_sub(self, stripe_sub: str) -> Subscription | None:
        return None

    async def latest_for_enrollment(self, enrollment_id: str) -> Subscription | None:
        return None


class _CheckoutGateway:
    def __init__(self, *, error: Exception | None = None) -> None:
        self._error = error

    async def create_subscription_checkout_session(self, **_: object) -> tuple[str, str, str]:
        if self._error is not None:
            raise self._error
        # Stripe leaves `subscription` null until Checkout completes.
        return "cs_test_1", "https://checkout.stripe.com/c/test", ""


def _checkout_command() -> StartSubscriptionCheckoutCommand:
    return StartSubscriptionCheckoutCommand(
        parent_id="p1",
        enrollment_id="enr-1",
        session_id="s1",
        amount_cents=7000,
        success_url="https://app.example.com/parent/payments?autopay=success",
        cancel_url="https://app.example.com/parent/payments?autopay=cancelled",
    )


@pytest.mark.asyncio
async def test_start_autopay_stripe_rejection_maps_to_checkout_creation_failed() -> None:
    uc = StartSubscriptionCheckout(
        subscriptions=_SubscriptionRepo(),
        stripe=_CheckoutGateway(error=RuntimeError("invalid request")),
        academy_id="acad",
    )
    with pytest.raises(CheckoutCreationFailed):
        await uc.execute(_checkout_command())


@pytest.mark.asyncio
async def test_start_autopay_persists_incomplete_subscription_until_webhook() -> None:
    repo = _SubscriptionRepo()
    uc = StartSubscriptionCheckout(
        subscriptions=repo,
        stripe=_CheckoutGateway(),
        academy_id="acad",
        clock=lambda: datetime(2026, 6, 11, tzinfo=UTC),
    )
    result = await uc.execute(_checkout_command())
    assert result.redirect_url == "https://checkout.stripe.com/c/test"
    assert len(repo.saved) == 1
    saved = repo.saved[0]
    assert saved.status == "incomplete"
    assert saved.enrollment_id == "enr-1"
    # Stripe has not assigned a subscription id yet; the webhook backfills it.
    assert saved.stripe_subscription_id == ""
