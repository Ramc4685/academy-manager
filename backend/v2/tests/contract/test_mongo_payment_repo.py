"""Mongo payment repository contract tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime

import pytest

from backend.v2.contexts.billing.domain.errors import PaymentOperationNotAllowed
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
    # LedgerPaymentStatus includes "partially_refunded" (domain/ledger.py), so
    # the bridge must persist the real status — downgrading to "succeeded"
    # hides partially-refunded payments from any status-filtered query.
    assert ledger_payment["status"] == "partially_refunded"
    assert ledger_payment["refunded_cents"] == 4_000
    assert await db["payments"].count_documents({"academy_id": acad}) == 0

    # Regression guard: the persisted doc must round-trip through the ledger
    # domain model without raising a validation error.
    from backend.v2.contexts.billing.infrastructure.mongo_billing_ledger_repo import (
        MongoBillingLedgerRepository,
    )

    parsed = MongoBillingLedgerRepository._payment_from_doc(ledger_payment)
    assert parsed.status == "partially_refunded"


@pytest.mark.asyncio
async def test_save_refuses_second_ledger_row_for_same_stripe_payment_intent(db, acad) -> None:
    """Issue #505: a brand-new Payment whose stripe_payment_intent_id already
    exists in ledger_payments (e.g. the ledger-native row written by the
    subscription-invoice sync) must NOT insert a second row — that row would
    double-count the charge in every ledger-based revenue report."""
    now = datetime.now(UTC)
    await db["ledger_payments"].insert_one(
        {
            "academy_id": acad,
            "payment_id": "ledger-pay-in_dup",
            "parent_id": "parent-1",
            "amount_cents": 7_000,
            "unapplied_amount_cents": 0,
            "currency": "usd",
            "status": "succeeded",
            "stripe_payment_intent_id": "pi_dup",
            "stripe_invoice_id": "in_dup",
            "refunded_cents": 0,
            "created_at": now,
            "updated_at": now,
        }
    )
    repo = MongoPaymentRepository(db)

    await repo.save(
        Payment(
            payment_id="legacy-projection-dup",
            academy_id=acad,
            parent_id="parent-1",
            stripe_payment_intent_id="pi_dup",
            amount_cents=7_000,
            currency="usd",
            status="succeeded",
            created_at=now,
            updated_at=now,
        )
    )

    assert (
        await db["ledger_payments"].count_documents(
            {"academy_id": acad, "stripe_payment_intent_id": "pi_dup"}
        )
        == 1
    )
    assert await db["payments"].count_documents({"academy_id": acad}) == 0
    # A payment WITHOUT a stripe PI is unaffected by the guard.
    await repo.save(
        Payment(
            payment_id="manual-no-pi",
            academy_id=acad,
            parent_id="parent-1",
            amount_cents=1_000,
            currency="usd",
            status="succeeded",
            created_at=now,
            updated_at=now,
        )
    )
    assert (
        await db["ledger_payments"].count_documents(
            {"academy_id": acad, "payment_id": "manual-no-pi"}
        )
        == 1
    )


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


def _due_date_of(invoice: dict) -> date:
    """due_date round-trips through Mongo as a midnight-UTC datetime."""
    raw = invoice["due_date"]
    return raw.date() if isinstance(raw, datetime) else raw


@pytest.mark.asyncio
async def test_generate_monthly_due_date_is_generation_date_plus_configured_grace(db, acad) -> None:
    """Issue #288 R4: the grace window is anchored to the generation date, not
    to the period's last day, so a late or backfilled period still gets the
    full window before the dunning ladder's first autopay attempt fires."""
    await db["billing_settings"].insert_one({"academy_id": acad, "invoice_due_days": 10})
    repo = MongoPaymentRepository(
        db,
        clock=lambda: datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
        ledger_repo=MongoBillingLedgerRepository(db),
    )
    await _seed_monthly_enrollment(
        db,
        acad,
        enrollment_id="enroll-due",
        session_id="sess-due",
        student_id="student-due",
        parent_id="parent-due",
    )

    result = await repo.generate_monthly_payments("2026-06")

    assert result.created == 1
    invoice = await db["invoices"].find_one({"academy_id": acad, "enrollment_id": "enroll-due"})
    assert invoice is not None
    assert _due_date_of(invoice) == date(2026, 6, 11)


@pytest.mark.asyncio
async def test_generate_monthly_due_date_falls_back_to_default_grace_without_settings(
    db, acad
) -> None:
    """Settings are advisory for generation: an academy with no
    billing_settings doc must still be invoiced, on the 7-day default."""
    repo = MongoPaymentRepository(
        db,
        clock=lambda: datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
        ledger_repo=MongoBillingLedgerRepository(db),
    )
    await _seed_monthly_enrollment(
        db,
        acad,
        enrollment_id="enroll-nodue",
        session_id="sess-nodue",
        student_id="student-nodue",
        parent_id="parent-nodue",
    )

    result = await repo.generate_monthly_payments("2026-06")

    assert result.created == 1
    invoice = await db["invoices"].find_one({"academy_id": acad, "enrollment_id": "enroll-nodue"})
    assert invoice is not None
    assert _due_date_of(invoice) == date(2026, 6, 8)


@pytest.mark.asyncio
async def test_generate_monthly_survives_unreadable_billing_settings(db, acad) -> None:
    """A corrupt settings doc must never block the monthly run — a missed month
    is only recoverable by an admin noticing it."""
    await db["billing_settings"].insert_one({"academy_id": acad, "invoice_due_days": 999})
    repo = MongoPaymentRepository(
        db,
        clock=lambda: datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
        ledger_repo=MongoBillingLedgerRepository(db),
    )
    await _seed_monthly_enrollment(
        db,
        acad,
        enrollment_id="enroll-bad",
        session_id="sess-bad",
        student_id="student-bad",
        parent_id="parent-bad",
    )

    result = await repo.generate_monthly_payments("2026-06")

    assert result.created == 1
    invoice = await db["invoices"].find_one({"academy_id": acad, "enrollment_id": "enroll-bad"})
    assert invoice is not None
    assert _due_date_of(invoice) == date(2026, 6, 8)


