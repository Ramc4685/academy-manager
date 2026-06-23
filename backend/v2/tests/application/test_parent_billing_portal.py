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
    GetCheckoutStatus,
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
        self.by_id: dict[str, Subscription] = {}
        self.by_checkout: dict[str, Subscription] = {}
        self.latest: Subscription | None = None

    async def save(self, subscription: Subscription) -> None:
        self.saved.append(subscription)
        self.by_id[subscription.subscription_id] = subscription
        if subscription.stripe_checkout_session_id:
            self.by_checkout[subscription.stripe_checkout_session_id] = subscription
        if subscription.enrollment_id:
            self.latest = subscription

    async def get(self, subscription_id: str) -> Subscription | None:
        return self.by_id.get(subscription_id)

    async def get_by_stripe_sub(self, stripe_sub: str) -> Subscription | None:
        return None

    async def get_by_checkout_session(self, checkout_session_id: str) -> Subscription | None:
        return self.by_checkout.get(checkout_session_id)

    async def latest_for_enrollment(self, enrollment_id: str) -> Subscription | None:
        if self.latest and self.latest.enrollment_id == enrollment_id:
            return self.latest
        return None


class _CheckoutGateway:
    def __init__(
        self,
        *,
        error: Exception | None = None,
        retrieved: dict[str, object] | None = None,
    ) -> None:
        self._error = error
        self.created: list[dict[str, object]] = []
        self.setup_created: list[dict[str, object]] = []
        self.retrieved = retrieved

    async def create_subscription_checkout_session(self, **kwargs: object) -> tuple[str, str, str]:
        if self._error is not None:
            raise self._error
        self.created.append(kwargs)
        # Stripe leaves `subscription` null until Checkout completes.
        return "cs_test_1", "https://checkout.stripe.com/c/test", ""

    async def create_autopay_setup_checkout_session(self, **kwargs: object) -> tuple[str, str]:
        if self._error is not None:
            raise self._error
        self.setup_created.append(kwargs)
        return "cs_setup_1", "https://checkout.stripe.com/c/setup"

    async def retrieve_checkout_session(self, checkout_session_id: str) -> dict[str, object]:
        if self.retrieved is not None:
            return dict(self.retrieved)
        return {
            "id": checkout_session_id,
            "object": "checkout.session",
            "status": "open",
            "url": "https://checkout.stripe.com/c/existing",
        }


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
async def test_start_autopay_persists_incomplete_setup_until_checkout_completion() -> None:
    repo = _SubscriptionRepo()
    gateway = _CheckoutGateway()
    uc = StartSubscriptionCheckout(
        subscriptions=repo,
        stripe=gateway,
        academy_id="acad",
        clock=lambda: datetime(2026, 6, 11, tzinfo=UTC),
    )
    result = await uc.execute(_checkout_command())
    assert result.redirect_url == "https://checkout.stripe.com/c/setup"
    assert len(repo.saved) == 1
    saved = repo.saved[0]
    assert saved.status == "incomplete"
    assert saved.enrollment_id == "enr-1"
    assert saved.stripe_checkout_session_id == "cs_setup_1"
    assert saved.stripe_subscription_id == ""
    assert gateway.created == []
    assert (
        gateway.setup_created[0]["success_url"]
        == "https://app.example.com/parent/payments?autopay=success&checkout_session_id={CHECKOUT_SESSION_ID}"
    )


@pytest.mark.asyncio
async def test_start_autopay_setup_uses_setup_checkout_not_subscription_checkout() -> None:
    repo = _SubscriptionRepo()
    gateway = _CheckoutGateway()
    uc = StartSubscriptionCheckout(
        subscriptions=repo,
        stripe=gateway,
        academy_id="acad",
        clock=lambda: datetime(2026, 6, 11, tzinfo=UTC),
    )

    result = await uc.execute(_checkout_command())

    assert result.checkout_session_id == "cs_setup_1"
    assert result.redirect_url == "https://checkout.stripe.com/c/setup"
    assert gateway.created == []
    assert len(gateway.setup_created) == 1
    assert gateway.setup_created[0]["metadata"] == {
        "academy_id": "acad",
        "app_subscription_id": result.subscription_id,
        "subscription_id": result.subscription_id,
        "parent_id": "p1",
        "enrollment_id": "enr-1",
        "session_id": "s1",
        "source": "autopay_setup",
    }
    assert repo.saved[0].stripe_subscription_id == ""


@pytest.mark.asyncio
async def test_start_autopay_reuses_existing_open_pending_checkout() -> None:
    repo = _SubscriptionRepo()
    now = datetime(2026, 6, 11, tzinfo=UTC)
    await repo.save(
        Subscription(
            subscription_id="sub-existing",
            academy_id="acad",
            parent_id="p1",
            enrollment_id="enr-1",
            session_id="s1",
            stripe_subscription_id="",
            stripe_checkout_session_id="cs_existing",
            status="incomplete",
            created_at=now,
            updated_at=now,
        )
    )
    gateway = _CheckoutGateway()
    uc = StartSubscriptionCheckout(
        subscriptions=repo,
        stripe=gateway,
        academy_id="acad",
        clock=lambda: now,
    )

    result = await uc.execute(_checkout_command())

    assert result.subscription_id == "sub-existing"
    assert result.checkout_session_id == "cs_existing"
    assert result.redirect_url == "https://checkout.stripe.com/c/existing"
    assert gateway.created == []


