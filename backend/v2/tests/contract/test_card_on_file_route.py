"""Card-on-file reads count only a card on the account autopay charges (#981).

Since direct charges a parent's card lives on one Stripe account. A connected
academy with a legacy PLATFORM card must not show "card on file": autopay
would refuse it with no_saved_payment_method.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.contexts.billing.domain.charge_route import ChargeRoute
from backend.v2.contexts.billing.infrastructure.mongo_parent_billing_customer_repo import (
    MongoParentBillingCustomerRepository,
)

NOW = datetime(2026, 11, 15, 12, tzinfo=UTC)
ACCT = "acct_route"


async def _card(db, acad: str, parent_id: str, account: str | None) -> None:
    doc = {
        "academy_id": acad,
        "parent_id": parent_id,
        "stripe_customer_id": f"cus_{parent_id}",
        "default_payment_method_id": f"pm_{parent_id}",
        "payment_method_label": "Visa",
        "payment_method_last4": "4242",
    }
    if account:
        doc["stripe_account_id"] = account
    await db["parent_billing_customers"].insert_one(doc)


async def _connect_ready(db, acad: str) -> None:
    await db["academy_connected_accounts"].insert_one(
        {
            "academy_id": acad,
            "stripe_account_id": ACCT,
            "status": "active",
            "charges_enabled": True,
            "fees_collector": "stripe",
            "losses_collector": "stripe",
            "payouts_enabled": True,
            "details_submitted": True,
            "capabilities": {},
            "created_at": NOW,
            "updated_at": NOW,
        }
    )


@pytest.mark.asyncio
async def test_connected_academy_ignores_a_legacy_platform_card(db, acad) -> None:
    await _connect_ready(db, acad)
    await _card(db, acad, "p-platform", None)
    await _card(db, acad, "p-direct", ACCT)
    repo = MongoParentBillingCustomerRepository(db)

    assert await repo.has_saved_card(parent_id="p-platform") is False
    assert await repo.has_saved_card(parent_id="p-direct") is True
    rows = {r["parent_id"]: r for r in await repo.list_academy_customers()}
    assert repo.display_payment_method(rows["p-platform"]) == (None, None)
    assert repo.display_payment_method(rows["p-direct"]) == ("Visa", "4242")
    assert "default_payment_method_id" not in rows["p-direct"]  # display-safe projection
    shown = await repo.get_display_customer(parent_id="p-platform")
    assert shown is not None and repo.display_payment_method(shown) == (None, None)


@pytest.mark.asyncio
async def test_house_academy_ignores_a_connected_card(db, acad) -> None:
    await db["billing_settings"].insert_one(
        {"academy_id": acad, "allow_platform_charge_fallback": True}
    )
    await _card(db, acad, "p-platform", None)
    await _card(db, acad, "p-direct", ACCT)
    repo = MongoParentBillingCustomerRepository(db)

    assert await repo.has_saved_card(parent_id="p-platform") is True
    assert await repo.has_saved_card(parent_id="p-direct") is False


@pytest.mark.asyncio
async def test_academy_that_cannot_take_payments_still_shows_cards(db, acad) -> None:
    # No connected account: the route banner already says nobody can pay.
    await _card(db, acad, "p-platform", None)
    assert await MongoParentBillingCustomerRepository(db).has_saved_card(parent_id="p-platform")


def test_holds_card_rule() -> None:
    assert ChargeRoute.platform().holds_card(None)
    assert not ChargeRoute.platform().holds_card(ACCT)
    assert ChargeRoute.connected(ACCT).holds_card(ACCT)
    assert not ChargeRoute.connected(ACCT).holds_card(None)
    assert not ChargeRoute.connected(ACCT).holds_card("acct_other")
    assert ChargeRoute(kind="account_not_ready").holds_card(None)
