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
from pymongo.errors import OperationFailure

from backend.v2.composition.parent import _MongoTransactionRunner
from backend.v2.contexts.billing.application.use_cases.parent_billing import (
    AutopayConsentCaptureContext,
    CompleteAutopaySetup,
    CreateCustomerPortalSession,
    CreateCustomerPortalSessionCommand,
    GetCheckoutStatus,
    StartSubscriptionCheckout,
    StartSubscriptionCheckoutCommand,
)
from backend.v2.contexts.billing.domain.connected_account import ConnectedAccount
from backend.v2.contexts.billing.domain.errors import CheckoutCreationFailed, PaymentNotFound
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
        default_error: Exception | None = None,
        retrieved: dict[str, object] | None = None,
    ) -> None:
        self._error = error
        self._default_error = default_error
        self.created: list[dict[str, object]] = []
        self.setup_created: list[dict[str, object]] = []
        self.setup_intents: dict[str, dict[str, object]] = {}
        self.payment_intents: dict[str, dict[str, object]] = {}
        self.payment_methods: dict[str, dict[str, object]] = {}
        self.default_payment_methods: list[dict[str, object]] = []
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
        metadata = dict(kwargs.get("metadata") or {})
        self.setup_intents["seti_saved_card"] = {
            "id": "seti_saved_card",
            "object": "setup_intent",
            "customer": "cus_parent",
            "payment_method": "pm_saved_card",
            "mandate": "mandate_saved_card",
            "metadata": metadata,
        }
        self.payment_methods["pm_saved_card"] = {
            "id": "pm_saved_card",
            "object": "payment_method",
            "type": "card",
        }
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

    async def retrieve_setup_intent(self, setup_intent_id: str) -> dict[str, object]:
        return dict(self.setup_intents[setup_intent_id])

    async def retrieve_payment_intent(self, payment_intent_id: str) -> dict[str, object]:
        return dict(self.payment_intents[payment_intent_id])

    async def retrieve_payment_method(self, payment_method_id: str) -> dict[str, object]:
        return dict(self.payment_methods[payment_method_id])

    async def set_customer_default_payment_method(
        self,
        *,
        stripe_customer_id: str,
        stripe_payment_method_id: str,
        metadata: dict[str, str],
    ) -> None:
        if self._default_error is not None:
            raise self._default_error
        self.default_payment_methods.append(
            {
                "stripe_customer_id": stripe_customer_id,
                "stripe_payment_method_id": stripe_payment_method_id,
                "metadata": metadata,
            }
        )


class _ConnectedAccounts:
    def __init__(self, account: ConnectedAccount | None) -> None:
        self.account = account
        self.calls = 0

    async def get_for_academy(self) -> ConnectedAccount | None:
        self.calls += 1
        return self.account


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
async def test_start_autopay_setup_routes_checkout_through_ready_connected_account() -> None:
    connected_account = ConnectedAccount.new(
        academy_id="acad",
        stripe_account_id="acct_ready",
    ).with_status(status="active", charges_enabled=True)
    connected_accounts = _ConnectedAccounts(connected_account)
    gateway = _CheckoutGateway()
    uc = StartSubscriptionCheckout(
        subscriptions=_SubscriptionRepo(),
        stripe=gateway,
        academy_id="acad",
        connected_accounts=connected_accounts,
    )

    await uc.execute(_checkout_command())

    assert connected_accounts.calls == 1
    assert gateway.setup_created[0]["connected_account_id"] == "acct_ready"


@pytest.mark.asyncio
async def test_start_autopay_setup_fails_closed_without_ready_connected_account() -> None:
    connected_accounts = _ConnectedAccounts(
        ConnectedAccount.new(academy_id="acad", stripe_account_id="acct_pending")
    )
    gateway = _CheckoutGateway()
    uc = StartSubscriptionCheckout(
        subscriptions=_SubscriptionRepo(),
        stripe=gateway,
        academy_id="acad",
        connected_accounts=connected_accounts,
    )

    with pytest.raises(CheckoutCreationFailed, match="connected account"):
        await uc.execute(_checkout_command())

    assert connected_accounts.calls == 1
    assert gateway.setup_created == []


class _SettingsRepo:
    def __init__(self, *, fallback: bool = False, error: bool = False) -> None:
        self._fallback = fallback
        self._error = error

    async def get(self):
        from backend.v2.contexts.billing.domain.billing_settings import BillingSettings

        if self._error:
            raise RuntimeError("settings lookup failed")
        return BillingSettings(academy_id="acad", allow_platform_charge_fallback=self._fallback)


@pytest.mark.asyncio
async def test_start_autopay_setup_falls_back_to_platform_when_flag_on() -> None:
    connected_accounts = _ConnectedAccounts(
        ConnectedAccount.new(academy_id="acad", stripe_account_id="acct_pending")
    )
    gateway = _CheckoutGateway()
    uc = StartSubscriptionCheckout(
        subscriptions=_SubscriptionRepo(),
        stripe=gateway,
        academy_id="acad",
        connected_accounts=connected_accounts,
        settings=_SettingsRepo(fallback=True),
    )

    result = await uc.execute(_checkout_command())

    assert result.redirect_url == "https://checkout.stripe.com/c/setup"
    assert gateway.setup_created[0]["connected_account_id"] is None


@pytest.mark.asyncio
async def test_start_autopay_setup_still_fails_closed_when_flag_off() -> None:
    connected_accounts = _ConnectedAccounts(
        ConnectedAccount.new(academy_id="acad", stripe_account_id="acct_pending")
    )
    gateway = _CheckoutGateway()
    uc = StartSubscriptionCheckout(
        subscriptions=_SubscriptionRepo(),
        stripe=gateway,
        academy_id="acad",
        connected_accounts=connected_accounts,
        settings=_SettingsRepo(fallback=False),
    )

    with pytest.raises(CheckoutCreationFailed, match="connected account"):
        await uc.execute(_checkout_command())
    assert gateway.setup_created == []