@pytest.mark.asyncio
async def test_generate_monthly_returns_row_level_skip_for_active_billing_deferral(
    db, acad
) -> None:
    ledger_repo = MongoBillingLedgerRepository(db)
    repo = MongoPaymentRepository(
        db,
        clock=lambda: datetime(2026, 6, 22, 12, 0, tzinfo=UTC),
        ledger_repo=ledger_repo,
    )
    await _seed_monthly_enrollment(
        db,
        acad,
        enrollment_id="enroll-paused",
        session_id="sess-paused",
        student_id="student-paused",
        parent_id="parent-paused",
        extra_enrollment={"status": "paused"},
    )
    await db["enrollment_billing_deferrals"].insert_one(
        {
            "academy_id": acad,
            "deferral_id": "def-paused",
            "enrollment_id": "enroll-paused",
            "student_id": "student-paused",
            "deferral_type": "fixed_pause",
            "reason": "summer travel",
            "source": "pause_request",
            "source_id": "pause-1",
            "actor_id": "admin-1",
            "billing_period": "2026-06",
            "resume_on": "2026-07-15",
            "status": "active",
            "created_at": datetime(2026, 6, 1, tzinfo=UTC),
            "updated_at": datetime(2026, 6, 1, tzinfo=UTC),
        }
    )

    result = await repo.generate_monthly_payments("2026-06")

    assert result.created == 0
    assert result.skipped_paused == 1
    assert len(result.skipped_details) == 1
    detail = result.skipped_details[0]
    assert detail.enrollment_id == "enroll-paused"
    assert detail.student_id == "student-paused"
    assert detail.reason_code == "fixed_pause"
    assert detail.source == "pause_request"
    assert detail.resume_on == "2026-07-15"


@pytest.mark.asyncio
async def test_generate_monthly_skips_paused_enrollment_even_when_deferral_expired(
    db, acad
) -> None:
    ledger_repo = MongoBillingLedgerRepository(db)
    repo = MongoPaymentRepository(
        db,
        clock=lambda: datetime(2026, 6, 22, 12, 0, tzinfo=UTC),
        ledger_repo=ledger_repo,
    )
    await _seed_monthly_enrollment(
        db,
        acad,
        enrollment_id="enroll-stale",
        session_id="sess-stale",
        student_id="student-stale",
        parent_id="parent-stale",
        extra_enrollment={"status": "paused"},
    )
    await db["enrollment_billing_deferrals"].insert_one(
        {
            "academy_id": acad,
            "deferral_id": "def-stale",
            "enrollment_id": "enroll-stale",
            "student_id": "student-stale",
            "deferral_type": "admin_pause",
            "reason": "old pause",
            "source": "admin_direct_pause",
            "actor_id": "admin-1",
            "billing_period": "2026-05",
            "review_on": "2026-05-15",
            "status": "active",
            "created_at": datetime(2026, 5, 1, tzinfo=UTC),
            "updated_at": datetime(2026, 5, 1, tzinfo=UTC),
        }
    )

    result = await repo.generate_monthly_payments("2026-06")

    # Issue #651 policy: a paused enrollment is never invoiced, even when its
    # deferral has expired or its review date is stale — that shows up as an
    # admin warning, not as a surprise invoice.
    assert result.created == 0
    assert result.skipped_paused == 1
    assert result.skipped_details[0].reason_code == "enrollment_paused"


@pytest.mark.asyncio
async def test_generate_monthly_skips_paused_enrollment_even_when_review_date_is_stale(
    db, acad
) -> None:
    ledger_repo = MongoBillingLedgerRepository(db)
    repo = MongoPaymentRepository(
        db,
        clock=lambda: datetime(2026, 6, 22, 12, 0, tzinfo=UTC),
        ledger_repo=ledger_repo,
    )
    await _seed_monthly_enrollment(
        db,
        acad,
        enrollment_id="enroll-stale-review",
        session_id="sess-stale-review",
        student_id="student-stale-review",
        parent_id="parent-stale-review",
        extra_enrollment={"status": "paused"},
    )
    await db["enrollment_billing_deferrals"].insert_one(
        {
            "academy_id": acad,
            "deferral_id": "def-stale-review",
            "enrollment_id": "enroll-stale-review",
            "student_id": "student-stale-review",
            "deferral_type": "admin_pause",
            "reason": "old pause",
            "source": "admin_direct_pause",
            "actor_id": "admin-1",
            "billing_period": "2026-06",
            "review_on": "2026-06-01",
            "status": "active",
            "created_at": datetime(2026, 6, 1, tzinfo=UTC),
            "updated_at": datetime(2026, 6, 1, tzinfo=UTC),
        }
    )

    result = await repo.generate_monthly_payments("2026-06")

    # Issue #651 policy: a paused enrollment is never invoiced, even when its
    # deferral has expired or its review date is stale — that shows up as an
    # admin warning, not as a surprise invoice.
    assert result.created == 0
    assert result.skipped_paused == 1
    assert result.skipped_details[0].reason_code == "enrollment_paused"


@pytest.mark.asyncio
async def test_generate_monthly_legacy_skip_period_returns_needs_review_detail(db, acad) -> None:
    ledger_repo = MongoBillingLedgerRepository(db)
    repo = MongoPaymentRepository(
        db,
        clock=lambda: datetime(2026, 6, 22, 12, 0, tzinfo=UTC),
        ledger_repo=ledger_repo,
    )
    await _seed_monthly_enrollment(
        db,
        acad,
        enrollment_id="enroll-legacy-skip",
        session_id="sess-legacy-skip",
        student_id="student-legacy-skip",
        parent_id="parent-legacy-skip",
        extra_enrollment={"skip_periods": ["2026-06"]},
    )

    result = await repo.generate_monthly_payments("2026-06")

    assert result.created == 0
    assert result.skipped_paused == 1
    assert len(result.skipped_details) == 1
    detail = result.skipped_details[0]
    assert detail.reason_code == "legacy_skip_period"
    assert detail.source == "enrollment.skip_periods"
    assert detail.needs_review is True


async def _seed_enrollment_without_billing_start(
    db,
    acad: str,
    *,
    enrollment_id: str,
    session_id: str,
    student_id: str,
    parent_id: str,
    extra_enrollment: dict | None = None,
) -> None:
    """Mirror the real shape of an admin-approved enrollment doc.

    Neither admin_registration_review.py nor confirm_enrollment.py ever stamp
    billing_start_at/enrolled_at/created_at onto the enrollment document, so
    _resolve_charge_for_enrollment's billing_start is always None for these —
    it never takes the first-month-proration branch, only the full-tuition
    one. skip_periods is therefore the only signal that can prevent a $0-quote
    period from being billed at full price once the enrollment exists.
    """
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
    }
    enrollment.update(extra_enrollment or {})
    await db["enrollments"].insert_one(enrollment)


