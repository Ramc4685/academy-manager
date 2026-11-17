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
            "latest_charge": {"id": "ch_ach", "refunded": False, "amount_refunded": 0},
            "metadata": {
                "academy_id": ACAD,
                "parent_id": PARENT,
                "invoice_id": "inv-a",
                "source": "autopay",
            },
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


async def _set_balance(real_db: Any, invoice_id: str, cents: int) -> None:
    await real_db["invoices"].update_one(
        {"academy_id": ACAD, "invoice_id": invoice_id},
        {"$set": {"balance_due_cents": cents, "total_cents": cents, "subtotal_cents": cents}},
    )


async def test_a_family_retry_with_a_changed_total_parks_instead_of_charging_again(
    real_db, acad
) -> None:
    """The family key carries no amount: a retry whose total moved reuses the key,
    Stripe refuses it (different params), and the group parks with no new charge."""
    await _seed(real_db, "inv-a")
    await _seed(real_db, "inv-b", cents=8_000)
    stripe = _CrashOnceStripe()
    scopes = {"inv-a": "r1", "inv-b": "r1"}
    charge = _charge(real_db, stripe)

    with pytest.raises(RuntimeError):
        await charge.execute_family(["inv-a", "inv-b"], charge_group_id="g1", retry_scopes=scopes)
    await _set_balance(real_db, "inv-b", 7_000)  # a credit landed between tries
    result = await charge.execute_family(
        ["inv-a", "inv-b"], charge_group_id="g1", retry_scopes=scopes
    )

    assert result.result is not None and result.result.decline_code == "stripe_unavailable"
    assert len(stripe.off_session_payment_intents) == 1
    (pi,) = stripe.off_session_payment_intents
    assert pi["idempotency_key"].startswith("autopay-family:")
    assert not pi["idempotency_key"].endswith(":18000")
    assert await _payments(real_db) == []


def _seed_pi(stripe: FakeStripeGateway, **overrides: Any) -> None:
    pi: dict[str, Any] = {
        "id": "pi_found",
        "status": "succeeded",
        "amount": 10_000,
        "currency": "usd",
        "latest_charge": {"id": "ch_found", "refunded": False, "amount_refunded": 0},
        "metadata": {
            "academy_id": ACAD,
            "parent_id": PARENT,
            "invoice_id": "inv-a",
            "source": "autopay",
        },
    }
    pi.update(overrides)
    stripe.payment_intents.append(pi)


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param(
            {"latest_charge": {"id": "ch_1", "refunded": True, "amount_refunded": 10_000}},
            id="refunded",
        ),
        pytest.param({"latest_charge": {"id": "ch_1", "disputed": True}}, id="disputed"),
        pytest.param({"amount": 4_000}, id="amount-differs"),
        pytest.param({"latest_charge": "ch_unexpanded"}, id="charge-not-expanded"),
        pytest.param(
            {
                "metadata": {
                    "academy_id": ACAD,
                    "parent_id": PARENT,
                    "invoice_id": "inv-a",
                    "source": "invoice_pay_link",
                }
            },
            id="checkout-payment",
        ),
    ],
)
async def test_a_found_charge_that_is_not_cleanly_this_one_parks_unpaid(
    real_db, acad, overrides: dict[str, Any]
) -> None:
    await _seed(real_db, "inv-a")
    stripe = _CrashOnceStripe()
    stripe.crash_once = False
    _seed_pi(stripe, **overrides)

    result = await _charge(real_db, stripe).execute("inv-a", check_existing=True)

    assert not result.success and not result.processing
    assert result.decline_code == "existing_charge_needs_review"
    assert stripe.off_session_payment_intents == []
    assert await _payments(real_db) == []
    assert (await _invoice(real_db, "inv-a"))["status"] == "open"


