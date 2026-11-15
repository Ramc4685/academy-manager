"""A saved bank Stripe has blocked, or whose mandate went inactive, stops being
chargeable until the parent saves a new method (L1 A4-8)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.contexts.billing.infrastructure.mongo_parent_billing_customer_repo import (
    MongoParentBillingCustomerRepository,
)

NOW = datetime(2026, 11, 15, 12, tzinfo=UTC)


async def _seed(db, acad: str, *, parent_id: str, pm: str) -> None:
    await db["parent_billing_customers"].insert_one(
        {
            "academy_id": acad,
            "parent_id": parent_id,
            "stripe_customer_id": f"cus_{parent_id}",
            "default_payment_method_id": pm,
            "primary_payment_method_id": pm,
            "primary_setup_status": "active",
            "payment_method_label": "Bank",
            "payment_method_last4": "6789",
        }
    )


@pytest.mark.asyncio
async def test_blocked_method_is_not_chargeable_until_a_new_one_is_saved(db, acad) -> None:
    repo = MongoParentBillingCustomerRepository(db)
    await _seed(db, acad, parent_id="p1", pm="pm_bank")
    await _seed(db, acad, parent_id="p2", pm="pm_other")

    flagged = await repo.flag_payment_method_blocked(
        payment_method_id="pm_bank", reason="mandate_inactive", at=NOW
    )

    assert flagged == 1
    assert await repo.get_saved_payment_method(parent_id="p1", stripe_account_id=None) is None
    assert await repo.payment_method_blocked(parent_id="p1") is True
    assert await repo.has_saved_card(parent_id="p1") is False
    assert await repo.get_saved_payment_method(parent_id="p2", stripe_account_id=None) == (
        "cus_p2",
        "pm_other",
    )

    await db["parent_billing_customers"].update_one(
        {"parent_id": "p1"},
        {"$set": {"default_payment_method_id": "pm_new", "primary_payment_method_id": "pm_new"}},
    )
    assert await repo.get_saved_payment_method(parent_id="p1", stripe_account_id=None) == (
        "cus_p1",
        "pm_new",
    )
    assert await repo.payment_method_blocked(parent_id="p1") is False


@pytest.mark.asyncio
async def test_flag_stays_inside_the_academy(db, acad) -> None:
    repo = MongoParentBillingCustomerRepository(db)
    await _seed(db, "other-academy", parent_id="p1", pm="pm_bank")

    assert (
        await repo.flag_payment_method_blocked(payment_method_id="pm_bank", reason="x", at=NOW) == 0
    )