@pytest.mark.asyncio
async def test_generate_monthly_skips_zero_quote_period_via_skip_periods(db, acad) -> None:
    """Regression for the zero-amount-checkout billing gap (PR #292).

    A checkout quoted $0 for 2026-06 and admin approval stamped skip_periods
    on the enrollment; generating 2026-06 must create no payment/invoice.
    """
    ledger_repo = MongoBillingLedgerRepository(db)
    repo = MongoPaymentRepository(
        db,
        clock=lambda: datetime(2026, 6, 22, 12, 0, tzinfo=UTC),
        ledger_repo=ledger_repo,
    )
    await _seed_enrollment_without_billing_start(
        db,
        acad,
        enrollment_id="enroll-zero-quote",
        session_id="sess-zero-quote",
        student_id="student-zero-quote",
        parent_id="parent-zero-quote",
        extra_enrollment={"skip_periods": ["2026-06"]},
    )

    result = await repo.generate_monthly_payments("2026-06")

    assert result.created == 0
    assert result.skipped_paused == 1
    invoice = await db["invoices"].find_one(
        {"academy_id": acad, "enrollment_id": "enroll-zero-quote"}
    )
    assert invoice is None


@pytest.mark.asyncio
async def test_generate_monthly_without_skip_periods_charges_full_tuition(db, acad) -> None:
    """Characterizes the bug this fix prevents: absent skip_periods, an
    enrollment with no billing_start_at is billed the FULL monthly price
    (not prorated, not $0) because _resolve_charge_for_enrollment has no
    proration signal at all for these documents.
    """
    ledger_repo = MongoBillingLedgerRepository(db)
    repo = MongoPaymentRepository(
        db,
        clock=lambda: datetime(2026, 6, 22, 12, 0, tzinfo=UTC),
        ledger_repo=ledger_repo,
    )
    await _seed_enrollment_without_billing_start(
        db,
        acad,
        enrollment_id="enroll-no-skip",
        session_id="sess-no-skip",
        student_id="student-no-skip",
        parent_id="parent-no-skip",
    )

    result = await repo.generate_monthly_payments("2026-06")

    assert result.created == 1
    invoice = await db["invoices"].find_one({"academy_id": acad, "enrollment_id": "enroll-no-skip"})
    assert invoice is not None
    assert invoice["total_cents"] == 10_000


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
async def test_generate_monthly_treats_paid_complete_invoice_as_existing(db, acad) -> None:
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
        enrollment_id="enroll-paid-existing",
        session_id="sess-paid-existing",
        student_id="student-paid-existing",
        parent_id="parent-paid-existing",
    )

    first = await repo.generate_monthly_payments("2026-06")
    await db["invoices"].update_one(
        {
            "academy_id": acad,
            "invoice_id": "inv-monthly-enroll-paid-existing-2026-06",
        },
        {"$set": {"status": "paid", "balance_due_cents": 0}},
    )
    second = await repo.generate_monthly_payments("2026-06")

    assert first.created == 1
    assert second.skipped_existing == 1
    assert second.failed_repair == 0


@pytest.mark.asyncio
async def test_generate_monthly_treats_existing_period_invoice_with_non_monthly_id_as_complete(
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
        enrollment_id="enroll-prod-existing",
        session_id="sess-prod-existing",
        student_id="student-prod-existing",
        parent_id="parent-prod-existing",
    )
    now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    await db["billing_invoice_keys"].insert_one(
        {
            "academy_id": acad,
            "invoice_key_id": "key-prod-existing",
            "enrollment_id": "enroll-prod-existing",
            "period": "2026-06",
            "created_at": now,
        }
    )
    await db["invoices"].insert_one(
        {
            "academy_id": acad,
            "invoice_id": "inv-from-prod-existing",
            "parent_id": "parent-prod-existing",
            "student_id": "student-prod-existing",
            "enrollment_id": "enroll-prod-existing",
            "period": "2026-06",
            "status": "paid",
            "subtotal_cents": 10_000,
            "discount_cents": 0,
            "total_cents": 10_000,
            "balance_due_cents": 0,
            "currency": "usd",
            "due_date": datetime(2026, 6, 30, tzinfo=UTC),
            "delivery_status": "not_sent",
            "sent_at": None,
            "last_sent_at": None,
            "finalized_at": None,
            "created_at": now,
            "updated_at": now,
            "idempotency_key": "prod-existing-invoice",
        }
    )
    await db["invoice_lines"].insert_one(
        {
            "academy_id": acad,
            "invoice_id": "inv-from-prod-existing",
            "line_id": "line-from-prod-existing",
            "line_type": "tuition",
            "description": "Monthly tuition 2026-06",
            "quantity": 1,
            "unit_amount_cents": 10_000,
            "amount_cents": 10_000,
            "source_type": "payment",
            "source_id": "manual-prod-existing",
            "created_at": now,
            "idempotency_key": "prod-existing-invoice",
        }
    )

    result = await repo.generate_monthly_payments("2026-06")

    assert result.created == 0
    assert result.skipped_existing == 1
    assert result.failed_repair == 0
    assert (
        await db["invoices"].count_documents(
            {"academy_id": acad, "invoice_id": "inv-monthly-enroll-prod-existing-2026-06"}
        )
        == 0
    )
    invoice_key = await db["billing_invoice_keys"].find_one(
        {"academy_id": acad, "enrollment_id": "enroll-prod-existing", "period": "2026-06"}
    )
    assert invoice_key is not None
    assert invoice_key["status"] == "complete"


@pytest.mark.asyncio
async def test_generate_monthly_treats_existing_period_invoice_without_key_as_complete(
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
        enrollment_id="enroll-existing-no-key",
        session_id="sess-existing-no-key",
        student_id="student-existing-no-key",
        parent_id="parent-existing-no-key",
    )
    now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    await db["invoices"].insert_one(
        {
            "academy_id": acad,
            "invoice_id": "inv-from-existing-no-key",
            "parent_id": "parent-existing-no-key",
            "student_id": "student-existing-no-key",
            "enrollment_id": "enroll-existing-no-key",
            "period": "2026-06",
            "status": "paid",
            "subtotal_cents": 10_000,
            "discount_cents": 0,
            "total_cents": 10_000,
            "balance_due_cents": 0,
            "currency": "usd",
            "due_date": datetime(2026, 6, 30, tzinfo=UTC),
            "delivery_status": "not_sent",
            "sent_at": None,
            "last_sent_at": None,
            "finalized_at": None,
            "created_at": now,
            "updated_at": now,
            "idempotency_key": "existing-no-key-invoice",
        }
    )
    await db["invoice_lines"].insert_one(
        {
            "academy_id": acad,
            "invoice_id": "inv-from-existing-no-key",
            "line_id": "line-from-existing-no-key",
            "line_type": "tuition",
            "description": "Monthly tuition 2026-06",
            "quantity": 1,
            "unit_amount_cents": 10_000,
            "amount_cents": 10_000,
            "source_type": "payment",
            "source_id": "manual-existing-no-key",
            "created_at": now,
            "idempotency_key": "existing-no-key-invoice",
        }
    )

    result = await repo.generate_monthly_payments("2026-06")

    assert result.created == 0
    assert result.skipped_existing == 1
    assert result.failed_repair == 0
    assert (
        await db["invoices"].count_documents(
            {"academy_id": acad, "invoice_id": "inv-monthly-enroll-existing-no-key-2026-06"}
        )
        == 0
    )
    invoice_key = await db["billing_invoice_keys"].find_one(
        {
            "academy_id": acad,
            "enrollment_id": "enroll-existing-no-key",
            "period": "2026-06",
        }
    )
    assert invoice_key is not None
    assert invoice_key["status"] == "complete"
    assert "payment_id" not in invoice_key


