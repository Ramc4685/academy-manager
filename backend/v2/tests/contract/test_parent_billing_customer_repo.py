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


async def test_default_payment_method_persists_safe_display_details(db, acad) -> None:
    repo = MongoParentBillingCustomerRepository(db)
    now = datetime(2026, 7, 1, tzinfo=UTC)

    await repo.set_default_payment_method(
        parent_id="parent-1",
        stripe_customer_id="cus_parent",
        stripe_payment_method_id="pm_bank",
        payment_method_type="us_bank_account",
        stripe_mandate_id="mandate_bank",
        setup_intent_id="seti_bank",
        checkout_session_id="cs_bank",
        completed_at=now,
        setup_status="active",
        payment_method_role="primary",
        payment_method_label="Stripe Test Bank",
        payment_method_last4="6789",
    )

    doc = await db["parent_billing_customers"].find_one(
        {"academy_id": acad, "parent_id": "parent-1"}
    )
    assert doc["primary_payment_method_label"] == "Stripe Test Bank"
    assert doc["primary_payment_method_last4"] == "6789"
    assert doc["payment_method_label"] == "Stripe Test Bank"
    assert doc["payment_method_last4"] == "6789"
    method = doc["autopay_payment_methods"][0]
    assert method["payment_method_label"] == "Stripe Test Bank"
    assert method["payment_method_last4"] == "6789"


async def test_replacing_method_without_display_details_clears_old_label_and_last4(
    db, acad
) -> None:
    repo = MongoParentBillingCustomerRepository(db)
    now = datetime(2026, 7, 1, tzinfo=UTC)
    await db["parent_billing_customers"].insert_one(
        {
            "academy_id": acad,
            "parent_id": "parent-1",
            "stripe_customer_id": "cus_parent",
            "default_payment_method_id": "pm_old_card",
            "payment_method_type": "card",
            "payment_method_label": "Visa",
            "payment_method_last4": "4242",
            "primary_payment_method_id": "pm_old_card",
            "primary_payment_method_type": "card",
            "primary_payment_method_label": "Visa",
            "primary_payment_method_last4": "4242",
            "primary_setup_status": "active",
            "autopay_payment_methods": [
                {
                    "role": "primary",
                    "stripe_payment_method_id": "pm_old_card",
                    "payment_method_type": "card",
                    "payment_method_label": "Visa",
                    "payment_method_last4": "4242",
                    "setup_intent_id": "seti_old",
                    "setup_status": "active",
                    "updated_at": now,
                }
            ],
            "created_at": now,
            "updated_at": now,
        }
    )

    await repo.set_default_payment_method(
        parent_id="parent-1",
        stripe_customer_id="cus_parent",
        stripe_payment_method_id="pm_new",
        payment_method_type="card",
        stripe_mandate_id=None,
        setup_intent_id="seti_new",
        checkout_session_id=None,
        completed_at=now,
        setup_status="active",
        payment_method_role="primary",
        payment_method_label=None,
        payment_method_last4=None,
    )
    await repo.promote_payment_method_to_default(
        parent_id="parent-1",
        stripe_payment_method_id="pm_new",
        payment_method_type="card",
        stripe_mandate_id=None,
        payment_method_label=None,
        payment_method_last4=None,
    )

    doc = await db["parent_billing_customers"].find_one(
        {"academy_id": acad, "parent_id": "parent-1"}
    )
    assert doc["primary_payment_method_id"] == "pm_new"
    assert doc["default_payment_method_id"] == "pm_new"
    assert "primary_payment_method_label" not in doc
    assert "primary_payment_method_last4" not in doc
    assert "payment_method_label" not in doc
    assert "payment_method_last4" not in doc
    method = doc["autopay_payment_methods"][0]
    assert method["stripe_payment_method_id"] == "pm_new"
    assert "payment_method_label" not in method
    assert "payment_method_last4" not in method


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


@pytest.mark.parametrize("shape", ["top_level", "primary", "nested"])
async def test_saved_card_detection_supports_all_compatible_projection_shapes(
    db, acad, shape: str
) -> None:
    repo = MongoParentBillingCustomerRepository(db)
    doc: dict[str, object] = {
        "academy_id": acad,
        "parent_id": f"parent-{shape}",
        "stripe_customer_id": f"cus-{shape}",
    }
    if shape == "top_level":
        doc.update(payment_method_label="Visa", payment_method_last4="4242")
    elif shape == "primary":
        doc.update(
            primary_payment_method_label="Mastercard",
            primary_payment_method_last4="4444",
            primary_setup_status="active",
        )
    else:
        doc["autopay_payment_methods"] = [
            {
                "role": "primary",
                "setup_status": "active",
                "payment_method_label": "Bank account",
                "payment_method_last4": "6789",
            }
        ]
    await db["parent_billing_customers"].insert_one(doc)

    assert await repo.has_saved_card(parent_id=f"parent-{shape}") is True
    listed = {
        row["parent_id"]: repo.display_payment_method(row)
        for row in await repo.list_academy_customers()
    }
    assert listed[f"parent-{shape}"][1] is not None


async def test_pending_primary_method_is_not_chargeable(db, acad) -> None:
    repo = MongoParentBillingCustomerRepository(db)
    await db["parent_billing_customers"].insert_one(
        {
            "academy_id": acad,
            "parent_id": "parent-pending",
            "primary_payment_method_label": "Pending bank",
            "primary_payment_method_last4": "6789",
            "primary_setup_status": "verification_required",
        }
    )

    assert await repo.has_saved_card(parent_id="parent-pending") is False
