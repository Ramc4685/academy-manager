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


class _FakeCustomer:
    calls: ClassVar[list[dict[str, object]]] = []

    @classmethod
    def search(cls, **kwargs: object) -> dict[str, object]:
        cls.calls.append(kwargs)
        return {
            "data": [
                {
                    "id": "cus_scoped",
                    "invoice_settings": {"default_payment_method": "pm_scoped"},
                }
            ]
        }


@pytest.fixture(autouse=True)
def fake_stripe_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeCheckoutSession.calls.clear()
    _FakeCustomer.calls.clear()
    fake_stripe = SimpleNamespace(
        api_key=None,
        checkout=SimpleNamespace(Session=_FakeCheckoutSession),
        billing_portal=SimpleNamespace(Session=SimpleNamespace()),
        Customer=_FakeCustomer,
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
    )

    request = _FakeCheckoutSession.calls[-1]
    assert session_id == "cs_test_request_shape"
    assert checkout_url == "https://checkout.stripe.test/session"
    assert request["mode"] == "payment"
    assert request["client_reference_id"] == "parent_1"
    assert request["metadata"] == {
        "invoice_id": "inv_123",
        "academy_id": "academy_1",
        "parent_id": "parent_1",
        "source": "invoice_pay_link",
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