@pytest.mark.asyncio
async def test_generate_monthly_concurrent_runs_converge_to_one_invoice_and_line(db, acad) -> None:
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
        enrollment_id="enroll-concurrent",
        session_id="sess-concurrent",
        student_id="student-concurrent",
        parent_id="parent-concurrent",
    )

    await asyncio.gather(
        repo.generate_monthly_payments("2026-06"),
        repo.generate_monthly_payments("2026-06"),
    )

    assert (
        await db["invoices"].count_documents(
            {"academy_id": acad, "invoice_id": "inv-monthly-enroll-concurrent-2026-06"}
        )
        == 1
    )
    assert (
        await db["invoice_lines"].count_documents(
            {
                "academy_id": acad,
                "invoice_id": "inv-monthly-enroll-concurrent-2026-06",
                "line_id": "line-monthly-enroll-concurrent-2026-06",
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
    assert invoice["subtotal_cents"] == 10_000
    assert invoice["total_cents"] == 6_250  # 10_000 gross - 3_750 credit
    assert await credits.balance_for_parent("parent-1") == 0

    # The completeness pre-check must recognise a credited invoice as already generated;
    # it used to compare the gross charge against a total that is net of credit.
    replay = await repo.generate_monthly_payments("2026-06")

    assert replay.created == 0
    assert replay.skipped_existing == 1
    assert replay.failed_repair == 0
    assert (
        await db["invoices"].count_documents(
            {"academy_id": acad, "enrollment_id": "enroll-1", "period": "2026-06"}
        )
        == 1
    )


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
    # Recovery records the same shape as the normal path: line and subtotal gross,
    # with only total/balance_due net of the applied credit.
    assert invoice["subtotal_cents"] == 10_000
    assert invoice["discount_cents"] == 0
    assert invoice["total_cents"] == 6_250
    assert invoice["balance_due_cents"] == 6_250
    line = await db["invoice_lines"].find_one(
        {
            "academy_id": acad,
            "invoice_id": "inv-monthly-enroll-orphan-key-2026-06",
            "line_id": "line-monthly-enroll-orphan-key-2026-06",
        }
    )
    assert line is not None
    assert line["amount_cents"] == 10_000
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
async def test_generate_monthly_repairs_header_without_monthly_line(db, acad) -> None:
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
        enrollment_id="enroll-header-only",
        session_id="sess-header-only",
        student_id="student-header-only",
        parent_id="parent-header-only",
    )
    await db["billing_invoice_keys"].insert_one(
        {
            "academy_id": acad,
            "invoice_key_id": "key-header-only",
            "payment_id": "pay-header-only",
            "enrollment_id": "enroll-header-only",
            "period": "2026-06",
            "created_at": datetime(2026, 5, 20, tzinfo=UTC),
        }
    )
    await db["invoices"].insert_one(
        {
            "academy_id": acad,
            "invoice_id": "inv-monthly-enroll-header-only-2026-06",
            "parent_id": "parent-header-only",
            "student_id": "student-header-only",
            "enrollment_id": "enroll-header-only",
            "period": "2026-06",
            "status": "open",
            "subtotal_cents": 10_000,
            "discount_cents": 0,
            "total_cents": 10_000,
            "balance_due_cents": 10_000,
            "currency": "usd",
            "due_date": datetime(2026, 6, 30, tzinfo=UTC),
            "source_type": None,
            "source_id": None,
            "delivery_status": "not_sent",
            "sent_at": None,
            "last_sent_at": None,
            "finalized_at": None,
            "created_at": datetime(2026, 5, 20, tzinfo=UTC),
            "updated_at": datetime(2026, 5, 20, tzinfo=UTC),
            "idempotency_key": "monthly-ledger-enroll-header-only-2026-06",
        }
    )

    result = await repo.generate_monthly_payments("2026-06")

    assert result.created == 0
    assert result.repaired_partial_invoices == 1
    assert result.failed_repair == 0
    assert result.skipped_existing == 0
    line = await db["invoice_lines"].find_one(
        {
            "academy_id": acad,
            "invoice_id": "inv-monthly-enroll-header-only-2026-06",
            "line_id": "line-monthly-enroll-header-only-2026-06",
        }
    )
    assert line is not None
    assert line["amount_cents"] == 10_000


@pytest.mark.asyncio
async def test_generate_monthly_reports_failed_repair_for_conflicting_monthly_line(
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
        enrollment_id="enroll-conflict",
        session_id="sess-conflict",
        student_id="student-conflict",
        parent_id="parent-conflict",
    )
    now = datetime(2026, 5, 20, tzinfo=UTC)
    await db["billing_invoice_keys"].insert_one(
        {
            "academy_id": acad,
            "invoice_key_id": "key-conflict",
            "payment_id": "pay-conflict",
            "enrollment_id": "enroll-conflict",
            "period": "2026-06",
            "status": "claimed",
            "created_at": now,
            "updated_at": now,
        }
    )
    await db["invoices"].insert_one(
        {
            "academy_id": acad,
            "invoice_id": "inv-monthly-enroll-conflict-2026-06",
            "parent_id": "parent-conflict",
            "student_id": "student-conflict",
            "enrollment_id": "enroll-conflict",
            "period": "2026-06",
            "status": "open",
            "subtotal_cents": 1_000,
            "discount_cents": 0,
            "total_cents": 1_000,
            "balance_due_cents": 1_000,
            "currency": "usd",
            "due_date": datetime(2026, 6, 30, tzinfo=UTC),
            "delivery_status": "not_sent",
            "sent_at": None,
            "last_sent_at": None,
            "finalized_at": None,
            "created_at": now,
            "updated_at": now,
            "idempotency_key": "monthly-ledger-enroll-conflict-2026-06",
        }
    )
    await db["invoice_lines"].insert_one(
        {
            "academy_id": acad,
            "invoice_id": "inv-monthly-enroll-conflict-2026-06",
            "line_id": "line-monthly-enroll-conflict-2026-06",
            "line_type": "tuition",
            "description": "Monthly tuition 2026-06",
            "quantity": 1,
            "unit_amount_cents": 1_000,
            "amount_cents": 1_000,
            "source_type": "payment",
            "source_id": "pay-conflict",
            "created_at": now,
            "idempotency_key": "monthly-ledger-enroll-conflict-2026-06",
        }
    )

    result = await repo.generate_monthly_payments("2026-06")

    assert result.failed_repair == 1
    assert result.skipped_existing == 0
    invoice_key = await db["billing_invoice_keys"].find_one(
        {"academy_id": acad, "enrollment_id": "enroll-conflict", "period": "2026-06"}
    )
    assert invoice_key is not None
    assert invoice_key["status"] == "repair_failed"


@pytest.mark.asyncio
async def test_generate_monthly_recovers_credit_from_source_of_truth_when_audit_missing(
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
            credit_id="credit-source-truth",
            academy_id=acad,
            parent_id="parent-source-truth",
            student_id="student-source-truth",
            enrollment_id="enroll-source-truth",
            type="EARLY_WITHDRAWAL_CREDIT",
            status="APPROVED",
            amount_cents=3_750,
            remaining_amount_cents=3_750,
            currency="usd",
            reason="withdrawal",
            calculation_snapshot_id="snap-source-truth",
            created_at=now,
            updated_at=now,
        )
    )
    await credits.apply_available_credits(
        parent_id="parent-source-truth",
        invoice_id="pay-source-truth",
        amount_due_cents=10_000,
    )
    await db["credit_applications"].delete_many(
        {"academy_id": acad, "invoice_id": "pay-source-truth"}
    )
    await db["billing_invoice_keys"].insert_one(
        {
            "academy_id": acad,
            "invoice_key_id": "key-source-truth",
            "payment_id": "pay-source-truth",
            "enrollment_id": "enroll-source-truth",
            "period": "2026-06",
            "created_at": now,
        }
    )
    await _seed_monthly_enrollment(
        db,
        acad,
        enrollment_id="enroll-source-truth",
        session_id="sess-source-truth",
        student_id="student-source-truth",
        parent_id="parent-source-truth",
    )

    result = await repo.generate_monthly_payments("2026-06")

    assert result.repaired_orphan_keys == 1
    invoice = await db["invoices"].find_one(
        {"academy_id": acad, "invoice_id": "inv-monthly-enroll-source-truth-2026-06"}
    )
    assert invoice is not None
    assert invoice["total_cents"] == 6_250
    assert invoice["balance_due_cents"] == 6_250


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


@pytest.mark.asyncio
async def test_undo_payment_paid_refuses_when_shadowing_ledger_payment_is_stripe_linked(
    db, acad
) -> None:
    """The Stripe-linkage guard must consider the shadowing ledger_payments doc:
    a legacy row without Stripe fields can front a real Stripe-backed ledger
    payment, and "undoing" that would silently diverge from Stripe truth."""
    now = datetime.now(UTC)
    await db["payments"].insert_one(
        {
            "academy_id": acad,
            "payment_id": "pay-shadowed",
            "parent_id": "parent-1",
            "amount_cents": 10_000,
            "status": "succeeded",
            "created_at": now,
            "updated_at": now,
        }
    )
    await db["ledger_payments"].insert_one(
        {
            "academy_id": acad,
            "payment_id": "pay-shadowed",
            "parent_id": "parent-1",
            "amount_cents": 10_000,
            "unapplied_amount_cents": 0,
            "currency": "usd",
            "status": "succeeded",
            "stripe_payment_intent_id": "pi_shadowed",
            "refunded_cents": 0,
            "created_at": now,
            "updated_at": now,
        }
    )
    repo = MongoPaymentRepository(db)

    with pytest.raises(PaymentOperationNotAllowed):
        await repo.undo_payment_paid("pay-shadowed")

    legacy_doc = await db["payments"].find_one({"academy_id": acad, "payment_id": "pay-shadowed"})
    assert legacy_doc is not None and legacy_doc["status"] == "succeeded"


@pytest.mark.asyncio
async def test_new_payment_save_is_ledger_native_and_lifecycle_works(db, acad) -> None:
    """Phase 5 freeze: brand-new payments are inserted into ledger_payments
    (marked payment_origin="legacy_payment"), never into the legacy payments
    collection — and the whole checkout lifecycle (lookup by checkout session,
    webhook status flip, lookup by PI, parent listing) keeps working."""
    now = datetime.now(UTC)
    repo = MongoPaymentRepository(db)
    await repo.save(
        Payment(
            payment_id="pay-new-1",
            academy_id=acad,
            parent_id="parent-1",
            enrollment_id="enr-1",
            session_id="sess-1",
            stripe_checkout_session_id="cs_new_1",
            amount_cents=5_000,
            status="pending",
            created_at=now,
            updated_at=now,
        )
    )

    assert await db["payments"].count_documents({"academy_id": acad}) == 0
    doc = await db["ledger_payments"].find_one({"academy_id": acad, "payment_id": "pay-new-1"})
    assert doc is not None
    assert doc["payment_origin"] == "legacy_payment"
    assert doc["unapplied_amount_cents"] == 0

    got = await repo.get_by_checkout_session("cs_new_1")
    assert got is not None and got.status == "pending"

    # Webhook completion path: stamp PI + succeeded through save() (bridge branch).
    await repo.save(
        got.model_copy(
            update={
                "status": "succeeded",
                "stripe_payment_intent_id": "pi_new_1",
                "updated_at": now,
            }
        )
    )
    by_pi = await repo.get_by_stripe_pi("pi_new_1")
    assert by_pi is not None
    assert by_pi.status == "succeeded"
    assert by_pi.payment_id == "pay-new-1"

    rows = await repo.list_for_parent("parent-1")
    assert [r.payment_id for r in rows] == ["pay-new-1"]
    assert [r.payment_id for r in await repo.list_all()] == ["pay-new-1"]


@pytest.mark.asyncio
async def test_ledger_native_payments_do_not_leak_into_legacy_lookups(db, acad) -> None:
    """Ledger-native payments (autopay / pay-link — no payment_origin marker)
    must stay invisible to legacy PI/checkout lookups, or charge.refunded
    webhooks would take the legacy branch and skip invoice refund sync."""
    now = datetime.now(UTC)
    await db["ledger_payments"].insert_one(
        {
            "academy_id": acad,
            "payment_id": "lp-native",
            "parent_id": "parent-1",
            "amount_cents": 8_000,
            "unapplied_amount_cents": 0,
            "currency": "usd",
            "status": "succeeded",
            "stripe_payment_intent_id": "pi_native",
            "stripe_checkout_session_id": "cs_native",
            "refunded_cents": 0,
            "created_at": now,
            "updated_at": now,
        }
    )
    repo = MongoPaymentRepository(db)

    assert await repo.get_by_stripe_pi("pi_native") is None
    assert await repo.get_by_checkout_session("cs_native") is None


@pytest.mark.asyncio
async def test_admin_ops_work_on_ledger_resident_payment(db, acad) -> None:
    """Phase 5b: admin manual ops (mark paid / discount) must operate on
    ledger-native payments (payment_origin marker), since new payments are no
    longer inserted into the legacy collection."""
    now = datetime.now(UTC)
    repo = MongoPaymentRepository(db)
    await repo.save(
        Payment(
            payment_id="pay-cash-1",
            academy_id=acad,
            parent_id="parent-1",
            session_id="sess-1",
            stripe_checkout_session_id="cs_cash_1",
            amount_cents=6_000,
            status="pending",
            created_at=now,
            updated_at=now,
        )
    )
    assert await db["payments"].count_documents({"academy_id": acad}) == 0

    await repo.apply_payment_discount("pay-cash-1", 1_000, reason="sibling")
    doc = await db["ledger_payments"].find_one({"academy_id": acad, "payment_id": "pay-cash-1"})
    assert doc is not None and doc["discount_cents"] == 1_000

    await repo.mark_payment_paid(
        "pay-cash-1",
        payment_method="cash",
        notes="paid at front desk",
        amount_received_cents=5_000,
        reference_number=None,
    )
    doc = await db["ledger_payments"].find_one({"academy_id": acad, "payment_id": "pay-cash-1"})
    assert doc is not None
    assert doc["status"] == "succeeded"
    assert doc["paid_amount_cents"] == 5_000
    assert await db["payments"].count_documents({"academy_id": acad}) == 0

    # The doc must still round-trip through the ledger domain parser.
    from backend.v2.contexts.billing.infrastructure.mongo_billing_ledger_repo import (
        MongoBillingLedgerRepository,
    )

    assert MongoBillingLedgerRepository._payment_from_doc(doc).status == "succeeded"


@pytest.mark.asyncio
async def test_generate_monthly_recovers_net_invoice_when_every_credit_audit_write_is_lost(
    db, acad
) -> None:
    """Issue #233: the crash window between the credit decrement and the audit writes.

    Real-world ordering inside ``generate_monthly_payments``:

    1. ``billing_invoice_keys`` row is inserted (payment_id ``pay-crash``)  -- durable
    2. ``apply_available_credits`` atomically decrements the credit document
       and pushes ``pay-crash`` into ``applied_invoice_ids``                -- durable
    3. *** process dies here ***  neither the ``credit_applications`` audit row
       nor the ``CREDIT_APPLIED`` ledger document is ever written
    4. the invoice itself is never written

    Deleting both projections after the fact reproduces byte-for-byte the database
    state a crash at (3) leaves behind. On rerun the generator must recover the
    invoice at NET (6_250), not at gross (10_000) -- the family already spent the
    credit, so billing them the full amount overcharges them.
    """
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
            credit_id="credit-crash",
            academy_id=acad,
            parent_id="parent-crash",
            student_id="student-crash",
            enrollment_id="enroll-crash",
            type="EARLY_WITHDRAWAL_CREDIT",
            status="APPROVED",
            amount_cents=3_750,
            remaining_amount_cents=3_750,
            currency="usd",
            reason="withdrawal",
            calculation_snapshot_id="snap-crash",
            created_at=now,
            updated_at=now,
        )
    )
    await credits.apply_available_credits(
        parent_id="parent-crash",
        invoice_id="pay-crash",
        amount_due_cents=10_000,
    )
    # The crash: both projections of the credit application are lost.
    await db["credit_applications"].delete_many({"academy_id": acad, "invoice_id": "pay-crash"})
    await db["account_credit_ledger"].delete_many(
        {"academy_id": acad, "invoice_id": "pay-crash", "type": "CREDIT_APPLIED"}
    )
    # Sanity: the money really did leave the credit, and nothing but the credit
    # document itself records where it went.
    assert await credits.balance_for_parent("parent-crash") == 0
    assert (
        await db["credit_applications"].count_documents(
            {"academy_id": acad, "invoice_id": "pay-crash"}
        )
        == 0
    )

    await db["billing_invoice_keys"].insert_one(
        {
            "academy_id": acad,
            "invoice_key_id": "key-crash",
            "payment_id": "pay-crash",
            "enrollment_id": "enroll-crash",
            "period": "2026-06",
            "status": "claimed",
            "created_at": now,
            "updated_at": now,
        }
    )
    await _seed_monthly_enrollment(
        db,
        acad,
        enrollment_id="enroll-crash",
        session_id="sess-crash",
        student_id="student-crash",
        parent_id="parent-crash",
    )

    result = await repo.generate_monthly_payments("2026-06")

    assert result.failed_repair == 0
    assert result.repaired_orphan_keys == 1
    invoice = await db["invoices"].find_one(
        {"academy_id": acad, "invoice_id": "inv-monthly-enroll-crash-2026-06"}
    )
    assert invoice is not None
    # 10_000 gross - 3_750 credit already consumed before the crash.
    assert invoice["total_cents"] == 6_250
    assert invoice["balance_due_cents"] == 6_250
    # The credit was not spent a second time.
    assert await credits.balance_for_parent("parent-crash") == 0
    credit_doc = await db["account_credit_ledger"].find_one(
        {"academy_id": acad, "credit_id": "credit-crash"}
    )
    assert credit_doc is not None
    assert credit_doc["remaining_amount_cents"] == 0
    assert credit_doc.get("applied_invoice_ids") == ["pay-crash"]

    # A second rerun converges: no new invoice, no second correction.
    replay = await repo.generate_monthly_payments("2026-06")

    assert replay.created == 0
    assert replay.repaired_orphan_keys == 0
    assert replay.failed_repair == 0
    assert replay.skipped_existing == 1
    assert (
        await db["invoices"].count_documents(
            {"academy_id": acad, "invoice_id": "inv-monthly-enroll-crash-2026-06"}
        )
        == 1
    )
    invoice_after = await db["invoices"].find_one(
        {"academy_id": acad, "invoice_id": "inv-monthly-enroll-crash-2026-06"}
    )
    assert invoice_after is not None
    assert invoice_after["total_cents"] == 6_250
    assert invoice_after["balance_due_cents"] == 6_250
    assert await credits.balance_for_parent("parent-crash") == 0


