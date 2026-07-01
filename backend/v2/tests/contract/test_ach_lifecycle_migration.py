import importlib
from datetime import UTC, datetime

import pytest

pytestmark = pytest.mark.asyncio


async def test_0142_parent_payment_method_projection_is_backward_compatible(db, acad) -> None:
    migration = importlib.import_module("backend.v2.migrations.0142_ach_lifecycle")

    await migration.up(db)

    now = datetime.now(UTC)
    await db["parent_billing_customers"].insert_one(
        {
            "academy_id": acad,
            "parent_id": "parent-old",
            "stripe_customer_id": "cus_old",
            "default_payment_method_id": "pm_old",
            "payment_method_type": "card",
            "created_at": now,
            "updated_at": now,
        }
    )
    await db["parent_billing_customers"].insert_one(
        {
            "academy_id": acad,
            "parent_id": "parent-new",
            "stripe_customer_id": "cus_new",
            "default_payment_method_id": "pm_bank",
            "payment_method_type": "us_bank_account",
            "primary_payment_method_id": "pm_bank",
            "primary_payment_method_type": "us_bank_account",
            "primary_setup_status": "verification_required",
            "primary_stripe_mandate_id": "mandate_bank",
            "fallback_payment_method_id": "pm_card",
            "fallback_payment_method_type": "card",
            "fallback_setup_status": "active",
            "autopay_payment_methods": [
                {
                    "role": "primary",
                    "stripe_payment_method_id": "pm_bank",
                    "payment_method_type": "us_bank_account",
                    "stripe_mandate_id": "mandate_bank",
                    "setup_intent_id": "seti_bank",
                    "setup_status": "verification_required",
                    "updated_at": now,
                },
                {
                    "role": "fallback",
                    "stripe_payment_method_id": "pm_card",
                    "payment_method_type": "card",
                    "setup_intent_id": "seti_card",
                    "setup_status": "active",
                    "updated_at": now,
                },
            ],
            "created_at": now,
            "updated_at": now,
        }
    )

    assert await db["parent_billing_customers"].count_documents({"academy_id": acad}) == 2


async def test_0142_creates_payment_allocation_reversal_indexes(db, acad) -> None:
    migration = importlib.import_module("backend.v2.migrations.0142_ach_lifecycle")

    await migration.up(db)

    names = {index["name"] async for index in db["payment_allocation_reversals"].list_indexes()}
    assert "uniq_payment_allocation_reversal_idempotency" in names
    assert "payment_allocation_reversal_payment_lookup" in names
