"""Monthly invoice generation applies recurring tuition discounts (issue #244).

Phase 2A removed the legacy ``payments``-collection write; monthly generation
now writes only to the billing ledger. These tests therefore assert against the
generated ledger invoice (``invoices``), whose total reflects the discounted
net charge.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.contexts.billing.domain.tuition_discount import TuitionDiscount
from backend.v2.contexts.billing.infrastructure.mongo_billing_ledger_repo import (
    MongoBillingLedgerRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_payment_repo import (
    MongoPaymentRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_tuition_discount_repo import (
    MongoTuitionDiscountRepository,
)


def _fixed_clock(moment: datetime):
    """Return a zero-arg clock callable (avoids E731 lambda assignment)."""

    def _clock() -> datetime:
        return moment

    return _clock


def _payment_repo(db, clock) -> MongoPaymentRepository:
    """Monthly generation wired to the ledger (the only persistence today)."""
    return MongoPaymentRepository(
        db,
        clock=clock,
        ledger_repo=MongoBillingLedgerRepository(db, clock=clock),
    )


async def _monthly_invoice(db, acad, period: str) -> dict | None:
    return await db["invoices"].find_one(
        {"academy_id": acad, "enrollment_id": "enroll-1", "period": period}
    )


async def _seed_session_student_enrollment(db, acad, *, billing_start: datetime) -> None:
    await db["sessions"].insert_one(
        {
            "academy_id": acad,
            "session_id": "sess-1",
            "name": "Junior Badminton",
            "title": "Junior Badminton",
            "coach_id": "coach-1",
            "location": "Court 1",
            "start_date": "2026-05-01",
            "end_date": "2026-12-31",
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
            "session_id": "sess-1",
            "student_id": "student-1",
            "parent_id": "parent-1",
            "status": "active",
            "billing_type": "standard",
            "billing_start_at": billing_start,
            "created_at": billing_start,
        }
    )


async def _set_discount(db, *, clock, **policy_kw) -> None:
    repo = MongoTuitionDiscountRepository(db, clock=clock)
    base = dict(
        discount_id="disc-1",
        enrollment_id="enroll-1",
        student_id="student-1",
        category="scholarship",
        kind="waiver",
        effective_start="2026-01-01",
    )
    base.update(policy_kw)
    await repo.set_active(TuitionDiscount(**base), set_by="admin-1")


@pytest.mark.asyncio
async def test_full_month_percent_discount(db, acad) -> None:
    clock = _fixed_clock(datetime(2026, 6, 1, 12, 0, tzinfo=UTC))
    await _seed_session_student_enrollment(
        db, acad, billing_start=datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    )
    await _set_discount(db, clock=clock, category="sibling", kind="percent", percent_bps=1000)

    result = await _payment_repo(db, clock).generate_monthly_payments("2026-06")

    assert result.created == 1
    invoice = await _monthly_invoice(db, acad, "2026-06")
    assert invoice is not None
    # 10% off 10_000 -> net 9_000
    assert invoice["total_cents"] == 9_000
    assert invoice["balance_due_cents"] == 9_000


@pytest.mark.asyncio
async def test_full_month_waiver_still_records_row(db, acad) -> None:
    clock = _fixed_clock(datetime(2026, 6, 1, 12, 0, tzinfo=UTC))
    await _seed_session_student_enrollment(
        db, acad, billing_start=datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    )
    await _set_discount(db, clock=clock, category="scholarship", kind="waiver")

    result = await _payment_repo(db, clock).generate_monthly_payments("2026-06")

    # A full waiver still records an invoice (net 0), it is not skipped.
    assert result.created == 1
    invoice = await _monthly_invoice(db, acad, "2026-06")
    assert invoice is not None
    assert invoice["total_cents"] == 0
    assert invoice["balance_due_cents"] == 0


@pytest.mark.asyncio
async def test_first_month_proration_with_amount_off(db, acad) -> None:
    # Same scenario as the existing proration test: 3/9 classes remain.
    clock = _fixed_clock(datetime(2026, 5, 18, 22, 0, tzinfo=UTC))
    await _seed_session_student_enrollment(
        db, acad, billing_start=datetime(2026, 5, 18, 15, 0, tzinfo=UTC)
    )
    await _set_discount(db, clock=clock, kind="amount_off", amount_off_cents=4000)

    result = await _payment_repo(db, clock).generate_monthly_payments("2026-05")

    assert result.created == 1
    invoice = await _monthly_invoice(db, acad, "2026-05")
    assert invoice is not None
    # net_prorated = (10_000 - 4_000) * 3/9 = 2_000
    assert invoice["total_cents"] == 2_000
    assert invoice["balance_due_cents"] == 2_000


@pytest.mark.asyncio
async def test_no_policy_leaves_amount_unchanged(db, acad) -> None:
    clock = _fixed_clock(datetime(2026, 6, 1, 12, 0, tzinfo=UTC))
    await _seed_session_student_enrollment(
        db, acad, billing_start=datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    )

    result = await _payment_repo(db, clock).generate_monthly_payments("2026-06")

    assert result.created == 1
    invoice = await _monthly_invoice(db, acad, "2026-06")
    assert invoice is not None
    assert invoice["total_cents"] == 10_000
    assert invoice["balance_due_cents"] == 10_000


@pytest.mark.asyncio
async def test_idempotent_rerun_does_not_double_apply(db, acad) -> None:
    # The re-run guard depends on the unique invoice key index (enforced in prod;
    # created explicitly here for mongomock).
    await db["billing_invoice_keys"].create_index(
        [("academy_id", 1), ("enrollment_id", 1), ("period", 1)],
        unique=True,
        name="uniq_monthly_invoice_key",
    )
    clock = _fixed_clock(datetime(2026, 6, 1, 12, 0, tzinfo=UTC))
    await _seed_session_student_enrollment(
        db, acad, billing_start=datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    )
    await _set_discount(db, clock=clock, kind="percent", percent_bps=2500)

    repo = _payment_repo(db, clock)
    await repo.generate_monthly_payments("2026-06")
    second = await repo.generate_monthly_payments("2026-06")

    assert second.created == 0
    rows = await db["invoices"].count_documents(
        {"academy_id": acad, "enrollment_id": "enroll-1", "period": "2026-06"}
    )
    assert rows == 1
    invoice = await _monthly_invoice(db, acad, "2026-06")
    assert invoice is not None
    # 25% off 10_000 -> net 7_500
    assert invoice["total_cents"] == 7_500
    assert invoice["balance_due_cents"] == 7_500