@pytest.mark.asyncio
async def test_generate_monthly_refuses_to_bill_gross_when_credit_amount_is_unrecoverable(
    db, acad
) -> None:
    """Issue #233: unknown-but-spent credit must fail loudly, never bill gross.

    A legacy credit document carries the invoice in ``applied_invoice_ids`` but
    predates the embedded amount record, and both audit projections are gone.
    Nothing anywhere says how much was consumed, so the generator must refuse to
    price the invoice rather than guess gross and overcharge the family.
    """
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
            credit_id="credit-legacy",
            academy_id=acad,
            parent_id="parent-legacy",
            student_id="student-legacy",
            enrollment_id="enroll-legacy",
            type="MANUAL_CREDIT",
            status="APPROVED",
            amount_cents=3_750,
            remaining_amount_cents=0,
            currency="usd",
            reason="legacy credit",
            created_at=now,
            updated_at=now,
        )
    )
    # Legacy shape: tagged as applied, no embedded amount, no audit rows at all.
    await db["account_credit_ledger"].update_one(
        {"academy_id": acad, "credit_id": "credit-legacy"},
        {"$set": {"applied_invoice_ids": ["pay-legacy"]}},
    )
    await db["billing_invoice_keys"].insert_one(
        {
            "academy_id": acad,
            "invoice_key_id": "key-legacy",
            "payment_id": "pay-legacy",
            "enrollment_id": "enroll-legacy",
            "period": "2026-06",
            "status": "claimed",
            "created_at": now,
            "updated_at": now,
        }
    )
    await _seed_monthly_enrollment(
        db,
        acad,
        enrollment_id="enroll-legacy",
        session_id="sess-legacy",
        student_id="student-legacy",
        parent_id="parent-legacy",
    )

    result = await repo.generate_monthly_payments("2026-06")

    assert result.failed_repair == 1
    assert result.created == 0
    # No invoice at all beats an invoice at gross.
    assert (
        await db["invoices"].count_documents(
            {"academy_id": acad, "invoice_id": "inv-monthly-enroll-legacy-2026-06"}
        )
        == 0
    )
    # The drift is observable to an admin on the invoice key.
    invoice_key = await db["billing_invoice_keys"].find_one(
        {"academy_id": acad, "enrollment_id": "enroll-legacy", "period": "2026-06"}
    )
    assert invoice_key is not None
    assert invoice_key["status"] == "repair_failed"
    assert "credit-legacy" in invoice_key["repair_error"]