@pytest.mark.asyncio
async def test_start_autopay_setup_fails_closed_when_settings_lookup_errors() -> None:
    connected_accounts = _ConnectedAccounts(
        ConnectedAccount.new(academy_id="acad", stripe_account_id="acct_pending")
    )
    gateway = _CheckoutGateway()
    uc = StartSubscriptionCheckout(
        subscriptions=_SubscriptionRepo(),
        stripe=gateway,
        academy_id="acad",
        connected_accounts=connected_accounts,
        settings=_SettingsRepo(error=True),
    )

    with pytest.raises(CheckoutCreationFailed, match="connected account"):
        await uc.execute(_checkout_command())
    assert gateway.setup_created == []


@pytest.mark.asyncio
async def test_start_autopay_creates_setup_checkout_without_subscription_row() -> None:
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
    assert repo.saved == []
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
        "consent_text_version": "autopay-consent-v1",
        "ach_mandate_version": "ach-mandate-v1",
        "card_disclosure_version": "card-disclosure-v1",
    }
    assert repo.saved == []


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


@pytest.mark.asyncio
async def test_start_autopay_does_not_reuse_legacy_checkout_when_connect_is_enforced() -> None:
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
    connected_account = ConnectedAccount.new(
        academy_id="acad",
        stripe_account_id="acct_ready",
    ).with_status(status="active", charges_enabled=True)
    gateway = _CheckoutGateway()
    uc = StartSubscriptionCheckout(
        subscriptions=repo,
        stripe=gateway,
        academy_id="acad",
        connected_accounts=_ConnectedAccounts(connected_account),
        clock=lambda: now,
    )

    result = await uc.execute(_checkout_command())

    assert result.subscription_id != "sub-existing"
    assert result.checkout_session_id == "cs_setup_1"
    assert gateway.setup_created[0]["connected_account_id"] == "acct_ready"


class _NoPaymentRepo:
    async def get_by_checkout_session(self, checkout_session_id: str):
        return None


class _CustomerRepo:
    def __init__(self, *, fail_default_payment_method: bool = False) -> None:
        self.saved: list[dict[str, str]] = []
        self.default_methods: list[dict[str, object]] = []
        self.fail_default_payment_method = fail_default_payment_method

    async def set_stripe_customer_id(self, *, parent_id: str, stripe_customer_id: str) -> None:
        self.saved.append({"parent_id": parent_id, "stripe_customer_id": stripe_customer_id})

    async def set_default_payment_method(
        self,
        *,
        parent_id: str,
        stripe_customer_id: str,
        stripe_payment_method_id: str,
        payment_method_type: str,
        stripe_mandate_id: str | None,
        setup_intent_id: str,
        checkout_session_id: str | None,
        completed_at: datetime,
        current_consent_id: str | None = None,
        consent_text_version: str | None = None,
        ach_mandate_version: str | None = None,
        card_disclosure_version: str | None = None,
        setup_status: str = "active",
        payment_method_role: str = "primary",
        payment_method_label: str | None = None,
        payment_method_last4: str | None = None,
        session=None,
    ) -> None:
        if self.fail_default_payment_method:
            raise RuntimeError("parent projection write failed")
        row = {
            "parent_id": parent_id,
            "stripe_customer_id": stripe_customer_id,
            "stripe_payment_method_id": stripe_payment_method_id,
            "payment_method_type": payment_method_type,
            "stripe_mandate_id": stripe_mandate_id,
            "setup_intent_id": setup_intent_id,
            "checkout_session_id": checkout_session_id,
            "completed_at": completed_at,
            "setup_status": setup_status,
            "payment_method_role": payment_method_role,
        }
        if payment_method_label:
            row["payment_method_label"] = payment_method_label
        if payment_method_last4:
            row["payment_method_last4"] = payment_method_last4
        if current_consent_id:
            row["current_consent_id"] = current_consent_id
        if consent_text_version:
            row["consent_text_version"] = consent_text_version
        if ach_mandate_version:
            row["ach_mandate_version"] = ach_mandate_version
        if card_disclosure_version:
            row["card_disclosure_version"] = card_disclosure_version
        self.default_methods = [
            existing
            for existing in self.default_methods
            if not (
                existing["parent_id"] == parent_id
                and existing.get("payment_method_role", "primary") == payment_method_role
            )
        ]
        self.default_methods.append(row)

    async def promote_payment_method_to_default(
        self,
        *,
        parent_id: str,
        stripe_payment_method_id: str,
        payment_method_type: str,
        stripe_mandate_id: str | None,
        payment_method_label: str | None = None,
        payment_method_last4: str | None = None,
    ) -> None:
        for row in reversed(self.default_methods):
            if row["parent_id"] != parent_id:
                continue
            row["default_payment_method_id"] = stripe_payment_method_id
            row["default_payment_method_type"] = payment_method_type
            if payment_method_label:
                row["default_payment_method_label"] = payment_method_label
            if payment_method_last4:
                row["default_payment_method_last4"] = payment_method_last4
            if stripe_mandate_id:
                row["default_stripe_mandate_id"] = stripe_mandate_id
            return
        self.default_methods.append(
            {
                "parent_id": parent_id,
                "default_payment_method_id": stripe_payment_method_id,
                "default_payment_method_type": payment_method_type,
                "default_stripe_mandate_id": stripe_mandate_id,
            }
        )
        if payment_method_label:
            self.default_methods[-1]["default_payment_method_label"] = payment_method_label
        if payment_method_last4:
            self.default_methods[-1]["default_payment_method_last4"] = payment_method_last4


class _ConsentRepo:
    def __init__(self, *, fail: bool = False) -> None:
        self.consents: list[object] = []
        self.by_setup_intent: dict[str, object] = {}
        self.fail = fail

    async def append(self, consent, *, session=None):
        if self.fail:
            raise RuntimeError("consent append failed")
        existing = self.by_setup_intent.get(consent.setup_intent_id)
        if existing is not None:
            return existing
        self.consents.append(consent)
        self.by_setup_intent[consent.setup_intent_id] = consent
        return consent


