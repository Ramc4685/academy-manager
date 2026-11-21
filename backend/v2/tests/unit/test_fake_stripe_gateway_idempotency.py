"""FakeStripeGateway replays an off-session PaymentIntent key the way Stripe does.

Stripe compares the WHOLE request on a reused idempotency key, not just the
amount: the same key with any other parameter (metadata included) is an
``IdempotencyError``. A fake that only compared the amount let a retry with
changed metadata look like a clean replay, which real Stripe refuses.
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.v2.contexts.billing.domain.errors import StripeIdempotencyConflict
from backend.v2.contexts.billing.infrastructure.fake_stripe_gateway import FakeStripeGateway

pytestmark = pytest.mark.asyncio


def _request(**overrides: Any) -> dict[str, Any]:
    request: dict[str, Any] = {
        "amount_cents": 10_000,
        "currency": "usd",
        "customer_id": "cus_1",
        "payment_method_id": "pm_1",
        "idempotency_key": "autopay:k",
        "metadata": {"invoice_id": "inv-a", "source": "autopay"},
    }
    request.update(overrides)
    return request


def _gateway() -> FakeStripeGateway:
    gw = FakeStripeGateway()
    gw.seed_saved_card(
        academy_id="acad", parent_id="par-1", customer_id="cus_1", payment_method_id="pm_1"
    )
    return gw


async def test_the_same_request_replays_the_first_payment_intent() -> None:
    gw = _gateway()
    first = await gw.create_off_session_payment_intent(**_request())
    assert await gw.create_off_session_payment_intent(**_request()) == first
    assert len(gw.off_session_payment_intents) == 1


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"amount_cents": 9_800}, id="amount"),
        pytest.param({"metadata": {"invoice_id": "inv-a", "source": "admin"}}, id="metadata"),
        pytest.param({"payment_method_id": "pm_2"}, id="payment-method"),
        pytest.param({"currency": "cad"}, id="currency"),
    ],
)
async def test_the_same_key_with_any_other_parameter_is_refused(overrides: dict) -> None:
    gw = _gateway()
    await gw.create_off_session_payment_intent(**_request())
    with pytest.raises(StripeIdempotencyConflict):
        await gw.create_off_session_payment_intent(**_request(**overrides))
    assert len(gw.off_session_payment_intents) == 1


async def test_a_forgotten_key_charges_again() -> None:
    gw = _gateway()
    await gw.create_off_session_payment_intent(**_request())
    gw.expire_idempotency_keys()
    await gw.create_off_session_payment_intent(**_request(amount_cents=9_800))
    assert len(gw.off_session_payment_intents) == 2
