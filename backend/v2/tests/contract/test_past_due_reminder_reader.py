"""The reminder sweep's Mongo reader flags invoices on active autopay (L1 should-fix 7)."""

from __future__ import annotations

from datetime import UTC, date, datetime
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