class _Outbox:
    def __init__(self, *, fail: bool = False) -> None:
        self.events: list[object] = []
        self.fail = fail

    async def append(self, event, *, session=None) -> None:
        if self.fail:
            raise RuntimeError("outbox append failed")
        self.events.append(event)


class _EnrollmentAutopay:
    def __init__(self, *, setup_result: bool = True) -> None:
        self.synced: list[dict[str, str | None]] = []
        self.setup_completed: list[str] = []
        self.setup_result = setup_result

    async def set_autopay_state(
        self,
        *,
        enrollment_id: str,
        autopay_enrollment_status: str,
        session=None,
    ) -> bool:
        self.synced.append(
            {
                "enrollment_id": enrollment_id,
                "autopay_enrollment_status": autopay_enrollment_status,
            }
        )
        return True

    async def mark_autopay_active_from_setup(self, *, enrollment_id: str, session=None) -> bool:
        if not self.setup_result:
            self.setup_completed.append(enrollment_id)
            return False
        if enrollment_id not in self.setup_completed:
            self.setup_completed.append(enrollment_id)
        return True


class _FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeSession:
    def start_transaction(self):
        return _FakeTransaction()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeClient:
    async def start_session(self):
        return _FakeSession()


class _FakeDb:
    client = _FakeClient()


class _NoSessionClient:
    async def start_session(self):
        raise OperationFailure("Sessions are not supported by this MongoDB deployment")


class _NoSessionDb:
    client = _NoSessionClient()


def _setup_checkout_gateway() -> _CheckoutGateway:
    gateway = _CheckoutGateway(
        retrieved={
            "id": "cs_setup_complete",
            "object": "checkout.session",
            "mode": "setup",
            "status": "complete",
            "customer": "cus_parent",
            "setup_intent": "seti_saved_card",
            "client_reference_id": "p1",
            "metadata": {
                "parent_id": "p1",
                "academy_id": "acad",
                "app_subscription_id": "setup-local",
                "enrollment_id": "enr-1",
                "source": "autopay_setup",
            },
        }
    )
    gateway.setup_intents["seti_saved_card"] = {
        "id": "seti_saved_card",
        "object": "setup_intent",
        "customer": "cus_parent",
        "payment_method": "pm_saved_card",
        "mandate": "mandate_saved_card",
        "metadata": {
            "parent_id": "p1",
            "academy_id": "acad",
            "enrollment_id": "enr-1",
            "source": "autopay_setup",
        },
    }
    gateway.payment_methods["pm_saved_card"] = {
        "id": "pm_saved_card",
        "object": "payment_method",
        "type": "card",
    }
    return gateway


@pytest.mark.asyncio
async def test_complete_autopay_setup_appends_new_consent_row_on_reconsent() -> None:
    now = datetime(2026, 6, 11, tzinfo=UTC)
    customers = _CustomerRepo()
    consents = _ConsentRepo()
    outbox = _Outbox()
    enrollment_autopay = _EnrollmentAutopay()
    gateway = _CheckoutGateway()
    gateway.setup_intents["seti_first"] = {
        "id": "seti_first",
        "customer": "cus_parent",
        "payment_method": "pm_card_1",
        "metadata": {
            "academy_id": "acad",
            "parent_id": "p1",
            "enrollment_id": "enr-1",
            "source": "autopay_setup",
            "consent_text_version": "autopay-v2",
            "card_disclosure_version": "card-v2",
        },
    }
    gateway.setup_intents["seti_second"] = {
        "id": "seti_second",
        "customer": "cus_parent",
        "payment_method": "pm_card_2",
        "metadata": {
            "academy_id": "acad",
            "parent_id": "p1",
            "enrollment_id": "enr-1",
            "source": "autopay_setup",
            "consent_text_version": "autopay-v3",
            "card_disclosure_version": "card-v3",
        },
    }
    gateway.payment_methods["pm_card_1"] = {"id": "pm_card_1", "type": "card"}
    gateway.payment_methods["pm_card_2"] = {"id": "pm_card_2", "type": "card"}
    uc = CompleteAutopaySetup(
        stripe=gateway,
        parent_customers=customers,
        enrollment_autopay=enrollment_autopay,
        consent_repo=consents,
        outbox=outbox,
        academy_id="acad",
        clock=lambda: now,
    )

    await uc.execute_from_setup_intent(gateway.setup_intents["seti_first"])
    await uc.execute_from_setup_intent(gateway.setup_intents["seti_second"])

    assert len(consents.consents) == 2
    assert consents.consents[0].setup_intent_id == "seti_first"
    assert consents.consents[0].card_disclosure_version == "card-v2"
    assert consents.consents[1].setup_intent_id == "seti_second"
    assert consents.consents[1].card_disclosure_version == "card-v3"
    assert consents.consents[0].consent_id != consents.consents[1].consent_id
    assert [event.name for event in outbox.events] == [
        "Billing.AutopayConsentCaptured",
        "Billing.AutopayConsentCaptured",
    ]


@pytest.mark.asyncio
async def test_complete_autopay_setup_projects_card_display_details() -> None:
    now = datetime(2026, 6, 11, tzinfo=UTC)
    customers = _CustomerRepo()
    enrollment_autopay = _EnrollmentAutopay()
    gateway = _CheckoutGateway()
    gateway.setup_intents["seti_card"] = {
        "id": "seti_card",
        "customer": "cus_parent",
        "payment_method": "pm_card",
        "metadata": {
            "academy_id": "acad",
            "parent_id": "p1",
            "enrollment_id": "enr-1",
            "source": "autopay_setup",
        },
    }
    gateway.payment_methods["pm_card"] = {
        "id": "pm_card",
        "type": "card",
        "card": {"brand": "visa", "last4": "4242"},
    }
    uc = CompleteAutopaySetup(
        stripe=gateway,
        parent_customers=customers,
        enrollment_autopay=enrollment_autopay,
        academy_id="acad",
        clock=lambda: now,
    )

    await uc.execute_from_setup_intent(gateway.setup_intents["seti_card"])

    assert customers.default_methods[0]["payment_method_label"] == "Visa"
    assert customers.default_methods[0]["payment_method_last4"] == "4242"


