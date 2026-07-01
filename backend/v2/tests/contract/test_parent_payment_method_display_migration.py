import importlib
from datetime import UTC, datetime

import pytest

pytestmark = pytest.mark.asyncio


async def test_0144_runs_after_0142_already_recorded(db, acad) -> None:
    migration_0142 = importlib.import_module("backend.v2.migrations.0142_ach_lifecycle")
    runner = importlib.import_module("backend.v2.migrations.runner")

    await migration_0142.up(db)
    for module in runner._discover_migrations():
        if module.version == "0144_parent_payment_method_display":
            continue
        await db["v2_migrations"].insert_one(
            {"version": module.version, "applied_at": datetime.now(UTC)}
        )

    applied = await runner.run_pending_migrations(db)

    assert applied == ["0144_parent_payment_method_display"]
    now = datetime.now(UTC)
    await db["parent_billing_customers"].insert_one(
        {
            "academy_id": acad,
            "parent_id": "parent-display",
            "stripe_customer_id": "cus_display",
            "default_payment_method_id": "pm_bank",
            "payment_method_type": "us_bank_account",
            "payment_method_label": "Stripe Test Bank",
            "payment_method_last4": "6789",
            "primary_payment_method_id": "pm_bank",
            "primary_payment_method_type": "us_bank_account",
            "primary_payment_method_label": "Stripe Test Bank",
            "primary_payment_method_last4": "6789",
            "primary_setup_status": "active",
            "autopay_payment_methods": [
                {
                    "role": "primary",
                    "stripe_payment_method_id": "pm_bank",
                    "payment_method_type": "us_bank_account",
                    "payment_method_label": "Stripe Test Bank",
                    "payment_method_last4": "6789",
                    "setup_intent_id": "seti_bank",
                    "setup_status": "active",
                    "updated_at": now,
                }
            ],
            "created_at": now,
            "updated_at": now,
        }
    )

    assert (
        await db["parent_billing_customers"].count_documents(
            {"academy_id": acad, "parent_id": "parent-display"}
        )
        == 1
    )
