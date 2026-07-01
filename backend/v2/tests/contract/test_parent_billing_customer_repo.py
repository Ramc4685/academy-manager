from datetime import UTC, datetime

import pytest

from backend.v2.contexts.billing.infrastructure.mongo_parent_billing_customer_repo import (
    MongoParentBillingCustomerRepository,
)

pytestmark = pytest.mark.asyncio


async def test_pending_primary_ach_does_not_replace_chargeable_default(db, acad) -> None:
    repo = MongoParentBillingCustomerRepository(db)
    now = datetime(2026, 7, 1, tzinfo=UTC)
    await db["parent_billing_customers"].insert_one(
        {
            "academy_id": acad,
            "parent_id": "parent-1",
            "stripe_customer_id": "cus_parent",
            "default_payment_method_id": "pm_existing_card",
            "payment_method_type": "card",
            "stripe_mandate_id": "mandate_existing",
            "created_at": now,
            "updated_at": now,
        }
    )

    await repo.set_default_payment_method(
        parent_id="parent-1",
        stripe_customer_id="cus_parent",
        stripe_payment_method_id="pm_pending_bank",
        payment_method_type="us_bank_account",
        stripe_mandate_id="mandate_pending",
        setup_intent_id="seti_pending_bank",
        checkout_session_id="cs_pending_bank",
        completed_at=now,
        setup_status="verification_required",
        payment_method_role="primary",
    )

    doc = await db["parent_billing_customers"].find_one(
        {"academy_id": acad, "parent_id": "parent-1"}
    )
    assert doc["primary_payment_method_id"] == "pm_pending_bank"
    assert doc["primary_payment_method_type"] == "us_bank_account"
    assert doc["primary_setup_status"] == "verification_required"
    assert doc["primary_stripe_mandate_id"] == "mandate_pending"
    assert doc["default_payment_method_id"] == "pm_existing_card"
    assert doc["payment_method_type"] == "card"
    assert doc["stripe_mandate_id"] == "mandate_existing"
    method = doc["autopay_payment_methods"][0]
    assert method | {"updated_at": None} == {
        "role": "primary",
        "stripe_payment_method_id": "pm_pending_bank",
        "payment_method_type": "us_bank_account",
        "setup_intent_id": "seti_pending_bank",
        "setup_status": "verification_required",
        "updated_at": None,
        "stripe_mandate_id": "mandate_pending",
        "checkout_session_id": "cs_pending_bank",
    }
    assert method["updated_at"] == now.replace(tzinfo=None)


async def test_active_primary_setup_waits_for_explicit_default_promotion(db, acad) -> None:
    repo = MongoParentBillingCustomerRepository(db)
    now = datetime(2026, 7, 1, tzinfo=UTC)

    await db["parent_billing_customers"].insert_one(
        {
            "academy_id": acad,
            "parent_id": "parent-1",
            "stripe_customer_id": "cus_parent",
            "default_payment_method_id": "pm_existing_card",
            "payment_method_type": "card",
            "stripe_mandate_id": "mandate_existing",
            "created_at": now,
            "updated_at": now,
        }
    )
    await repo.set_default_payment_method(
        parent_id="parent-1",
        stripe_customer_id="cus_parent",
        stripe_payment_method_id="pm_active_bank",
        payment_method_type="us_bank_account",
        stripe_mandate_id="mandate_active",
        setup_intent_id="seti_active_bank",
        checkout_session_id=None,
        completed_at=now,
        setup_status="active",
        payment_method_role="primary",
    )

    doc = await db["parent_billing_customers"].find_one(
        {"academy_id": acad, "parent_id": "parent-1"}
    )
    assert doc["default_payment_method_id"] == "pm_existing_card"
    assert doc["payment_method_type"] == "card"
    assert doc["stripe_mandate_id"] == "mandate_existing"
    assert doc["primary_payment_method_id"] == "pm_active_bank"
    assert doc["primary_setup_status"] == "active"

    await repo.promote_payment_method_to_default(
        parent_id="parent-1",
        stripe_payment_method_id="pm_active_bank",
        payment_method_type="us_bank_account",
        stripe_mandate_id="mandate_active",
    )

    doc = await db["parent_billing_customers"].find_one(
        {"academy_id": acad, "parent_id": "parent-1"}
    )
    assert doc["default_payment_method_id"] == "pm_active_bank"
    assert doc["payment_method_type"] == "us_bank_account"
    assert doc["stripe_mandate_id"] == "mandate_active"
    assert doc["primary_payment_method_id"] == "pm_active_bank"
    assert doc["primary_setup_status"] == "active"