@pytest.mark.asyncio
async def test_complete_autopay_setup_projects_bank_display_details() -> None:
    now = datetime(2026, 6, 11, tzinfo=UTC)
    customers = _CustomerRepo()
    enrollment_autopay = _EnrollmentAutopay()
    gateway = _CheckoutGateway()
    gateway.setup_intents["seti_bank"] = {
        "id": "seti_bank",
        "customer": "cus_parent",
        "payment_method": "pm_bank",
        "mandate": "mandate_bank",
        "metadata": {
            "academy_id": "acad",
            "parent_id": "p1",
            "enrollment_id": "enr-1",
            "source": "autopay_setup",
        },
    }
    gateway.payment_methods["pm_bank"] = {
        "id": "pm_bank",
        "type": "us_bank_account",
        "us_bank_account": {"bank_name": "STRIPE TEST BANK", "last4": "6789"},
    }
    uc = CompleteAutopaySetup(
        stripe=gateway,
        parent_customers=customers,
        enrollment_autopay=enrollment_autopay,
        academy_id="acad",
        clock=lambda: now,
    )

    await uc.execute_from_setup_intent(gateway.setup_intents["seti_bank"])

    assert customers.default_methods[0]["payment_method_label"] == "STRIPE TEST BANK"
    assert customers.default_methods[0]["payment_method_last4"] == "6789"


@pytest.mark.asyncio
async def test_complete_autopay_setup_emits_consent_event_with_method_version_and_source() -> None:
    now = datetime(2026, 6, 11, tzinfo=UTC)
    customers = _CustomerRepo()
    consents = _ConsentRepo()
    outbox = _Outbox()
    enrollment_autopay = _EnrollmentAutopay()
    gateway = _CheckoutGateway()
    gateway.setup_intents["seti_ach"] = {
        "id": "seti_ach",
        "customer": "cus_parent",
        "payment_method": "pm_ach",
        "mandate": "mandate_ach",
        "metadata": {
            "academy_id": "acad",
            "parent_id": "p1",
            "enrollment_id": "enr-1",
            "source": "autopay_setup",
            "consent_text_version": "autopay-v4",
            "ach_mandate_version": "ach-v4",
            "card_disclosure_version": "card-v4",
        },
    }
    gateway.payment_methods["pm_ach"] = {"id": "pm_ach", "type": "us_bank_account"}
    uc = CompleteAutopaySetup(
        stripe=gateway,
        parent_customers=customers,
        enrollment_autopay=enrollment_autopay,
        consent_repo=consents,
        outbox=outbox,
        academy_id="acad",
        clock=lambda: now,
    )

    await uc.execute_from_setup_intent(
        gateway.setup_intents["seti_ach"],
        consent_context=AutopayConsentCaptureContext(
            source="parent_checkout_status",
            actor_id="p1",
            ip="203.0.113.10",
            user_agent="pytest-browser",
        ),
    )

    assert len(consents.consents) == 1
    consent = consents.consents[0]
    assert consent.method_type == "us_bank_account"
    assert consent.ach_mandate_version == "ach-v4"
    assert consent.card_disclosure_version is None
    assert consent.source == "parent_checkout_status"
    assert consent.actor_id == "p1"
    assert consent.ip == "203.0.113.10"
    assert consent.user_agent == "pytest-browser"
    event = outbox.events[0]
    assert event.name == "Billing.AutopayConsentCaptured"
    assert event.aggregate_id == consent.consent_id
    assert event.payload.consent_id == consent.consent_id
    assert event.payload.method_type == "us_bank_account"
    assert event.payload.ach_mandate_version == "ach-v4"
    assert event.payload.card_disclosure_version is None
    assert event.payload.source == "parent_checkout_status"


@pytest.mark.asyncio
async def test_autopay_setup_replay_same_setup_intent_does_not_duplicate_consent_or_event() -> None:
    now = datetime(2026, 6, 11, tzinfo=UTC)
    repo = _SubscriptionRepo()
    customers = _CustomerRepo()
    consents = _ConsentRepo()
    outbox = _Outbox()
    enrollment_autopay = _EnrollmentAutopay()
    gateway = _setup_checkout_gateway()
    status_uc = GetCheckoutStatus(
        payments=_NoPaymentRepo(),
        subscriptions=repo,
        stripe=gateway,
        parent_customers=customers,
        enrollment_autopay=enrollment_autopay,
        consent_repo=consents,
        outbox=outbox,
        academy_id="acad",
        clock=lambda: now,
    )
    complete_uc = CompleteAutopaySetup(
        stripe=gateway,
        parent_customers=customers,
        enrollment_autopay=enrollment_autopay,
        consent_repo=consents,
        outbox=outbox,
        academy_id="acad",
        clock=lambda: now,
    )

    await status_uc.execute("cs_setup_complete", parent_id="p1")
    await complete_uc.execute_from_checkout(gateway.retrieved)
    await complete_uc.execute_from_setup_intent(gateway.setup_intents["seti_saved_card"])

    assert [consent.setup_intent_id for consent in consents.consents] == ["seti_saved_card"]
    assert [event.name for event in outbox.events] == ["Billing.AutopayConsentCaptured"]
    assert [row["setup_intent_id"] for row in customers.default_methods] == ["seti_saved_card"]
    assert customers.default_methods[0]["default_payment_method_id"] == "pm_saved_card"
    assert enrollment_autopay.setup_completed == ["enr-1"]