@pytest.mark.asyncio
async def test_generate_monthly_resumes_partial_credit_application_across_credits(db, acad) -> None:
    """Issue #233: an interrupted multi-credit application resumes, not restarts.

    The first run applied credit A (3_000) and died before touching credit B and
    before writing the invoice. The rerun must count A's 3_000 from the source of
    truth, top the invoice up from B, and bill the remainder.
    """
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
    for credit_id, cents in (("credit-part-a", 3_000), ("credit-part-b", 2_000)):
        await credits.create(
            CreditLedgerEntry(
                credit_id=credit_id,
                academy_id=acad,
                parent_id="parent-part",
                student_id="student-part",
                enrollment_id="enroll-part",
                type="MANUAL_CREDIT",
                status="APPROVED",
                amount_cents=cents,
                remaining_amount_cents=cents,
                currency="usd",
                reason="partial",
                created_at=now,
                updated_at=now,
            )
        )
    # First run got as far as consuming credit A only, then died.
    await credits.apply_available_credits(
        parent_id="parent-part",
        invoice_id="pay-part",
        amount_due_cents=3_000,
    )
    await db["credit_applications"].delete_many({"academy_id": acad, "invoice_id": "pay-part"})
    await db["account_credit_ledger"].delete_many(
        {"academy_id": acad, "invoice_id": "pay-part", "type": "CREDIT_APPLIED"}
    )
    assert await credits.balance_for_parent("parent-part") == 2_000

    await db["billing_invoice_keys"].insert_one(
        {
            "academy_id": acad,
            "invoice_key_id": "key-part",
            "payment_id": "pay-part",
            "enrollment_id": "enroll-part",
            "period": "2026-06",
            "status": "claimed",
            "created_at": now,
            "updated_at": now,
        }
    )
    await _seed_monthly_enrollment(
        db,
        acad,
        enrollment_id="enroll-part",
        session_id="sess-part",
        student_id="student-part",
        parent_id="parent-part",
    )

    result = await repo.generate_monthly_payments("2026-06")

    assert result.failed_repair == 0
    invoice = await db["invoices"].find_one(
        {"academy_id": acad, "invoice_id": "inv-monthly-enroll-part-2026-06"}
    )
    assert invoice is not None
    # 10_000 gross - 3_000 (already spent) - 2_000 (topped up on the rerun).
    assert invoice["total_cents"] == 5_000
    assert invoice["balance_due_cents"] == 5_000
    assert await credits.balance_for_parent("parent-part") == 0
    # Both applications are durably recorded and their audit rows rebuilt.
    assert (
        await db["credit_applications"].count_documents(
            {"academy_id": acad, "invoice_id": "pay-part"}
        )
        == 2
    )

    replay = await repo.generate_monthly_payments("2026-06")

    assert replay.created == 0
    assert replay.failed_repair == 0
    assert await credits.balance_for_parent("parent-part") == 0
    assert (
        await db["invoices"].count_documents(
            {"academy_id": acad, "invoice_id": "inv-monthly-enroll-part-2026-06"}
        )
        == 1
    )


