"""FakeStripeGateway models Stripe's account dimension.

Stripe objects are account-scoped: an id minted on one account is
``resource_missing`` on every other. A permissive fake that ignored this is
exactly how cross-account money bugs pass tests, so the fake must refuse.
"""

from __future__ import annotations

import pytest

from backend.v2.contexts.billing.application.ports import StripeResourceNotFound
from backend.v2.contexts.billing.infrastructure.fake_stripe_gateway import FakeStripeGateway

ACCT_A = "acct_a"
ACCT_B = "acct_b"


async def _setup(gw: FakeStripeGateway, stripe_account: str | None) -> str:
    checkout_id, _ = await gw.create_autopay_setup_checkout_session(
        parent_id="par-1",
        enrollment_id="enr-1",
        session_id="st-1",
        success_url="https://ok",
        cancel_url="https://cancel",
        metadata={"academy_id": "acad", "parent_id": "par-1"},
        stripe_account=stripe_account,
    )
    return checkout_id


async def test_checkout_session_is_invisible_on_another_account() -> None:
    gw = FakeStripeGateway()
    checkout_id = await _setup(gw, ACCT_A)

    session = await gw.retrieve_checkout_session(checkout_id, stripe_account=ACCT_A)
    assert session["customer"] == f"cus_fake_parent_{ACCT_A}"
    with pytest.raises(StripeResourceNotFound):
        await gw.retrieve_checkout_session(checkout_id)
    with pytest.raises(StripeResourceNotFound):
        await gw.retrieve_checkout_session(checkout_id, stripe_account=ACCT_B)
    with pytest.raises(StripeResourceNotFound):
        await gw.expire_checkout_session(checkout_id)


async def test_platform_objects_are_invisible_on_a_connected_account() -> None:
    gw = FakeStripeGateway()
    checkout_id = await _setup(gw, None)
    session = await gw.retrieve_checkout_session(checkout_id)
    setup_intent = await gw.retrieve_setup_intent(session["setup_intent"])

    with pytest.raises(StripeResourceNotFound):
        await gw.retrieve_setup_intent(session["setup_intent"], stripe_account=ACCT_A)
    with pytest.raises(StripeResourceNotFound):
        await gw.retrieve_payment_method(setup_intent["payment_method"], stripe_account=ACCT_A)
    with pytest.raises(StripeResourceNotFound):
        await gw.set_customer_default_payment_method(
            stripe_customer_id="cus_fake_parent",
            stripe_payment_method_id=setup_intent["payment_method"],
            metadata={},
            stripe_account=ACCT_A,
        )


async def test_unknown_id_on_a_connected_account_is_missing() -> None:
    gw = FakeStripeGateway()
    # Hand-written platform ids keep working (legacy tests)...
    assert (await gw.retrieve_payment_intent("pi_handwritten"))["id"] == "pi_handwritten"
    # ...but a connected account only knows objects created on it.
    with pytest.raises(StripeResourceNotFound):
        await gw.retrieve_payment_intent("pi_handwritten", stripe_account=ACCT_A)


async def test_saved_card_lookup_is_per_account() -> None:
    gw = FakeStripeGateway()
    gw.seed_saved_card(
        academy_id="acad",
        parent_id="par-1",
        customer_id="cus_a",
        payment_method_id="pm_a",
        stripe_account=ACCT_A,
    )
    assert await gw.get_default_payment_method(
        academy_id="acad", parent_id="par-1", stripe_account=ACCT_A
    ) == ("cus_a", "pm_a")
    assert await gw.get_default_payment_method(academy_id="acad", parent_id="par-1") is None
    assert (
        await gw.get_default_payment_method(
            academy_id="acad", parent_id="par-1", stripe_account=ACCT_B
        )
        is None
    )


async def test_off_session_charge_needs_customer_and_card_on_the_same_account() -> None:
    gw = FakeStripeGateway()
    gw.seed_saved_card(
        academy_id="acad",
        parent_id="par-1",
        customer_id="cus_plat",
        payment_method_id="pm_plat",
    )
    # A platform customer/card cannot be charged on a connected account.
    with pytest.raises(ValueError, match="No such customer"):
        await gw.create_off_session_payment_intent(
            amount_cents=100,
            currency="usd",
            customer_id="cus_plat",
            payment_method_id="pm_plat",
            idempotency_key="k",
            metadata={},
            stripe_account=ACCT_A,
        )
    pi_id, status, _ = await gw.create_off_session_payment_intent(
        amount_cents=100,
        currency="usd",
        customer_id="cus_plat",
        payment_method_id="pm_plat",
        idempotency_key="k",
        metadata={},
    )
    assert status == "succeeded"
    assert gw.account_of(pi_id) is None


async def test_refund_must_target_the_charge_account() -> None:
    gw = FakeStripeGateway()
    gw.seed_saved_card(
        academy_id="acad",
        parent_id="par-1",
        customer_id="cus_a",
        payment_method_id="pm_a",
        stripe_account=ACCT_A,
    )
    pi_id, _, _ = await gw.create_off_session_payment_intent(
        amount_cents=1000,
        currency="usd",
        customer_id="cus_a",
        payment_method_id="pm_a",
        idempotency_key="k",
        metadata={},
        stripe_account=ACCT_A,
    )
    with pytest.raises(StripeResourceNotFound):
        await gw.issue_refund(pi_id, 500, idempotency_key="r1")
    with pytest.raises(StripeResourceNotFound):
        await gw.issue_refund(pi_id, 500, idempotency_key="r1", stripe_account=ACCT_B)

    refund_id = await gw.issue_refund(pi_id, 500, idempotency_key="r1", stripe_account=ACCT_A)
    assert gw.refunds[-1]["stripe_account"] == ACCT_A
    # Idempotent replay on the same account returns the same refund.
    assert await gw.issue_refund(pi_id, 500, idempotency_key="r1", stripe_account=ACCT_A) == (
        refund_id
    )
    assert len(gw.refunds) == 1


async def test_invoice_checkout_idempotency_is_scoped_per_account() -> None:
    gw = FakeStripeGateway()
    kwargs = {
        "invoice_id": "inv-1",
        "amount_cents": 4100,
        "currency": "usd",
        "success_url": "https://ok",
        "cancel_url": "https://cancel",
        "metadata": {"academy_id": "acad", "parent_id": "par-1"},
        "idempotency_key": "invoice-checkout:inv-1:4100",
    }
    first, _ = await gw.create_invoice_checkout_session(**kwargs)
    replay, _ = await gw.create_invoice_checkout_session(**kwargs)
    other, _ = await gw.create_invoice_checkout_session(**kwargs, stripe_account=ACCT_A)
    assert first == replay
    assert other != first
    assert gw.account_of(other) == ACCT_A
    with pytest.raises(StripeResourceNotFound):
        await gw.retrieve_checkout_session(other)


async def test_destination_and_direct_at_once_is_refused() -> None:
    gw = FakeStripeGateway()
    with pytest.raises(ValueError, match="both"):
        await gw.create_checkout_session(
            parent_id="p",
            session_id="s",
            amount_cents=100,
            success_url="https://ok",
            cancel_url="https://cancel",
            metadata={},
            connected_account_id=ACCT_A,
            stripe_account=ACCT_A,
        )