@pytest.mark.asyncio
async def test_autopay_setup_existing_consent_replay_repairs_projection_and_enrollment() -> None:
    now = datetime(2026, 6, 11, tzinfo=UTC)
    customers = _CustomerRepo()
    consents = _ConsentRepo()
    outbox = _Outbox()
    enrollment_autopay = _EnrollmentAutopay()
    gateway = _setup_checkout_gateway()
    uc = CompleteAutopaySetup(
        stripe=gateway,
        parent_customers=customers,
        enrollment_autopay=enrollment_autopay,
        consent_repo=consents,
        outbox=outbox,
        academy_id="acad",
        clock=lambda: now,
    )

    await uc.execute_from_setup_intent(gateway.setup_intents["seti_saved_card"])
    customers.default_methods.clear()
    enrollment_autopay.setup_completed.clear()

    await uc.execute_from_setup_intent(gateway.setup_intents["seti_saved_card"])

    assert [consent.setup_intent_id for consent in consents.consents] == ["seti_saved_card"]
    assert [event.name for event in outbox.events] == ["Billing.AutopayConsentCaptured"]
    assert customers.default_methods == [
        {
            "parent_id": "p1",
            "stripe_customer_id": "cus_parent",
            "stripe_payment_method_id": "pm_saved_card",
            "payment_method_type": "card",
            "stripe_mandate_id": "mandate_saved_card",
            "setup_intent_id": "seti_saved_card",
            "checkout_session_id": None,
            "completed_at": now,
            "setup_status": "active",
            "payment_method_role": "primary",
            "current_consent_id": consents.consents[0].consent_id,
            "consent_text_version": "autopay-consent-v1",
            "card_disclosure_version": "card-disclosure-v1",
            "default_payment_method_id": "pm_saved_card",
            "default_payment_method_type": "card",
            "default_stripe_mandate_id": "mandate_saved_card",
        }
    ]
    assert enrollment_autopay.setup_completed == ["enr-1"]


@pytest.mark.asyncio
async def test_autopay_setup_consent_append_failure_does_not_update_projection_or_enrollment() -> (
    None
):
    now = datetime(2026, 6, 11, tzinfo=UTC)
    customers = _CustomerRepo()
    consents = _ConsentRepo(fail=True)
    outbox = _Outbox()
    enrollment_autopay = _EnrollmentAutopay()
    gateway = _setup_checkout_gateway()
    uc = CompleteAutopaySetup(
        stripe=gateway,
        parent_customers=customers,
        enrollment_autopay=enrollment_autopay,
        consent_repo=consents,
        outbox=outbox,
        academy_id="acad",
        clock=lambda: now,
    )

    with pytest.raises(RuntimeError, match="consent append failed"):
        await uc.execute_from_setup_intent(gateway.setup_intents["seti_saved_card"])

    assert customers.default_methods == []
    assert outbox.events == []
    assert enrollment_autopay.setup_completed == []


@pytest.mark.asyncio
async def test_autopay_setup_outbox_failure_does_not_update_projection_or_enrollment() -> None:
    now = datetime(2026, 6, 11, tzinfo=UTC)
    customers = _CustomerRepo()
    consents = _ConsentRepo()
    outbox = _Outbox(fail=True)
    enrollment_autopay = _EnrollmentAutopay()
    gateway = _setup_checkout_gateway()
    uc = CompleteAutopaySetup(
        stripe=gateway,
        parent_customers=customers,
        enrollment_autopay=enrollment_autopay,
        consent_repo=consents,
        outbox=outbox,
        academy_id="acad",
        clock=lambda: now,
    )

    with pytest.raises(RuntimeError, match="outbox append failed"):
        await uc.execute_from_setup_intent(gateway.setup_intents["seti_saved_card"])

    assert customers.default_methods == []
    assert enrollment_autopay.setup_completed == []


@pytest.mark.asyncio
async def test_autopay_setup_projection_failure_does_not_activate_enrollment() -> None:
    now = datetime(2026, 6, 11, tzinfo=UTC)
    customers = _CustomerRepo(fail_default_payment_method=True)
    consents = _ConsentRepo()
    outbox = _Outbox()
    enrollment_autopay = _EnrollmentAutopay()
    gateway = _setup_checkout_gateway()
    uc = CompleteAutopaySetup(
        stripe=gateway,
        parent_customers=customers,
        enrollment_autopay=enrollment_autopay,
        consent_repo=consents,
        outbox=outbox,
        academy_id="acad",
        clock=lambda: now,
    )

    with pytest.raises(RuntimeError, match="parent projection write failed"):
        await uc.execute_from_setup_intent(gateway.setup_intents["seti_saved_card"])

    assert [consent.setup_intent_id for consent in consents.consents] == ["seti_saved_card"]
    assert [event.name for event in outbox.events] == ["Billing.AutopayConsentCaptured"]
    assert customers.default_methods == []
    assert gateway.default_payment_methods == []
    assert enrollment_autopay.setup_completed == []


@pytest.mark.asyncio
async def test_autopay_setup_stripe_default_failure_does_not_activate_enrollment() -> None:
    now = datetime(2026, 6, 11, tzinfo=UTC)
    customers = _CustomerRepo()
    consents = _ConsentRepo()
    outbox = _Outbox()
    enrollment_autopay = _EnrollmentAutopay()
    gateway = _setup_checkout_gateway()
    gateway._default_error = RuntimeError("stripe default failed")
    uc = CompleteAutopaySetup(
        stripe=gateway,
        parent_customers=customers,
        enrollment_autopay=enrollment_autopay,
        consent_repo=consents,
        outbox=outbox,
        academy_id="acad",
        clock=lambda: now,
    )

    with pytest.raises(RuntimeError, match="stripe default failed"):
        await uc.execute_from_setup_intent(gateway.setup_intents["seti_saved_card"])

    assert [consent.setup_intent_id for consent in consents.consents] == ["seti_saved_card"]
    assert [event.name for event in outbox.events] == ["Billing.AutopayConsentCaptured"]
    assert [row["setup_intent_id"] for row in customers.default_methods] == ["seti_saved_card"]
    assert "default_payment_method_id" not in customers.default_methods[0]
    assert gateway.default_payment_methods == []
    assert enrollment_autopay.setup_completed == []