@pytest.mark.asyncio
async def test_generate_monthly_recovery_honours_tuition_discount_and_credit(db, acad) -> None:
    """Recovery must price from net, not gross (issue #233 follow-on).

    The normal path bills ``net - credit``. Recovery pricing from gross would
    overcharge a discounted family by the whole discount, and would let credit
    be consumed against the 2_000 of tuition they never owed.
    """
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
    # 10_000 gross, 2_000 off => 8_000 net.
    await db["enrollment_discounts"].insert_one(
        {
            "academy_id": acad,
            "discount_id": "disc-recover",
            "enrollment_id": "enroll-disc",
            "student_id": "student-disc",
            "category": "sibling",
            "kind": "amount_off",
            "amount_off_cents": 2_000,
            "effective_start": "2026-01-01",
            "status": "active",
        }
    )
    # Parent holds 9_000 of credit — more than the 8_000 net they actually owe.
    await credits.create(
        CreditLedgerEntry(
            credit_id="credit-disc",
            academy_id=acad,
            parent_id="parent-disc",
            student_id="student-disc",
            enrollment_id="enroll-disc",
            type="MANUAL_CREDIT",
            status="APPROVED",
            amount_cents=9_000,
            remaining_amount_cents=9_000,
            currency="usd",
            reason="goodwill",
            created_at=now,
            updated_at=now,
        )
    )
    await db["billing_invoice_keys"].insert_one(
        {
            "academy_id": acad,
            "invoice_key_id": "key-disc",
            "payment_id": "pay-disc",
            "enrollment_id": "enroll-disc",
            "period": "2026-06",
            "status": "claimed",
            "created_at": now,
            "updated_at": now,
        }
    )
    await _seed_monthly_enrollment(
        db,
        acad,
        enrollment_id="enroll-disc",
        session_id="sess-disc",
        student_id="student-disc",
        parent_id="parent-disc",
    )

    result = await repo.generate_monthly_payments("2026-06")

    assert result.failed_repair == 0
    invoice = await db["invoices"].find_one(
        {"academy_id": acad, "invoice_id": "inv-monthly-enroll-disc-2026-06"}
    )
    assert invoice is not None
    # 8_000 net fully covered by credit, so nothing is owed...
    assert invoice["total_cents"] == 0
    assert invoice["balance_due_cents"] == 0
    # ...and only the 8_000 they owed was taken, not the 10_000 gross.
    assert await credits.balance_for_parent("parent-disc") == 1_000