class _NoPaymentRepo:
    async def get_by_checkout_session(self, checkout_session_id: str):
        return None


class _CustomerRepo:
    def __init__(self) -> None:
        self.saved: list[dict[str, str]] = []

    async def set_stripe_customer_id(self, *, parent_id: str, stripe_customer_id: str) -> None:
        self.saved.append({"parent_id": parent_id, "stripe_customer_id": stripe_customer_id})


class _EnrollmentAutopay:
    def __init__(self) -> None:
        self.synced: list[dict[str, str | None]] = []

    async def set_autopay_state(
        self,
        *,
        enrollment_id: str,
        subscription_status: str,
        stripe_subscription_id: str | None,
    ) -> None:
        self.synced.append(
            {
                "enrollment_id": enrollment_id,
                "subscription_status": subscription_status,
                "stripe_subscription_id": stripe_subscription_id,
            }
        )


@pytest.mark.asyncio
async def test_checkout_status_reconciles_completed_subscription_checkout() -> None:
    now = datetime(2026, 6, 11, tzinfo=UTC)
    repo = _SubscriptionRepo()
    await repo.save(
        Subscription(
            subscription_id="sub-local",
            academy_id="acad",
            parent_id="p1",
            enrollment_id="enr-1",
            session_id="s1",
            stripe_subscription_id="",
            stripe_checkout_session_id="cs_complete",
            status="incomplete",
            created_at=now,
            updated_at=now,
        )
    )
    customers = _CustomerRepo()
    enrollment_autopay = _EnrollmentAutopay()
    gateway = _CheckoutGateway(
        retrieved={
            "id": "cs_complete",
            "object": "checkout.session",
            "status": "complete",
            "payment_status": "paid",
            "customer": "cus_parent",
            "subscription": "sub_live_123",
            "metadata": {
                "parent_id": "p1",
                "app_subscription_id": "sub-local",
                "subscription_id": "sub-local",
                "enrollment_id": "enr-1",
            },
        }
    )
    uc = GetCheckoutStatus(
        payments=_NoPaymentRepo(),
        subscriptions=repo,
        stripe=gateway,
        parent_customers=customers,
        enrollment_autopay=enrollment_autopay,
        clock=lambda: now,
    )

    result = await uc.execute("cs_complete", parent_id="p1")

    assert result.status == "active"
    assert result.payment_id is None
    assert repo.by_id["sub-local"].stripe_subscription_id == "sub_live_123"
    assert repo.by_id["sub-local"].status == "active"
    assert customers.saved == [{"parent_id": "p1", "stripe_customer_id": "cus_parent"}]
    assert enrollment_autopay.synced == [
        {
            "enrollment_id": "enr-1",
            "subscription_status": "active",
            "stripe_subscription_id": "sub_live_123",
        }
    ]


@pytest.mark.asyncio
async def test_checkout_status_reconciles_completed_setup_checkout_without_subscription() -> None:
    now = datetime(2026, 6, 11, tzinfo=UTC)
    repo = _SubscriptionRepo()
    await repo.save(
        Subscription(
            subscription_id="setup-local",
            academy_id="acad",
            parent_id="p1",
            enrollment_id="enr-1",
            session_id="s1",
            stripe_subscription_id="",
            stripe_checkout_session_id="cs_setup_complete",
            status="incomplete",
            created_at=now,
            updated_at=now,
        )
    )
    customers = _CustomerRepo()
    enrollment_autopay = _EnrollmentAutopay()
    gateway = _CheckoutGateway(
        retrieved={
            "id": "cs_setup_complete",
            "object": "checkout.session",
            "mode": "setup",
            "status": "complete",
            "customer": "cus_parent",
            "setup_intent": "seti_saved_card",
            "metadata": {
                "parent_id": "p1",
                "app_subscription_id": "setup-local",
                "enrollment_id": "enr-1",
                "source": "autopay_setup",
            },
        }
    )
    uc = GetCheckoutStatus(
        payments=_NoPaymentRepo(),
        subscriptions=repo,
        stripe=gateway,
        parent_customers=customers,
        enrollment_autopay=enrollment_autopay,
        clock=lambda: now,
    )

    result = await uc.execute("cs_setup_complete", parent_id="p1")

    assert result.status == "active"
    assert result.payment_id is None
    assert repo.by_id["setup-local"].stripe_subscription_id == ""
    assert repo.by_id["setup-local"].status == "active"
    assert customers.saved == [{"parent_id": "p1", "stripe_customer_id": "cus_parent"}]
    assert enrollment_autopay.synced == [
        {
            "enrollment_id": "enr-1",
            "subscription_status": "active",
            "stripe_subscription_id": None,
        }
    ]