@pytest.mark.asyncio
async def test_autopay_setup_enrollment_activation_failure_raises_after_projection() -> None:
    now = datetime(2026, 6, 11, tzinfo=UTC)
    customers = _CustomerRepo()
    consents = _ConsentRepo()
    outbox = _Outbox()
    enrollment_autopay = _EnrollmentAutopay(setup_result=False)
    gateway = _setup_checkout_gateway()
    uc = CompleteAutopaySetup(
        stripe=gateway,
        parent_customers=customers,
        enrollment_autopay=enrollment_autopay,
        consent_repo=consents,
        outbox=outbox,
        academy_id="acad",
        clock=lambda: now,
    )

    with pytest.raises(RuntimeError, match="autopay enrollment activation failed"):
        await uc.execute_from_setup_intent(gateway.setup_intents["seti_saved_card"])

    assert [consent.setup_intent_id for consent in consents.consents] == ["seti_saved_card"]
    assert [event.name for event in outbox.events] == ["Billing.AutopayConsentCaptured"]
    assert [row["setup_intent_id"] for row in customers.default_methods] == ["seti_saved_card"]
    assert customers.default_methods[0]["default_payment_method_id"] == "pm_saved_card"
    assert enrollment_autopay.setup_completed == ["enr-1"]


@pytest.mark.asyncio
async def test_mongo_transaction_runner_does_not_fallback_after_work_started() -> None:
    runner = _MongoTransactionRunner(_FakeDb())
    sessions: list[object | None] = []

    async def work(session):
        sessions.append(session)
        raise AttributeError("repository bug after transaction started")

    with pytest.raises(AttributeError, match="repository bug"):
        await runner.run(work)

    assert len(sessions) == 1
    assert sessions[0] is not None


@pytest.mark.asyncio
async def test_mongo_transaction_runner_falls_back_when_sessions_unavailable() -> None:
    runner = _MongoTransactionRunner(_NoSessionDb())
    sessions: list[object | None] = []

    async def work(session):
        sessions.append(session)
        return "ok"

    assert await runner.run(work) == "ok"
    assert sessions == [None]


@pytest.mark.asyncio
async def test_mongo_transaction_runner_falls_back_when_standalone_mongo_rejects_first_op() -> None:
    """Standalone mongod: start_session()/start_transaction() both succeed, but
    the first operation executed inside work(session) raises OperationFailure
    code 20 ("Transaction numbers are only allowed on a replica set member or
    mongos"). The runner must catch that failure, let the transaction context
    abort, and retry with work(None) rather than letting the error escape."""
    runner = _MongoTransactionRunner(_FakeDb())
    sessions: list[object | None] = []

    async def work(session):
        sessions.append(session)
        if session is not None:
            raise OperationFailure(
                "Transaction numbers are only allowed on a replica set member or mongos",
                code=20,
            )
        return "ok"

    assert await runner.run(work) == "ok"
    assert len(sessions) == 2
    assert sessions[0] is not None
    assert sessions[1] is None


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
        academy_id="acad",
        clock=lambda: now,
    )

    result = await uc.execute("cs_complete", parent_id="p1")

    assert result.status == "active"
    assert result.payment_id is None
    assert repo.by_id["sub-local"].stripe_subscription_id == "sub_live_123"
    assert repo.by_id["sub-local"].status == "active"
    assert customers.saved == [{"parent_id": "p1", "stripe_customer_id": "cus_parent"}]
    assert enrollment_autopay.setup_completed == ["enr-1"]
    assert enrollment_autopay.synced == []


@pytest.mark.asyncio
async def test_checkout_status_reconciles_completed_setup_checkout_without_subscription() -> None:
    now = datetime(2026, 6, 11, tzinfo=UTC)
    repo = _SubscriptionRepo()
    customers = _CustomerRepo()
    enrollment_autopay = _EnrollmentAutopay()
    gateway = _setup_checkout_gateway()
    uc = GetCheckoutStatus(
        payments=_NoPaymentRepo(),
        subscriptions=repo,
        stripe=gateway,
        parent_customers=customers,
        enrollment_autopay=enrollment_autopay,
        academy_id="acad",
        clock=lambda: now,
    )

    result = await uc.execute("cs_setup_complete", parent_id="p1")

    assert result.status == "active"
    assert result.payment_id is None
    assert repo.saved == []
    assert customers.saved == []
    assert gateway.default_payment_methods == [
        {
            "stripe_customer_id": "cus_parent",
            "stripe_payment_method_id": "pm_saved_card",
            "metadata": {"academy_id": "acad", "parent_id": "p1"},
        }
    ]
    assert customers.default_methods == [
        {
            "parent_id": "p1",
            "stripe_customer_id": "cus_parent",
            "stripe_payment_method_id": "pm_saved_card",
            "payment_method_type": "card",
            "stripe_mandate_id": "mandate_saved_card",
            "setup_intent_id": "seti_saved_card",
            "checkout_session_id": "cs_setup_complete",
            "completed_at": now,
            "setup_status": "active",
            "payment_method_role": "primary",
            "default_payment_method_id": "pm_saved_card",
            "default_payment_method_type": "card",
            "default_stripe_mandate_id": "mandate_saved_card",
        }
    ]
    assert enrollment_autopay.setup_completed == ["enr-1"]
    assert enrollment_autopay.synced == []


# ---------------------------------------------------------------------------
# Autopay opt-in at payment time (invoice / balance checkout, mode=payment)
# ---------------------------------------------------------------------------


