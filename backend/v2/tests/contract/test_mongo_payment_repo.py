"""Mongo payment repository contract tests."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.v2.contexts.billing.domain.models import CreditLedgerEntry, Payment
from backend.v2.contexts.billing.infrastructure.mongo_credit_ledger_repo import (
    MongoCreditLedgerRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_payment_repo import MongoPaymentRepository


@pytest.mark.asyncio
async def test_list_for_parent_maps_domain_payments(db, acad) -> None:
    repo = MongoPaymentRepository(db)
    now = datetime.now(timezone.utc)
    await repo.save(
        Payment(
            payment_id="pay-parent-1",
            academy_id=acad,
            parent_id="parent-1",
            session_id="session-1",
            amount_cents=2500,
            status="pending",
            created_at=now,
            updated_at=now,
        )
    )

    rows = await repo.list_for_parent("parent-1")

    assert [row.payment_id for row in rows] == ["pay-parent-1"]
    assert rows[0].amount_cents == 2500


@pytest.mark.asyncio
async def test_generate_monthly_prorates_first_period_and_stores_snapshot(db, acad) -> None:
    repo = MongoPaymentRepository(
        db,
        clock=lambda: datetime(2026, 5, 18, 22, 0, tzinfo=timezone.utc),
    )
    await db["sessions"].insert_one(
        {
            "academy_id": acad,
            "session_id": "sess-prorate",
            "name": "Junior Badminton",
            "title": "Junior Badminton",
            "coach_id": "coach-1",
            "location": "Court 1",
            "start_date": "2026-05-01",
            "end_date": "2026-05-29",
            "days_of_week": ["Mon", "Fri"],
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
            "student_id": "student-1",
            "parent_id": "parent-1",
            "full_name": "A Student",
        }
    )
    await db["enrollments"].insert_one(
        {
            "academy_id": acad,
            "enrollment_id": "enroll-1",
            "session_id": "sess-prorate",
            "student_id": "student-1",
            "parent_id": "parent-1",
            "status": "active",
            "billing_type": "standard",
            "billing_start_at": datetime(2026, 5, 18, 15, 0, tzinfo=timezone.utc),
            "created_at": datetime(2026, 5, 18, 15, 0, tzinfo=timezone.utc),
        }
    )

    result = await repo.generate_monthly_payments("2026-05")

    assert result.created == 1
    payment = await db["payments"].find_one({"academy_id": acad, "enrollment_id": "enroll-1"})
    assert payment is not None
    assert payment["amount_cents"] == 3_333
    assert payment["calculation_snapshot_id"]
    assert payment["invoice_key_id"]
    snapshot = await db["billing_calculation_snapshots"].find_one(
        {"snapshot_id": payment["calculation_snapshot_id"]}
    )
    assert snapshot is not None
    assert snapshot["status"] == "CONSUMED"
    assert snapshot["total_eligible_classes"] == 9
    assert snapshot["billable_remaining_classes"] == 3
    assert snapshot["excluded_occurrences"]["sess-prorate:2026-05-18:18:00"] == "SAME_DAY_CUTOFF"


@pytest.mark.asyncio
async def test_generate_monthly_applies_approved_account_credit(db, acad) -> None:
    credits = MongoCreditLedgerRepository(db)
    repo = MongoPaymentRepository(
        db,
        clock=lambda: datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
        credit_ledger=credits,
    )
    now = datetime(2026, 5, 20, tzinfo=timezone.utc)
    await credits.create(
        CreditLedgerEntry(
            credit_id="credit-1",
            academy_id=acad,
            parent_id="parent-1",
            student_id="student-1",
            enrollment_id="enroll-1",
            type="EARLY_WITHDRAWAL_CREDIT",
            status="APPROVED",
            amount_cents=3750,
            remaining_amount_cents=3750,
            currency="usd",
            reason="withdrawal",
            calculation_snapshot_id="snap-credit",
            created_at=now,
            updated_at=now,
        )
    )
    await db["sessions"].insert_one(
        {
            "academy_id": acad,
            "session_id": "sess-credit",
            "name": "Junior Badminton",
            "title": "Junior Badminton",
            "coach_id": "coach-1",
            "location": "Court 1",
            "start_date": "2026-06-01",
            "end_date": "2026-06-30",
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
            "student_id": "student-1",
            "parent_id": "parent-1",
            "full_name": "A Student",
        }
    )
    await db["enrollments"].insert_one(
        {
            "academy_id": acad,
            "enrollment_id": "enroll-1",
            "session_id": "sess-credit",
            "student_id": "student-1",
            "parent_id": "parent-1",
            "status": "active",
            "billing_type": "standard",
            "billing_start_at": datetime(2026, 5, 1, tzinfo=timezone.utc),
            "created_at": datetime(2026, 5, 1, tzinfo=timezone.utc),
        }
    )

    result = await repo.generate_monthly_payments("2026-06")

    assert result.created == 1
    payment = await db["payments"].find_one({"academy_id": acad, "enrollment_id": "enroll-1"})
    assert payment is not None
    assert payment["gross_amount_cents"] == 10_000
    assert payment["applied_credit_cents"] == 3750
    assert payment["amount_cents"] == 6250
    assert payment["calculation_snapshot_id"]
    assert await credits.balance_for_parent("parent-1") == 0