# ---------------------------------------------------------------------------
# BillingCalculationSnapshot TTL enforcement (issue #530)
# ---------------------------------------------------------------------------


def _quote_snapshot(calculated_at: datetime):
    from backend.v2.contexts.billing.domain.proration import BillingCalculationSnapshot

    return BillingCalculationSnapshot(
        monthly_price_cents=10_000,
        billing_period_start=datetime(2026, 6, 1, tzinfo=UTC),
        billing_period_end=datetime(2026, 7, 1, tzinfo=UTC),
        billing_period_label="2026-06",
        timezone="UTC",
        total_eligible_classes=8,
        billable_remaining_classes=4,
        proration_ratio="4/8",
        final_amount_cents=5_000,
        included_occurrence_ids=["sess-1:2026-06-15:18:00"],
        excluded_occurrences={},
        calculated_at=calculated_at,
        calculated_by="parent-1",
    )


@pytest.mark.asyncio
async def test_consume_within_ttl_transitions_open_to_consumed(db, acad) -> None:
    quoted_at = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    from datetime import timedelta

    repo = MongoPaymentRepository(db, clock=lambda: quoted_at + timedelta(minutes=5))
    stored = await repo.persist_open(
        snapshot=_quote_snapshot(quoted_at),
        session_id="sess-1",
        parent_id="parent-1",
        student_id=None,
        enrollment_id=None,
        ttl_minutes=15,
        now=quoted_at,
    )

    consumed = await repo.consume(str(stored.snapshot_id))

    assert consumed is not None
    assert consumed.status == "CONSUMED"
    doc = await db["billing_calculation_snapshots"].find_one(
        {"academy_id": acad, "snapshot_id": stored.snapshot_id}
    )
    assert doc["status"] == "CONSUMED"


@pytest.mark.asyncio
async def test_consume_refuses_expired_snapshot_and_stamps_expired(db, acad) -> None:
    """An OPEN quote past its 15-minute TTL must never be consumed — the TTL
    was previously decorative (issue #530). The doc is stamped EXPIRED so the
    audit trail explains the refusal instead of leaving the quote OPEN forever."""
    quoted_at = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    from datetime import timedelta

    repo = MongoPaymentRepository(db, clock=lambda: quoted_at + timedelta(minutes=16))
    stored = await repo.persist_open(
        snapshot=_quote_snapshot(quoted_at),
        session_id="sess-1",
        parent_id="parent-1",
        student_id=None,
        enrollment_id=None,
        ttl_minutes=15,
        now=quoted_at,
    )

    consumed = await repo.consume(str(stored.snapshot_id))

    assert consumed is None
    doc = await db["billing_calculation_snapshots"].find_one(
        {"academy_id": acad, "snapshot_id": stored.snapshot_id}
    )
    assert doc["status"] == "EXPIRED"
    # mongomock returns naive UTC datetimes; normalise before comparing.
    assert doc["expired_at"].replace(tzinfo=UTC) == quoted_at + timedelta(minutes=16)
    # A second consume attempt stays refused (no OPEN doc left).
    assert await repo.consume(str(stored.snapshot_id)) is None


@pytest.mark.asyncio
async def test_consume_legacy_snapshot_without_expires_at_still_works(db, acad) -> None:
    """Pre-#530 snapshots have no expires_at; they must stay consumable so
    in-flight quotes are not bricked by the deploy."""
    now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    repo = MongoPaymentRepository(db, clock=lambda: now)
    snapshot = _quote_snapshot(now).model_copy(
        update={"snapshot_id": "legacy-snap-1", "status": "OPEN", "expires_at": None}
    )
    await db["billing_calculation_snapshots"].insert_one(
        {**snapshot.model_dump(mode="python"), "academy_id": acad, "session_id": "sess-1"}
    )

    consumed = await repo.consume("legacy-snap-1")

    assert consumed is not None
    assert consumed.status == "CONSUMED"


@pytest.mark.asyncio
async def test_month_end_evening_enrollment_is_not_re_prorated_next_month(db, acad) -> None:
    """The generator's first-month gate must bucket billing_start locally.

    Regression for #541 (generator side). ``billing_start_at`` is the UTC
    instant recorded at checkout, but the period label it is compared against
    is a local month — and ``BillingPeriod.from_label`` two lines up builds
    the bounds in the session's timezone. Comparing the raw UTC label reads a
    month ahead for the several evening hours before local month-end.

    An enrollment created at 8:15pm Chicago on May 31 (01:15 UTC Jun 1) has a
    UTC label of "2026-06", so the June run misread it as a *first-month*
    enrollment and prorated June down to the classes remaining after the run
    date — undercharging a parent who attends the whole month, and who has
    already paid a prorated May at checkout. Locally the enrollment starts in
    May, so June is a full month of tuition.
    """
    repo = MongoPaymentRepository(
        db,
        # Mid-June run: if the gate wrongly takes the first-month branch the
        # proration drops every class before this instant, so the two branches
        # produce visibly different money.
        clock=lambda: datetime(2026, 6, 16, 12, 0, tzinfo=UTC),
        ledger_repo=MongoBillingLedgerRepository(db),
    )
    await _seed_monthly_enrollment(
        db,
        acad,
        enrollment_id="enroll-tz",
        session_id="sess-tz",
        student_id="student-tz",
        parent_id="parent-tz",
        extra_enrollment={
            # 2026-05-31 20:15 America/Chicago
            "billing_start_at": datetime(2026, 6, 1, 1, 15, tzinfo=UTC),
            "created_at": datetime(2026, 6, 1, 1, 15, tzinfo=UTC),
        },
    )

    result = await repo.generate_monthly_payments("2026-06")

    assert result.created == 1
    invoice = await db["invoices"].find_one({"academy_id": acad, "enrollment_id": "enroll-tz"})
    assert invoice is not None
    # Full monthly tuition, not a second proration.
    assert invoice["total_cents"] == 10_000
