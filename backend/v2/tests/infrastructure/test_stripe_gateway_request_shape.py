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


@pytest.fixture(autouse=True)
def fake_stripe_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeCheckoutSession.calls.clear()
    fake_stripe = SimpleNamespace(
        api_key=None,
        checkout=SimpleNamespace(Session=_FakeCheckoutSession),
        billing_portal=SimpleNamespace(Session=SimpleNamespace()),
        Webhook=SimpleNamespace(),
        Refund=SimpleNamespace(),
        Subscription=SimpleNamespace(),
        Invoice=SimpleNamespace(),
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