async def test_a_found_charge_that_leaves_a_balance_is_not_reported_paid(real_db, acad) -> None:
    await _seed(real_db, "inv-a")
    stripe = _CrashOnceStripe()
    stripe.crash_once = False
    _seed_pi(stripe)
    charge = _charge(real_db, stripe)
    real_get = charge._ledger.get_invoice
    reads = 0

    async def _get_invoice(invoice_id: str) -> Any:
        # The post-settle read sees a balance the allocation did not clear.
        nonlocal reads
        reads += 1
        invoice = await real_get(invoice_id)
        if reads > 2 and invoice is not None:
            return invoice.model_copy(update={"balance_due_cents": 2_500})
        return invoice

    charge._ledger.get_invoice = _get_invoice  # type: ignore[method-assign]
    result = await charge.execute("inv-a", check_existing=True)

    assert not result.success
    assert stripe.off_session_payment_intents == []


async def test_a_lost_charge_is_not_recharged_after_a_non_technical_park(real_db, acad) -> None:
    """A lost answer, then a no-card park (which clears the technical clock),
    then a new card a day later: the retry must still look for the first charge."""
    await _seed(real_db, "inv-a")
    stripe = _CrashOnceStripe()

    first = await _tick(real_db, stripe, FakeOutbox())
    assert first.technical_failures == 1
    assert len(stripe.off_session_payment_intents) == 1  # Stripe took the money

    stripe.saved_cards.clear()  # card removed in the Billing Portal
    await _tick(real_db, stripe, FakeOutbox(), at=NOW + timedelta(hours=1))
    state = await real_db["dunning_states"].find_one({"invoice_id": "inv-a"})
    assert state["suppression_reason"] == "no_saved_payment_method"
    assert state.get("technical_parked_since") is None
    assert state["parked_since"] is not None  # survives the second park and re-claim

    stripe.seed_saved_card(
        academy_id=ACAD, parent_id=PARENT, customer_id="cus_fam", payment_method_id="pm_new"
    )
    stripe.expire_idempotency_keys()
    await _tick(real_db, stripe, FakeOutbox(), at=NOW + timedelta(hours=25))

    assert len(stripe.off_session_payment_intents) == 1
    assert (await _invoice(real_db, "inv-a"))["status"] == "paid"


async def test_a_refunded_lost_charge_parks_once_for_review_and_is_not_rechecked(
    real_db, acad
) -> None:
    """The lost charge was refunded in Stripe before the capped recheck found it. It
    must not settle, must not be charged again, and must not re-park every day: the
    rung parks once for a person to review and the ladder stops asking Stripe."""
    await _seed(real_db, "inv-a")
    stripe = _CrashOnceStripe()
    await _tick(real_db, stripe, FakeOutbox())
    (pi,) = stripe.off_session_payment_intents
    stripe._payment_intents_by_id[pi["id"]]["latest_charge"].update(
        {"refunded": True, "amount_refunded": 10_000}
    )
    searches = 0
    real_search = stripe.search_app_owned_payment_intents

    async def _search(**kwargs: Any) -> list[dict[str, Any]]:
        nonlocal searches
        searches += 1
        return await real_search(**kwargs)

    stripe.search_app_owned_payment_intents = _search  # type: ignore[method-assign]
    stripe.expire_idempotency_keys()

    result = await _tick(real_db, stripe, FakeOutbox(), at=LATER)
    state = await real_db["dunning_states"].find_one({"invoice_id": "inv-a"})
    assert state["suppression_reason"] == "existing_charge_needs_review"
    assert result.technical_failures == 1  # counted once, for the admin
    assert searches == 1

    for days in (2, 3):
        later = await _tick(real_db, stripe, FakeOutbox(), at=NOW + timedelta(days=days))
        assert later.parked == 0 and later.technical_failures == 0
    after = await real_db["dunning_states"].find_one({"invoice_id": "inv-a"})
    assert after["suppressed_at"] == state["suppressed_at"]
    assert searches == 1
    assert len(stripe.off_session_payment_intents) == 1
    assert await _payments(real_db) == []
    assert (await _invoice(real_db, "inv-a"))["status"] == "open"
