"""The monthly generation run mints a human invoice number (#659).

Before this, ``mint_invoice_number`` was wired into the autopay, proration and
ad-hoc-line paths only — never into the batch that produces the vast majority
of invoices — so the "number" parents saw in the portal and in email was the
internal slug ``inv-monthly-<enrollment>-<period>``.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

import pytest

from backend.v2.contexts.billing.infrastructure.mongo_billing_ledger_repo import (
    MongoBillingLedgerRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_payment_repo import MongoPaymentRepository

pytestmark = pytest.mark.asyncio

NUMBER_RE = re.compile(r"^[A-Z0-9]+-\d{4}-\d{2}-\d{4,}$")


async def _seed(db, acad: str, *, enrollment_id: str, student_id: str) -> None:
    await db["sessions"].insert_one(
        {
            "academy_id": acad,
            "session_id": "sess-1",
            "name": "Junior Badminton",
            "title": "Junior Badminton",
            "coach_id": "coach-1",
            "location": "Court 1",
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
            "days_of_week": ["Mon", "Wed"],
            "start_time": "18:00",
            "end_time": "19:00",
            "monthly_price_cents": 10_000,
            "capacity": 8,
            "status": "active",
        }
    )
    await db["students"].insert_one(
        {
            "academy_id": acad,
            "student_id": student_id,
            "parent_id": "parent-1",
            "full_name": "Arjun Kumar",
        }
    )
    await db["enrollments"].insert_one(
        {
            "academy_id": acad,
            "enrollment_id": enrollment_id,
            "session_id": "sess-1",
            "student_id": student_id,
            "parent_id": "parent-1",
            "status": "active",
            "billing_type": "standard",
            "billing_start_at": datetime(2025, 12, 1, 15, 0, tzinfo=UTC),
            "created_at": datetime(2025, 12, 1, 15, 0, tzinfo=UTC),
        }
    )


async def test_generated_monthly_invoice_gets_a_readable_number(db, acad) -> None:
    await _seed(db, acad, enrollment_id="enroll-1", student_id="student-1")
    repo = MongoPaymentRepository(
        db,
        clock=lambda: datetime(2026, 9, 1, 8, 0, tzinfo=UTC),
        ledger_repo=MongoBillingLedgerRepository(db),
    )

    result = await repo.generate_monthly_payments("2026-09")

    assert result.created == 1
    invoice = await db["invoices"].find_one({"academy_id": acad, "enrollment_id": "enroll-1"})
    assert invoice is not None
    number = invoice.get("invoice_number")
    assert number, "monthly generation must mint an invoice_number"
    assert NUMBER_RE.match(number), number
    # The tuition month is readable at a glance, and the internal id is untouched.
    assert "-2026-09-" in number
    assert invoice["invoice_id"] == "inv-monthly-enroll-1-2026-09"


async def test_invoice_numbers_are_unique_per_academy_period(db, acad) -> None:
    await _seed(db, acad, enrollment_id="enroll-1", student_id="student-1")
    await db["students"].insert_one(
        {
            "academy_id": acad,
            "student_id": "student-2",
            "parent_id": "parent-1",
            "full_name": "Meera Kumar",
        }
    )
    await db["enrollments"].insert_one(
        {
            "academy_id": acad,
            "enrollment_id": "enroll-2",
            "session_id": "sess-1",
            "student_id": "student-2",
            "parent_id": "parent-1",
            "status": "active",
            "billing_type": "standard",
            "billing_start_at": datetime(2025, 12, 1, 15, 0, tzinfo=UTC),
            "created_at": datetime(2025, 12, 1, 15, 0, tzinfo=UTC),
        }
    )
    repo = MongoPaymentRepository(
        db,
        clock=lambda: datetime(2026, 9, 1, 8, 0, tzinfo=UTC),
        ledger_repo=MongoBillingLedgerRepository(db),
    )

    result = await repo.generate_monthly_payments("2026-09")

    assert result.created == 2
    numbers = {
        doc["invoice_number"]
        async for doc in db["invoices"].find({"academy_id": acad, "period": "2026-09"})
    }
    assert len(numbers) == 2
