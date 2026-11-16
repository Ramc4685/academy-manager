"""A capped ladder's daily recheck never charges an invoice twice, on a real mongod.

A charge that Stripe took but whose answer never reached us parks the rung as a
technical failure. After a day of those the ladder is capped and rechecked once
a day under the same idempotency key, but Stripe only remembers a key for 24h,
so the recheck would make a second PaymentIntent. Before such a charge the use
case searches Stripe for one that already covers the invoice(s) and settles it
instead. The Stripe double replays keys until ``expire_idempotency_keys``, the
way Stripe does, and its search sees the PaymentIntents it created.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from backend.v2.contexts.billing.infrastructure.fake_stripe_gateway import FakeStripeGateway
from backend.v2.tests.contract.test_family_combined_charge import (
    ACAD,
    NOW,
    PARENT,
    FakeOutbox,
    _charge,
    _invoice,
    _seed,
    _tick,
)

pytestmark = pytest.mark.asyncio

LATER = NOW + timedelta(hours=25)


class _CrashOnceStripe(FakeStripeGateway):
    """Stripe accepts the first PaymentIntent, but the answer never arrives."""

    def __init__(self) -> None:
        super().__init__()
        self.crash_once = True
        self.seed_saved_card(
            academy_id=ACAD, parent_id=PARENT, customer_id="cus_fam", payment_method_id="pm_fam"
        )

    async def create_off_session_payment_intent(self, **kwargs: Any) -> tuple[str, str, str | None]:
        result = await super().create_off_session_payment_intent(**kwargs)
        if self.crash_once:
            self.crash_once = False
            raise RuntimeError("connection reset after Stripe accepted the request")
        return result


async def _payments(real_db: Any) -> list[dict[str, Any]]:
    return await real_db["ledger_payments"].find({"academy_id": ACAD}).to_list(None)


async def test_capped_recheck_settles_the_lost_charge_instead_of_charging_again(
    real_db, acad
) -> None:
    await _seed(real_db, "inv-a")
    stripe = _CrashOnceStripe()

    first = await _tick(real_db, stripe, FakeOutbox())
    assert first.technical_failures == 1
    assert (await _invoice(real_db, "inv-a"))["status"] == "open"

    stripe.expire_idempotency_keys()  # a day later Stripe has forgotten the key
    result = await _tick(real_db, stripe, FakeOutbox(), at=LATER)

    assert result.succeeded == 1
    assert len(stripe.off_session_payment_intents) == 1  # no second charge
    (pi,) = stripe.off_session_payment_intents
    assert (await _invoice(real_db, "inv-a"))["status"] == "paid"
    assert [p["payment_id"] for p in await _payments(real_db)] == [f"ledger-pay-autopay:{pi['id']}"]


async def test_capped_family_recheck_settles_the_lost_family_charge(real_db, acad) -> None:
    await _seed(real_db, "inv-a")
    await _seed(real_db, "inv-b", cents=8_000)
    stripe = _CrashOnceStripe()

    await _tick(real_db, stripe, FakeOutbox())
    stripe.expire_idempotency_keys()
    result = await _tick(real_db, stripe, FakeOutbox(), at=LATER)

    assert result.succeeded == 2
    assert len(stripe.off_session_payment_intents) == 1
    (pi,) = stripe.off_session_payment_intents
    assert pi["amount_cents"] == 18_000
    for invoice_id in ("inv-a", "inv-b"):
        assert (await _invoice(real_db, invoice_id))["status"] == "paid"
    allocations = await real_db["payment_allocations"].find({"academy_id": ACAD}).to_list(None)
    assert sorted((a["invoice_id"], a["amount_cents"]) for a in allocations) == [
        ("inv-a", 10_000),
        ("inv-b", 8_000),
    ]
    assert len(await _payments(real_db)) == 1


async def test_a_processing_debit_found_on_recheck_parks_without_charging(real_db, acad) -> None:
    await _seed(real_db, "inv-a")
    stripe = _CrashOnceStripe()
    stripe.crash_once = False
    stripe.payment_intents.append(
        {
            "id": "pi_ach_settling",
            "status": "processing",
            "amount": 10_000,
            "currency": "usd",
            "metadata": {"academy_id": ACAD, "parent_id": PARENT, "invoice_id": "inv-a"},
        }
    )

    result = await _charge(real_db, stripe).execute("inv-a", check_existing=True)

    assert result.processing and not result.success
    assert stripe.off_session_payment_intents == []
    attempts = await real_db["payment_attempts"].find({"invoice_id": "inv-a"}).to_list(None)
    assert [(a["status"], a["idempotency_key"]) for a in attempts] == [
        ("processing", "autopay-processing:inv-a:pi_ach_settling")
    ]
    assert await _payments(real_db) == []


async def test_recheck_does_not_charge_when_stripe_cannot_be_searched(real_db, acad) -> None:
    await _seed(real_db, "inv-a")
    stripe = _CrashOnceStripe()

    async def _down(**_: Any) -> list[dict[str, Any]]:
        raise ValueError("Stripe PaymentIntent search failed: api down")

    stripe.search_app_owned_payment_intents = _down  # type: ignore[method-assign]

    result = await _charge(real_db, stripe).execute("inv-a", check_existing=True)

    assert result.decline_code == "stripe_unavailable"
    assert stripe.off_session_payment_intents == []