def _optin_payment_checkout(
    *,
    session_id: str = "cs_pay_optin",
    enrollment_ids: str | None = "enr-1",
    status: str = "complete",
    parent_id: str = "p1",
) -> dict[str, object]:
    metadata: dict[str, str] = {
        "academy_id": "acad",
        "parent_id": parent_id,
        "invoice_id": "inv-1",
        "source": "invoice_pay_link",
        "autopay_optin": "true",
    }
    if enrollment_ids:
        metadata["enrollment_ids"] = enrollment_ids
    return {
        "id": session_id,
        "object": "checkout.session",
        "mode": "payment",
        "status": status,
        "payment_status": "paid" if status == "complete" else "unpaid",
        "customer": "cus_parent",
        "payment_intent": "pi_optin",
        "client_reference_id": parent_id,
        "metadata": metadata,
    }


def _optin_payment_gateway(
    checkout: dict[str, object] | None = None,
    *,
    default_error: Exception | None = None,
) -> _CheckoutGateway:
    gateway = _CheckoutGateway(retrieved=checkout, default_error=default_error)
    gateway.payment_intents["pi_optin"] = {
        "id": "pi_optin",
        "object": "payment_intent",
        "customer": "cus_parent",
        "payment_method": "pm_card",
    }
    gateway.payment_methods["pm_card"] = {
        "id": "pm_card",
        "object": "payment_method",
        "type": "card",
        "card": {"brand": "visa", "last4": "4242"},
    }
    return gateway


def _optin_complete_uc(
    gateway: _CheckoutGateway,
    *,
    customers: _CustomerRepo,
    consents: _ConsentRepo,
    outbox: _Outbox,
    enrollment_autopay: _EnrollmentAutopay,
    now: datetime,
) -> CompleteAutopaySetup:
    return CompleteAutopaySetup(
        stripe=gateway,
        parent_customers=customers,
        enrollment_autopay=enrollment_autopay,
        consent_repo=consents,
        outbox=outbox,
        academy_id="acad",
        clock=lambda: now,
    )


@pytest.mark.asyncio
async def test_complete_autopay_optin_payment_activates_single_enrollment() -> None:
    now = datetime(2026, 7, 5, tzinfo=UTC)
    customers = _CustomerRepo()
    consents = _ConsentRepo()
    outbox = _Outbox()
    enrollment_autopay = _EnrollmentAutopay()
    gateway = _optin_payment_gateway()
    uc = _optin_complete_uc(
        gateway,
        customers=customers,
        consents=consents,
        outbox=outbox,
        enrollment_autopay=enrollment_autopay,
        now=now,
    )

    activated = await uc.execute_from_payment_checkout(_optin_payment_checkout())

    assert activated == ["enr-1"]
    assert enrollment_autopay.setup_completed == ["enr-1"]
    assert gateway.default_payment_methods == [
        {
            "stripe_customer_id": "cus_parent",
            "stripe_payment_method_id": "pm_card",
            "metadata": {"academy_id": "acad", "parent_id": "p1"},
        }
    ]
    assert len(consents.consents) == 1
    consent = consents.consents[0]
    assert consent.enrollment_id == "enr-1"
    assert consent.source == "invoice_payment_optin"
    assert consent.method_type == "card"
    assert consent.checkout_session_id == "cs_pay_optin"
    assert [event.name for event in outbox.events] == ["Billing.AutopayConsentCaptured"]
    assert customers.default_methods
    assert customers.default_methods[-1]["default_payment_method_id"] == "pm_card"


@pytest.mark.asyncio
async def test_complete_autopay_optin_payment_activates_all_metadata_enrollments() -> None:
    now = datetime(2026, 7, 5, tzinfo=UTC)
    customers = _CustomerRepo()
    consents = _ConsentRepo()
    outbox = _Outbox()
    enrollment_autopay = _EnrollmentAutopay()
    gateway = _optin_payment_gateway()
    uc = _optin_complete_uc(
        gateway,
        customers=customers,
        consents=consents,
        outbox=outbox,
        enrollment_autopay=enrollment_autopay,
        now=now,
    )

    activated = await uc.execute_from_payment_checkout(
        _optin_payment_checkout(enrollment_ids="enr-1,enr-2")
    )

    assert activated == ["enr-1", "enr-2"]
    assert enrollment_autopay.setup_completed == ["enr-1", "enr-2"]
    assert sorted(consent.enrollment_id for consent in consents.consents) == ["enr-1", "enr-2"]
    # One saved payment method for the whole opt-in.
    assert len(gateway.default_payment_methods) == 1


@pytest.mark.asyncio
async def test_complete_autopay_optin_replay_is_idempotent() -> None:
    now = datetime(2026, 7, 5, tzinfo=UTC)
    customers = _CustomerRepo()
    consents = _ConsentRepo()
    outbox = _Outbox()
    enrollment_autopay = _EnrollmentAutopay()
    gateway = _optin_payment_gateway()
    uc = _optin_complete_uc(
        gateway,
        customers=customers,
        consents=consents,
        outbox=outbox,
        enrollment_autopay=enrollment_autopay,
        now=now,
    )

    first = await uc.execute_from_payment_checkout(_optin_payment_checkout())
    second = await uc.execute_from_payment_checkout(_optin_payment_checkout())

    assert first == ["enr-1"]
    assert second == ["enr-1"]
    assert enrollment_autopay.setup_completed == ["enr-1"]
    # Consent rows and events are not duplicated on webhook/poll replay.
    assert len(consents.consents) == 1
    assert [event.name for event in outbox.events] == ["Billing.AutopayConsentCaptured"]


@pytest.mark.asyncio
async def test_complete_autopay_optin_missing_enrollment_doc_attempts_all_then_raises() -> None:
    """Activation returning False (e.g. missing student_billing_enrollments doc)
    must attempt EVERY enrollment first, then raise so the webhook worker
    retries the event. The checkout-status poll path catches the raise, so the
    payment's parent-facing result stays unaffected."""
    now = datetime(2026, 7, 5, tzinfo=UTC)
    customers = _CustomerRepo()
    consents = _ConsentRepo()
    outbox = _Outbox()
    enrollment_autopay = _EnrollmentAutopay(setup_result=False)
    gateway = _optin_payment_gateway()
    uc = _optin_complete_uc(
        gateway,
        customers=customers,
        consents=consents,
        outbox=outbox,
        enrollment_autopay=enrollment_autopay,
        now=now,
    )

    with pytest.raises(RuntimeError, match="enr-1.*enr-2"):
        await uc.execute_from_payment_checkout(
            _optin_payment_checkout(enrollment_ids="enr-1,enr-2")
        )

    # Both enrollments were attempted before the failure surfaced.
    assert enrollment_autopay.setup_completed == ["enr-1", "enr-2"]


