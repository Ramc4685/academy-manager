"""Request-shape checks for the real Stripe gateway.

These tests fake the Stripe SDK so CI can verify parameters without making
network calls.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import ClassVar

import pytest
from backend.v2.contexts.billing.infrastructure.stripe_gateway import RealStripeGateway


class _FakeStripeError(Exception):
    pass


class _FakeCheckoutSession:
    calls: ClassVar[list[dict[str, object]]] = []

    @classmethod
    def create(cls, **kwargs: object) -> SimpleNamespace:
        cls.calls.append(kwargs)
        return SimpleNamespace(
            id="cs_test_request_shape",
            url="https://checkout.stripe.test/session",
            subscription="sub_test_request_shape",
        )

    @classmethod
    def retrieve(cls, checkout_session_id: str) -> object:
        if checkout_session_id == "cs_missing":
            raise _FakeStripeError("No such checkout.session")

        class _StripeObject:
            def _to_dict_recursive(self) -> dict[str, object]:
                return {"id": checkout_session_id, "object": "checkout.session"}

        return _StripeObject()


class _FakeStripeCustomerObject:
    """Mirrors a real Stripe object: attribute access works, ``.get`` does not."""

    def __init__(self, **fields: object) -> None:
        self._data = fields

    def __getattr__(self, name: str) -> object:
        try:
            return self._data[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __getitem__(self, key: str) -> object:
        return self._data[key]


class _FakeCustomer:
    calls: ClassVar[list[dict[str, object]]] = []
    modify_calls: ClassVar[list[dict[str, object]]] = []

    @classmethod
    def search(cls, **kwargs: object) -> object:
        cls.calls.append(kwargs)
        # Real ``Customer.search`` returns a SearchResultObject, not a dict;
        # ``.get`` is not a method on it, so the gateway must use ``.data``.
        return _FakeStripeCustomerObject(
            data=[
                _FakeStripeCustomerObject(
                    id="cus_scoped",
                    invoice_settings=_FakeStripeCustomerObject(default_payment_method="pm_scoped"),
                )
            ]
        )

    @classmethod
    def modify(cls, customer_id: str, **kwargs: object) -> object:
        cls.modify_calls.append({"customer_id": customer_id, **kwargs})
        return _FakeStripeCustomerObject(id=customer_id)


class _FakePaymentIntent:
    calls: ClassVar[list[dict[str, object]]] = []

    @classmethod
    def search(cls, **kwargs: object) -> object:
        cls.calls.append(kwargs)
        return SimpleNamespace(data=[{"id": "pi_search_1", "status": "succeeded"}])


class _FakeSetupIntent:
    @classmethod
    def retrieve(cls, setup_intent_id: str) -> object:
        return {
            "id": setup_intent_id,
            "object": "setup_intent",
            "payment_method": "pm_request_shape",
        }


class _FakePaymentMethod:
    @classmethod
    def retrieve(cls, payment_method_id: str) -> object:
        return {
            "id": payment_method_id,
            "object": "payment_method",
            "type": "card",
        }


@pytest.fixture(autouse=True)
def fake_stripe_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeCheckoutSession.calls.clear()
    _FakeCustomer.calls.clear()
    _FakeCustomer.modify_calls.clear()
    _FakePaymentIntent.calls.clear()
    fake_stripe = SimpleNamespace(
        api_key=None,
        checkout=SimpleNamespace(Session=_FakeCheckoutSession),
        billing_portal=SimpleNamespace(Session=SimpleNamespace()),
        Customer=_FakeCustomer,
        PaymentIntent=_FakePaymentIntent,
        SetupIntent=_FakeSetupIntent,
        PaymentMethod=_FakePaymentMethod,
        Webhook=SimpleNamespace(),
        Refund=SimpleNamespace(),
        Subscription=SimpleNamespace(),
        Invoice=SimpleNamespace(),
        StripeError=_FakeStripeError,
    )
    monkeypatch.setitem(sys.modules, "stripe", fake_stripe)


@pytest.mark.asyncio
async def test_subscription_checkout_omits_invalid_initial_proration_behavior() -> None:
    gateway = RealStripeGateway(api_key="sk_test_fake", webhook_secret="whsec_fake")

    await gateway.create_subscription_checkout_session(
        parent_id="parent_1",
        enrollment_id="enrollment_1",
        session_id="session_1",
        amount_cents=7000,
        success_url="https://example.test/success",
        cancel_url="https://example.test/cancel",
        metadata={"academy_id": "academy_1"},
    )

    request = _FakeCheckoutSession.calls[-1]
    assert request["mode"] == "subscription"
    assert "payment_method_types" not in request
    assert request["subscription_data"] == {
        "metadata": {
            "academy_id": "academy_1",
            "enrollment_id": "enrollment_1",
        }
    }


@pytest.mark.asyncio
async def test_autopay_setup_checkout_uses_setup_mode_without_subscription_data() -> None:
    gateway = RealStripeGateway(api_key="sk_test_fake", webhook_secret="whsec_fake")

    await gateway.create_autopay_setup_checkout_session(
        parent_id="parent_1",
        enrollment_id="enrollment_1",
        session_id="session_1",
        success_url="https://example.test/success",
        cancel_url="https://example.test/cancel",
        metadata={
            "academy_id": "academy_1",
            "parent_id": "parent_1",
            "source": "autopay_setup",
        },
    )

    request = _FakeCheckoutSession.calls[-1]
    assert request["mode"] == "setup"
    assert request["currency"] == "usd"
    assert request["customer_creation"] == "always"
    assert request["client_reference_id"] == "parent_1"
    assert "subscription_data" not in request
    assert "line_items" not in request
    assert request["metadata"] == {
        "academy_id": "academy_1",
        "parent_id": "parent_1",
        "source": "autopay_setup",
        "enrollment_id": "enrollment_1",
        "session_id": "session_1",
    }
    assert request["setup_intent_data"] == {
        "metadata": {
            "academy_id": "academy_1",
            "parent_id": "parent_1",
            "source": "autopay_setup",
            "enrollment_id": "enrollment_1",
            "session_id": "session_1",
        }
    }


@pytest.mark.asyncio
async def test_payment_intent_reconciliation_search_is_scoped_to_academy() -> None:
    gateway = RealStripeGateway(api_key="sk_test_fake", webhook_secret="whsec_fake")

    result = await gateway.search_app_owned_payment_intents(academy_id="academy_1", limit=25)

    assert result == [{"id": "pi_search_1", "status": "succeeded"}]
    # `processing` is included alongside `succeeded` so ACH-in-flight PIs
    # (§7.2) are visible to reconciliation instead of only appearing once
    # settled.
    assert _FakePaymentIntent.calls[-1] == {
        "query": (
            'metadata["academy_id"]:"academy_1" AND (status:"succeeded" OR status:"processing")'
        ),
        "limit": 25,
    }


@pytest.mark.asyncio
async def test_payment_intent_reconciliation_search_scopes_to_connected_account() -> None:
    """Slice I: reconciliation must be able to search a connected account's
    PaymentIntents by passing Stripe's `stripe_account` header/param, or money
    routed through that account is invisible to platform-level search."""
    gateway = RealStripeGateway(api_key="sk_test_fake", webhook_secret="whsec_fake")

    await gateway.search_app_owned_payment_intents(
        academy_id="academy_1", limit=25, stripe_account="acct_connected_1"
    )

    assert _FakePaymentIntent.calls[-1]["stripe_account"] == "acct_connected_1"


@pytest.mark.asyncio
async def test_payment_intent_reconciliation_search_omits_stripe_account_when_platform_scoped() -> (
    None
):
    gateway = RealStripeGateway(api_key="sk_test_fake", webhook_secret="whsec_fake")

    await gateway.search_app_owned_payment_intents(academy_id="academy_1", limit=25)

    assert "stripe_account" not in _FakePaymentIntent.calls[-1]


@pytest.mark.asyncio
async def test_payment_checkout_uses_dynamic_payment_methods() -> None:
    gateway = RealStripeGateway(api_key="sk_test_fake", webhook_secret="whsec_fake")

    await gateway.create_checkout_session(
        parent_id="parent_1",
        session_id="session_1",
        amount_cents=7000,
        success_url="https://example.test/success",
        cancel_url="https://example.test/cancel",
        metadata={"academy_id": "academy_1"},
    )

    request = _FakeCheckoutSession.calls[-1]
    assert request["mode"] == "payment"
    assert "payment_method_types" not in request


@pytest.mark.asyncio
async def test_customer_default_payment_method_sets_invoice_settings_and_metadata() -> None:
    gateway = RealStripeGateway(api_key="sk_test_fake", webhook_secret="whsec_fake")

    await gateway.set_customer_default_payment_method(
        stripe_customer_id="cus_123",
        stripe_payment_method_id="pm_123",
        metadata={"academy_id": "academy_1", "parent_id": "parent_1"},
    )

    assert _FakeCustomer.modify_calls == [
        {
            "customer_id": "cus_123",
            "invoice_settings": {"default_payment_method": "pm_123"},
            "metadata": {"academy_id": "academy_1", "parent_id": "parent_1"},
        }
    ]


@pytest.mark.asyncio
async def test_invoice_checkout_session_uses_invoice_metadata_and_reference() -> None:
    gateway = RealStripeGateway(api_key="sk_test_fake", webhook_secret="whsec_fake")

    session_id, checkout_url = await gateway.create_invoice_checkout_session(
        invoice_id="inv_123",
        amount_cents=4100,
        currency="usd",
        success_url="https://example.test/paid",
        cancel_url="https://example.test/cancelled",
        metadata={
            "invoice_id": "inv_123",
            "academy_id": "academy_1",
            "parent_id": "parent_1",
            "source": "invoice_pay_link",
        },
        idempotency_key="invoice-checkout:inv_123:4100",
    )

    request = _FakeCheckoutSession.calls[-1]
    assert session_id == "cs_test_request_shape"
    assert checkout_url == "https://checkout.stripe.test/session"
    assert request["mode"] == "payment"
    assert request["client_reference_id"] == "parent_1"
    assert request["idempotency_key"] == "invoice-checkout:inv_123:4100"
    assert request["metadata"] == {
        "invoice_id": "inv_123",
        "academy_id": "academy_1",
        "parent_id": "parent_1",
        "source": "invoice_pay_link",
    }
    assert request["payment_intent_data"] == {
        "metadata": {
            "invoice_id": "inv_123",
            "academy_id": "academy_1",
            "parent_id": "parent_1",
            "source": "invoice_pay_link",
        }
    }
    assert request["line_items"] == [
        {
            "price_data": {
                "currency": "usd",
                "product_data": {"name": "Academy invoice inv_123"},
                "unit_amount": 4100,
            },
            "quantity": 1,
        }
    ]


@pytest.mark.asyncio
async def test_retrieve_checkout_session_serializes_current_stripe_objects() -> None:
    gateway = RealStripeGateway(api_key="sk_test_fake", webhook_secret="whsec_fake")

    result = await gateway.retrieve_checkout_session("cs_test_request_shape")

    assert result == {"id": "cs_test_request_shape", "object": "checkout.session"}


@pytest.mark.asyncio
async def test_retrieve_checkout_session_converts_stripe_errors_to_value_error() -> None:
    gateway = RealStripeGateway(api_key="sk_test_fake", webhook_secret="whsec_fake")

    with pytest.raises(ValueError, match="Stripe Checkout Session lookup failed"):
        await gateway.retrieve_checkout_session("cs_missing")


@pytest.mark.asyncio
async def test_default_payment_method_search_is_academy_and_parent_scoped() -> None:
    gateway = RealStripeGateway(api_key="sk_test_fake", webhook_secret="whsec_fake")

    result = await gateway.get_default_payment_method(
        academy_id="academy_1",
        parent_id="parent_1",
    )

    assert result == ("cus_scoped", "pm_scoped")
    assert _FakeCustomer.calls == [
        {
            "query": 'metadata["academy_id"]:"academy_1" AND metadata["parent_id"]:"parent_1"',
            "limit": 1,
        }
    ]
