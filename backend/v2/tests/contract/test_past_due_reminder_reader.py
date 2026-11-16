"""The reminder sweep's Mongo reader flags invoices on active autopay (L1 should-fix 7)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from backend.v2.composition.dues_reminders import compose_dues_reminders


async def _unused(*_: Any) -> Any:
    raise AssertionError("not used by the reader")


@pytest.mark.asyncio
async def test_reader_flags_invoices_whose_enrollment_is_on_active_autopay(db, acad) -> None:
    due = datetime(2026, 9, 20, tzinfo=UTC)
    for invoice_id, enrollment_id, autopay in (
        ("inv-auto", "enr-auto", "active"),
        ("inv-paused", "enr-paused", "paused"),
        ("inv-manual", None, None),
    ):
        await db["invoices"].insert_one(
            {
                "academy_id": acad,
                "invoice_id": invoice_id,
                "parent_id": "parent-1",
                "enrollment_id": enrollment_id,
                "period": "2026-09",
                "status": "open",
                "balance_due_cents": 5000,
                "due_date": due,
            }
        )
        if enrollment_id:
            await db["student_billing_enrollments"].insert_one(
                {
                    "academy_id": acad,
                    "enrollment_id": enrollment_id,
                    "autopay_enrollment_status": autopay,
                }
            )
    bundle = compose_dues_reminders(
        db,
        academies=None,
        users=None,
        email_sender=None,
        email_sender_is_real=False,
        ledger=None,
        billing_counters=None,
        billing_settings=None,
        parent_payments_link=_unused,
        list_dues_followup=_unused,
        generate_invoice_artifact=_unused,
    )

    rows = await bundle.send_past_due_reminders._invoices.list_past_due(
        due_from=date(2026, 9, 20), due_to=date(2026, 9, 20)
    )

    assert {row.invoice_id: row.autopay_active for row in rows} == {
        "inv-auto": True,
        "inv-paused": False,
        "inv-manual": False,
    }


@pytest.mark.asyncio
async def test_bank_returns_to_review_counts_recent_families(real_db, acad) -> None:
    """Fix round 2: partial and unreconciled returns in the last 30 days, by family."""
    now = datetime.now(UTC)
    for parent_id, code, age_days in (
        ("parent-a", "unsupported_partial_ach_return", 1),
        ("parent-a", "unreconciled_payment_return", 2),
        ("parent-b", "unreconciled_payment_return", 3),
        ("parent-c", "unreconciled_payment_return", 40),
        ("parent-d", "card_declined", 1),
    ):
        await real_db["payment_attempts"].insert_one(
            {
                "attempt_id": f"att-{parent_id}-{age_days}",
                "academy_id": acad,
                "invoice_id": f"inv-{parent_id}-{age_days}",
                "parent_id": parent_id,
                "amount_cents": 5000,
                "currency": "usd",
                "status": "failed",
                "failure_code": code,
                "created_at": now - timedelta(days=age_days),
            }
        )
    bundle = compose_dues_reminders(
        real_db,
        academies=None,
        users=None,
        email_sender=None,
        email_sender_is_real=False,
        ledger=None,
        billing_counters=None,
        billing_settings=None,
        parent_payments_link=_unused,
        list_dues_followup=_unused,
        generate_invoice_artifact=_unused,
    )

    counts = await bundle.count_dunning_alerts()

    assert counts["bank_returns_to_review"] == 2