@pytest.mark.asyncio
async def test_complete_autopay_optin_rejects_plain_payment_checkout() -> None:
    now = datetime(2026, 7, 5, tzinfo=UTC)
    gateway = _optin_payment_gateway()
    uc = _optin_complete_uc(
        gateway,
        customers=_CustomerRepo(),
        consents=_ConsentRepo(),
        outbox=_Outbox(),
        enrollment_autopay=_EnrollmentAutopay(),
        now=now,
    )
    checkout = _optin_payment_checkout()
    checkout["metadata"] = {"academy_id": "acad", "parent_id": "p1", "invoice_id": "inv-1"}

    with pytest.raises(ValueError, match="autopay opt-in"):
        await uc.execute_from_payment_checkout(checkout)


def _optin_status_uc(
    gateway: _CheckoutGateway,
    *,
    customers: _CustomerRepo,
    consents: _ConsentRepo,
    outbox: _Outbox,
    enrollment_autopay: _EnrollmentAutopay,
    now: datetime,
) -> GetCheckoutStatus:
    return GetCheckoutStatus(
        payments=_NoPaymentRepo(),
        stripe=gateway,
        parent_customers=customers,
        enrollment_autopay=enrollment_autopay,
        consent_repo=consents,
        outbox=outbox,
        academy_id="acad",
        clock=lambda: now,
    )


@pytest.mark.asyncio
async def test_checkout_status_completes_autopay_optin_payment_checkout() -> None:
    now = datetime(2026, 7, 5, tzinfo=UTC)
    customers = _CustomerRepo()
    consents = _ConsentRepo()
    outbox = _Outbox()
    enrollment_autopay = _EnrollmentAutopay()
    gateway = _optin_payment_gateway(_optin_payment_checkout())
    uc = _optin_status_uc(
        gateway,
        customers=customers,
        consents=consents,
        outbox=outbox,
        enrollment_autopay=enrollment_autopay,
        now=now,
    )

    result = await uc.execute("cs_pay_optin", parent_id="p1")

    assert result.status == "succeeded"
    assert result.payment_id is None
    assert result.parent_id == "p1"
    assert enrollment_autopay.setup_completed == ["enr-1"]
    assert len(consents.consents) == 1


@pytest.mark.asyncio
async def test_checkout_status_returns_succeeded_even_when_optin_activation_fails() -> None:
    """A succeeded payment's status response must NEVER fail because autopay
    activation errored — log and let the webhook worker retry."""
    now = datetime(2026, 7, 5, tzinfo=UTC)
    enrollment_autopay = _EnrollmentAutopay()
    gateway = _optin_payment_gateway(
        _optin_payment_checkout(),
        default_error=RuntimeError("stripe customer update failed"),
    )
    uc = _optin_status_uc(
        gateway,
        customers=_CustomerRepo(),
        consents=_ConsentRepo(),
        outbox=_Outbox(),
        enrollment_autopay=enrollment_autopay,
        now=now,
    )

    result = await uc.execute("cs_pay_optin", parent_id="p1")

    assert result.status == "succeeded"
    assert enrollment_autopay.setup_completed == []


@pytest.mark.asyncio
async def test_checkout_status_open_optin_payment_checkout_reports_status_without_activation() -> (
    None
):
    now = datetime(2026, 7, 5, tzinfo=UTC)
    enrollment_autopay = _EnrollmentAutopay()
    gateway = _optin_payment_gateway(_optin_payment_checkout(status="open"))
    uc = _optin_status_uc(
        gateway,
        customers=_CustomerRepo(),
        consents=_ConsentRepo(),
        outbox=_Outbox(),
        enrollment_autopay=enrollment_autopay,
        now=now,
    )

    result = await uc.execute("cs_pay_optin", parent_id="p1")

    assert result.status == "open"
    assert enrollment_autopay.setup_completed == []
    assert gateway.default_payment_methods == []


@pytest.mark.asyncio
async def test_checkout_status_optin_payment_checkout_rejects_wrong_parent() -> None:
    now = datetime(2026, 7, 5, tzinfo=UTC)
    gateway = _optin_payment_gateway(_optin_payment_checkout())
    uc = _optin_status_uc(
        gateway,
        customers=_CustomerRepo(),
        consents=_ConsentRepo(),
        outbox=_Outbox(),
        enrollment_autopay=_EnrollmentAutopay(),
        now=now,
    )

    with pytest.raises(PaymentNotFound):
        await uc.execute("cs_pay_optin", parent_id="someone-else")


@pytest.mark.asyncio
async def test_checkout_status_plain_payment_checkout_still_raises_payment_not_found() -> None:
    """A mode=payment session WITHOUT the opt-in metadata takes none of the new
    branches — unchanged 404 behavior."""
    now = datetime(2026, 7, 5, tzinfo=UTC)
    checkout = _optin_payment_checkout()
    checkout["metadata"] = {"academy_id": "acad", "parent_id": "p1", "invoice_id": "inv-1"}
    gateway = _optin_payment_gateway(checkout)
    uc = _optin_status_uc(
        gateway,
        customers=_CustomerRepo(),
        consents=_ConsentRepo(),
        outbox=_Outbox(),
        enrollment_autopay=_EnrollmentAutopay(),
        now=now,
    )

    with pytest.raises(PaymentNotFound):
        await uc.execute("cs_pay_optin", parent_id="p1")
