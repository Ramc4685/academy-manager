"""Mongo payment repository contract tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.contexts.billing.domain.models import CreditLedgerEntry, Payment
from backend.v2.contexts.billing.infrastructure.mongo_billing_ledger_repo import (
    MongoBillingLedgerRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_credit_ledger_repo import (
    MongoCreditLedgerRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_payment_repo import MongoPaymentRepository


async def _seed_monthly_enrollment(
    db,
    acad: str,
    *,
    enrollment_id: str,
    session_id: str,
    student_id: str,
    parent_id: str,
    extra_enrollment: dict | None = None,
) -> None:
    await db["sessions"].insert_one(
        {
            "academy_id": acad,
            "session_id": session_id,
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
            "student_id": student_id,
            "parent_id": parent_id,
            "full_name": "A Student",
        }
    )
    enrollment = {
        "academy_id": acad,
        "enrollment_id": enrollment_id,
        "session_id": session_id,
        "student_id": student_id,
        "parent_id": parent_id,
        "status": "active",
        "billing_type": "standard",
        "billing_start_at": datetime(2026, 5, 1, tzinfo=UTC),
        "created_at": datetime(2026, 5, 1, tzinfo=UTC),
    }
    enrollment.update(extra_enrollment or {})
    await db["enrollments"].insert_one(enrollment)


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
async def test_get_and_save_ledger_payment_without_recreating_legacy_payment(db, acad) -> None:
    now = datetime.now(UTC)
    await db["ledger_payments"].insert_one(
        {
            "academy_id": acad,
            "payment_id": "lp-refundable",
            "parent_id": "parent-1",
            "amount_cents": 10_000,
            "unapplied_amount_cents": 0,
            "currency": "usd",
            "status": "succeeded",
            "stripe_payment_intent_id": "pi_refundable",
            "refunded_cents": 0,
            "created_at": now,
            "updated_at": now,
        }
    )
    repo = MongoPaymentRepository(db)

    payment = await repo.get("lp-refundable")

    assert payment is not None
    assert payment.payment_id == "lp-refundable"
    assert payment.stripe_payment_intent_id == "pi_refundable"
    assert payment.amount_cents == 10_000

    await repo.save(
        payment.model_copy(
            update={
                "status": "partially_refunded",
                "refunded_cents": 4_000,
                "updated_at": now,
            }
        )
    )

    ledger_payment = await db["ledger_payments"].find_one(
        {"academy_id": acad, "payment_id": "lp-refundable"}
    )
    assert ledger_payment is not None
    # LedgerPayment only accepts pending/succeeded/failed/refunded, so a
    # partial refund must be normalized to "succeeded" with the refunded
    # amount tracked separately; otherwise later ledger reads fail to parse.
    assert ledger_payment["status"] == "succeeded"
    assert ledger_payment["refunded_cents"] == 4_000
    assert await db["payments"].count_documents({"academy_id": acad}) == 0

    # Regression guard: the persisted doc must round-trip through the ledger
    # domain model without raising a validation error.
    from backend.v2.contexts.billing.infrastructure.mongo_billing_ledger_repo import (
        MongoBillingLedgerRepository,
    )

    parsed = MongoBillingLedgerRepository._payment_from_doc(ledger_payment)
    assert parsed.status == "succeeded"


@pytest.mark.asyncio
async def test_generate_monthly_prorates_first_period_and_stores_snapshot(db, acad) -> None:
    ledger_repo = MongoBillingLedgerRepository(db)
    repo = MongoPaymentRepository(
        db,
        clock=lambda: datetime(2026, 5, 18, 22, 0, tzinfo=UTC),
        ledger_repo=ledger_repo,
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
    # Legacy payment is no longer written; verify the LedgerInvoice was created instead.
    legacy = await db["payments"].find_one({"academy_id": acad, "enrollment_id": "enroll-1"})
    assert legacy is None
    invoice = await db["invoices"].find_one({"academy_id": acad, "enrollment_id": "enroll-1"})
    assert invoice is not None
    assert invoice["total_cents"] == 3_333
    assert invoice["invoice_id"] == "inv-monthly-enroll-1-2026-05"
    # Verify the calculation snapshot was still produced and consumed.
    snapshot = await db["billing_calculation_snapshots"].find_one(
        {"academy_id": acad, "status": "CONSUMED"}
    )
    assert snapshot is not None
    assert snapshot["total_eligible_classes"] == 9
    assert snapshot["billable_remaining_classes"] == 3
    assert snapshot["excluded_occurrences"]["sess-prorate:2026-05-18:18:00"] == "SAME_DAY_CUTOFF"


@pytest.mark.asyncio
async def test_generate_monthly_creates_ledger_invoice_for_active_autopay_enrollment_before_webhook(
    db, acad
) -> None:
    ledger_repo = MongoBillingLedgerRepository(db)
    repo = MongoPaymentRepository(
        db,
        clock=lambda: datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
        ledger_repo=ledger_repo,
    )
    await _seed_monthly_enrollment(
        db,
        acad,
        enrollment_id="enroll-autopay",
        session_id="sess-autopay",
        student_id="student-autopay",
        parent_id="parent-autopay",
        extra_enrollment={
            "payment_mode": "autopay",
            "subscription_status": "active",
            "stripe_subscription_id": "sub_active_autopay",
        },
    )

    result = await repo.generate_monthly_payments("2026-06")

    assert result.created == 1
    assert result.skipped_autopay == 0
    assert await db["payments"].count_documents({"academy_id": acad}) == 0
    invoice = await db["invoices"].find_one({"academy_id": acad, "enrollment_id": "enroll-autopay"})
    assert invoice is not None
    assert invoice["invoice_id"] == "inv-monthly-enroll-autopay-2026-06"
    assert invoice["status"] == "open"
    assert invoice["total_cents"] == 10_000
    assert invoice["balance_due_cents"] == 10_000
    assert invoice.get("stripe_invoice_id") is None


@pytest.mark.asyncio
async def test_generate_monthly_autopay_invoice_is_idempotent_per_enrollment_period(
    db, acad
) -> None:
    await db["billing_invoice_keys"].create_index(
        [("academy_id", 1), ("enrollment_id", 1), ("period", 1)],
        unique=True,
        name="uniq_monthly_invoice_key",
    )
    ledger_repo = MongoBillingLedgerRepository(db)
    repo = MongoPaymentRepository(
        db,
        clock=lambda: datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
        ledger_repo=ledger_repo,
    )
    await _seed_monthly_enrollment(
        db,
        acad,
        enrollment_id="enroll-autopay-idempotent",
        session_id="sess-autopay-idempotent",
        student_id="student-autopay-idempotent",
        parent_id="parent-autopay-idempotent",
        extra_enrollment={
            "payment_mode": "autopay",
            "subscription_status": "active",
            "stripe_subscription_id": "sub_active_autopay_idempotent",
        },
    )

    first = await repo.generate_monthly_payments("2026-06")
    second = await repo.generate_monthly_payments("2026-06")

    assert first.created == 1
    assert second.created == 0
    assert second.skipped_existing == 1
    assert (
        await db["invoices"].count_documents(
            {
                "academy_id": acad,
                "invoice_id": "inv-monthly-enroll-autopay-idempotent-2026-06",
            }
        )
        == 1
    )


@pytest.mark.asyncio
async def test_generate_monthly_applies_approved_account_credit(db, acad) -> None:
    credits = MongoCreditLedgerRepository(db)
    ledger_repo = MongoBillingLedgerRepository(db)
    repo = MongoPaymentRepository(
        db,
        clock=lambda: datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
        credit_ledger=credits,
        ledger_repo=ledger_repo,
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
    # Legacy payment is no longer written; verify the LedgerInvoice reflects post-credit amount.
    legacy = await db["payments"].find_one({"academy_id": acad, "enrollment_id": "enroll-1"})
    assert legacy is None
    invoice = await db["invoices"].find_one({"academy_id": acad, "enrollment_id": "enroll-1"})
    assert invoice is not None
    assert invoice["total_cents"] == 6_250  # 10_000 gross - 3_750 credit
    assert await credits.balance_for_parent("parent-1") == 0


@pytest.mark.asyncio
async def test_generate_monthly_recovers_orphan_invoice_key_with_existing_credit_application(
    db, acad
) -> None:
    await db["billing_invoice_keys"].create_index(
        [("academy_id", 1), ("enrollment_id", 1), ("period", 1)],
        unique=True,
        name="uniq_monthly_invoice_key",
    )
    credits = MongoCreditLedgerRepository(db)
    ledger_repo = MongoBillingLedgerRepository(db)
    repo = MongoPaymentRepository(
        db,
        clock=lambda: datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
        credit_ledger=credits,
        ledger_repo=ledger_repo,
    )
    now = datetime(2026, 5, 20, tzinfo=UTC)
    await credits.create(
        CreditLedgerEntry(
            credit_id="credit-orphan-key",
            academy_id=acad,
            parent_id="parent-1",
            student_id="student-1",
            enrollment_id="enroll-orphan-key",
            type="EARLY_WITHDRAWAL_CREDIT",
            status="APPROVED",
            amount_cents=3_750,
            remaining_amount_cents=3_750,
            currency="usd",
            reason="withdrawal",
            calculation_snapshot_id="snap-orphan-key",
            created_at=now,
            updated_at=now,
        )
    )
    await credits.apply_available_credits(
        parent_id="parent-1",
        invoice_id="pay-orphan-key",
        amount_due_cents=10_000,
    )
    await db["billing_invoice_keys"].insert_one(
        {
            "academy_id": acad,
            "invoice_key_id": "key-orphan",
            "payment_id": "pay-orphan-key",
            "enrollment_id": "enroll-orphan-key",
            "period": "2026-06",
            "created_at": now,
        }
    )
    await db["sessions"].insert_one(
        {
            "academy_id": acad,
            "session_id": "sess-orphan-key",
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
            "enrollment_id": "enroll-orphan-key",
            "session_id": "sess-orphan-key",
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
    assert result.skipped_existing == 0
    invoice = await db["invoices"].find_one(
        {"academy_id": acad, "invoice_id": "inv-monthly-enroll-orphan-key-2026-06"}
    )
    assert invoice is not None
    assert invoice["total_cents"] == 6_250
    assert invoice["balance_due_cents"] == 6_250
    assert await credits.balance_for_parent("parent-1") == 0
    assert (
        await db["credit_applications"].count_documents(
            {"academy_id": acad, "invoice_id": "pay-orphan-key"}
        )
        == 1
    )

    replay = await repo.generate_monthly_payments("2026-06")

    assert replay.created == 0
    assert replay.skipped_existing == 1
    assert (
        await db["invoices"].count_documents(
            {"academy_id": acad, "invoice_id": "inv-monthly-enroll-orphan-key-2026-06"}
        )
        == 1
    )


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
