"""Mongo payment repository contract tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.contexts.billing.domain.models import CreditLedgerEntry, Payment
from backend.v2.contexts.billing.infrastructure.mongo_credit_ledger_repo import (
    MongoCreditLedgerRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_payment_repo import MongoPaymentRepository


@pytest.mark.asyncio
async def test_list_for_parent_maps_domain_payments(db, acad) -> None:
    repo = MongoPaymentRepository(db)
    now = datetime.now(UTC)
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
        clock=lambda: datetime(2026, 5, 18, 22, 0, tzinfo=UTC),
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
            "billing_start_at": datetime(2026, 5, 18, 15, 0, tzinfo=UTC),
            "created_at": datetime(2026, 5, 18, 15, 0, tzinfo=UTC),
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
        clock=lambda: datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
        credit_ledger=credits,
    )
    now = datetime(2026, 5, 20, tzinfo=UTC)
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
            "billing_start_at": datetime(2026, 5, 1, tzinfo=UTC),
            "created_at": datetime(2026, 5, 1, tzinfo=UTC),
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


@pytest.mark.asyncio
async def test_latest_paid_payment_for_enrollment_finds_legacy_paid_status(db, acad) -> None:
    repo = MongoPaymentRepository(db)
    # Legacy onboarding writes status="paid" (not the v2 "succeeded") and stores
    # enrollment_id on the row.
    await db["payments"].insert_one(
        {
            "academy_id": acad,
            "payment_id": "legacy-pay-1",
            "enrollment_id": "enroll-legacy-1",
            "parent_id": "parent-legacy-1",
            "session_id": "sess-legacy-1",
            "status": "paid",
            "amount_cents": 4000,
            "calculation_snapshot_id": "snap-legacy-1",
            "created_at": datetime(2026, 5, 1, tzinfo=UTC),
            "updated_at": datetime(2026, 5, 1, tzinfo=UTC),
        }
    )

    payment = await repo.latest_paid_payment_for_enrollment("enroll-legacy-1")

    assert payment is not None
    assert payment.payment_id == "legacy-pay-1"
    assert payment.calculation_snapshot_id == "snap-legacy-1"


@pytest.mark.asyncio
async def test_latest_paid_payment_for_enrollment_fallback_via_session_when_enrollment_id_missing(
    db, acad
) -> None:
    repo = MongoPaymentRepository(db)
    # Older onboarding payments may have been written before enrollment_id was
    # backfilled onto the payment row. They still have parent_id and session_id.
    await db["enrollments"].insert_one(
        {
            "academy_id": acad,
            "_id": "enroll-orphan-1",
            "enrollment_id": "enroll-orphan-1",
            "parent_user_id": "parent-orphan-1",
            "session_id": "sess-orphan-1",
            "status": "active",
        }
    )
    await db["payments"].insert_one(
        {
            "academy_id": acad,
            "payment_id": "orphan-pay-1",
            "parent_user_id": "parent-orphan-1",
            "session_id": "sess-orphan-1",
            "status": "paid",
            "amount_cents": 4000,
            "calculation_snapshot_id": "snap-orphan-1",
            "created_at": datetime(2026, 5, 1, tzinfo=UTC),
            "updated_at": datetime(2026, 5, 1, tzinfo=UTC),
        }
    )

    payment = await repo.latest_paid_payment_for_enrollment("enroll-orphan-1")

    assert payment is not None
    assert payment.payment_id == "orphan-pay-1"


@pytest.mark.asyncio
async def test_latest_paid_payment_for_enrollment_fallback_does_not_cross_tenants(db, acad) -> None:
    repo = MongoPaymentRepository(db)
    await db["enrollments"].insert_one(
        {
            "academy_id": "other-acad",
            "_id": "enroll-cross-tenant",
            "enrollment_id": "enroll-cross-tenant",
            "parent_user_id": "parent-other",
            "session_id": "sess-other",
            "status": "active",
        }
    )
    await db["payments"].insert_one(
        {
            "academy_id": acad,
            "payment_id": "current-pay-without-enrollment",
            "parent_user_id": "parent-other",
            "session_id": "sess-other",
            "status": "paid",
            "amount_cents": 5000,
            "calculation_snapshot_id": "snap-current-1",
            "created_at": datetime(2026, 5, 2, tzinfo=UTC),
            "updated_at": datetime(2026, 5, 2, tzinfo=UTC),
        }
    )
    await db["payments"].insert_one(
        {
            "academy_id": "other-acad",
            "payment_id": "other-pay-1",
            "parent_user_id": "parent-other",
            "session_id": "sess-other",
            "status": "paid",
            "amount_cents": 4000,
            "calculation_snapshot_id": "snap-other-1",
            "created_at": datetime(2026, 5, 1, tzinfo=UTC),
            "updated_at": datetime(2026, 5, 1, tzinfo=UTC),
        }
    )

    payment = await repo.latest_paid_payment_for_enrollment("enroll-cross-tenant")

    assert payment is None


@pytest.mark.asyncio
async def test_list_all_tolerates_legacy_waived_payments(db, acad) -> None:
    repo = MongoPaymentRepository(db)
    await db["payments"].insert_one(
        {
            "academy_id": acad,
            "payment_id": "waived-pay-1",
            "parent_id": "parent-waived-1",
            "session_id": "sess-waived-1",
            "status": "waived",
            "amount_cents": 4000,
            "created_at": datetime(2026, 5, 1, tzinfo=UTC),
            "updated_at": datetime(2026, 5, 1, tzinfo=UTC),
        }
    )

    payments = await repo.list_all()

    assert [payment.payment_id for payment in payments] == ["waived-pay-1"]
    assert payments[0].status == "waived"
