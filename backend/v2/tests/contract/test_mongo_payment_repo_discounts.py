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
async def test_discounted_invoice_records_discount_line_and_gross_net_identity(db, acad) -> None:
    clock = _fixed_clock(datetime(2026, 6, 1, 12, 0, tzinfo=UTC))
    await _seed_session_student_enrollment(
        db, acad, billing_start=datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    )
    await _set_discount(db, clock=clock, category="sibling", kind="percent", percent_bps=1000)

    result = await _payment_repo(db, clock).generate_monthly_payments("2026-06")

    assert result.created == 1
    invoice = await _monthly_invoice(db, acad, "2026-06")
    assert invoice is not None
    assert invoice["subtotal_cents"] == 10_000
    assert invoice["discount_cents"] == 1_000
    assert invoice["total_cents"] == 9_000
    assert invoice["total_cents"] == invoice["subtotal_cents"] - invoice["discount_cents"]

    lines = [
        doc
        async for doc in db["invoice_lines"].find(
            {"academy_id": acad, "invoice_id": invoice["invoice_id"]},
            sort=[("line_type", -1)],
        )
    ]
    assert [(line["line_type"], line["amount_cents"]) for line in lines] == [
        ("tuition", 10_000),
        ("discount", -1_000),
    ]
    discount_line = next(line for line in lines if line["line_type"] == "discount")
    assert discount_line["description"] == "Sibling discount"
    assert discount_line["source_type"] == "tuition_discount"
    assert discount_line["source_id"] == "disc-1"
    assert discount_line["category"] == "sibling"
    assert discount_line["discount_kind"] == "percent"
    assert "note" not in discount_line


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


async def _unique_invoice_key_index(db) -> None:
    """The DuplicateKeyError that drives orphan recovery needs the prod unique index."""
    await db["billing_invoice_keys"].create_index(
        [("academy_id", 1), ("enrollment_id", 1), ("period", 1)],
        unique=True,
        name="uniq_monthly_invoice_key",
    )


async def _monthly_lines(db, acad, invoice_id: str) -> list[tuple[str, int]]:
    return [
        (doc["line_type"], doc["amount_cents"])
        async for doc in db["invoice_lines"].find(
            {"academy_id": acad, "invoice_id": invoice_id},
            sort=[("line_type", -1)],
        )
    ]


@pytest.mark.asyncio
async def test_orphan_key_recovery_writes_same_shape_as_normal_generation(db, acad) -> None:
    """A recovered invoice is indistinguishable from a normally generated one.

    Recovery used to record the tuition line and subtotal net of the discount, with
    discount_cents 0 and no discount line, so line-level reporting disagreed with the
    normal path for the same enrollment/period.
    """
    await _unique_invoice_key_index(db)
    clock = _fixed_clock(datetime(2026, 6, 1, 12, 0, tzinfo=UTC))
    await _seed_session_student_enrollment(
        db, acad, billing_start=datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    )
    await _set_discount(db, clock=clock, category="sibling", kind="percent", percent_bps=1000)
    await db["billing_invoice_keys"].insert_one(
        {
            "academy_id": acad,
            "invoice_key_id": "key-orphan-discount",
            "payment_id": "pay-orphan-discount",
            "enrollment_id": "enroll-1",
            "period": "2026-06",
            "status": "claimed",
            "created_at": datetime(2026, 5, 20, tzinfo=UTC),
            "updated_at": datetime(2026, 5, 20, tzinfo=UTC),
        }
    )

    result = await _payment_repo(db, clock).generate_monthly_payments("2026-06")

    assert result.repaired_orphan_keys == 1
    assert result.failed_repair == 0
    invoice = await _monthly_invoice(db, acad, "2026-06")
    assert invoice is not None
    assert invoice["subtotal_cents"] == 10_000
    assert invoice["discount_cents"] == 1_000
    assert invoice["total_cents"] == 9_000
    assert invoice["balance_due_cents"] == 9_000
    assert await _monthly_lines(db, acad, invoice["invoice_id"]) == [
        ("tuition", 10_000),
        ("discount", -1_000),
    ]
    key = await db["billing_invoice_keys"].find_one(
        {"academy_id": acad, "enrollment_id": "enroll-1", "period": "2026-06"}
    )
    assert key is not None
    assert key["status"] == "complete"


@pytest.mark.asyncio
async def test_partial_invoice_repair_restates_header_for_discounted_charge(db, acad) -> None:
    """Back-filling the missing lines must not leave the header disagreeing with them.

    ``create_invoice`` recomputes an existing header from its lines, which subtracts a
    discount line and ``discount_cents`` twice; recovery restates the header itself.
    """
    await _unique_invoice_key_index(db)
    clock = _fixed_clock(datetime(2026, 6, 1, 12, 0, tzinfo=UTC))
    await _seed_session_student_enrollment(
        db, acad, billing_start=datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    )
    await _set_discount(db, clock=clock, category="sibling", kind="percent", percent_bps=1000)
    now = datetime(2026, 5, 20, tzinfo=UTC)
    await db["billing_invoice_keys"].insert_one(
        {
            "academy_id": acad,
            "invoice_key_id": "key-partial-discount",
            "payment_id": "pay-partial-discount",
            "enrollment_id": "enroll-1",
            "period": "2026-06",
            "status": "claimed",
            "created_at": now,
            "updated_at": now,
        }
    )
    await db["invoices"].insert_one(
        {
            "academy_id": acad,
            "invoice_id": "inv-monthly-enroll-1-2026-06",
            "parent_id": "parent-1",
            "student_id": "student-1",
            "enrollment_id": "enroll-1",
            "period": "2026-06",
            "status": "open",
            "subtotal_cents": 10_000,
            "discount_cents": 0,
            "total_cents": 10_000,
            "balance_due_cents": 10_000,
            "currency": "usd",
            "due_date": datetime(2026, 6, 30, tzinfo=UTC),
            "delivery_status": "not_sent",
            "sent_at": None,
            "last_sent_at": None,
            "finalized_at": None,
            "created_at": now,
            "updated_at": now,
            "idempotency_key": "monthly-ledger-enroll-1-2026-06",
        }
    )

    result = await _payment_repo(db, clock).generate_monthly_payments("2026-06")

    assert result.repaired_partial_invoices == 1
    assert result.failed_repair == 0
    invoice = await _monthly_invoice(db, acad, "2026-06")
    assert invoice is not None
    assert invoice["subtotal_cents"] == 10_000
    assert invoice["discount_cents"] == 1_000
    assert invoice["total_cents"] == 9_000
    assert invoice["balance_due_cents"] == 9_000
    assert await _monthly_lines(db, acad, invoice["invoice_id"]) == [
        ("tuition", 10_000),
        ("discount", -1_000),
    ]


@pytest.mark.asyncio
async def test_stale_net_shaped_invoice_is_left_untouched_for_review(db, acad) -> None:
    """An invoice recovered under the old net-of-credit shape is not silently rewritten.

    Its tuition line cannot be corrected ($setOnInsert), so back-filling a discount line
    around it would drag the recomputed header away from both the old and the new shape.
    Recovery bails before writing and reports the key for an operator instead.
    """
    await _unique_invoice_key_index(db)
    clock = _fixed_clock(datetime(2026, 6, 1, 12, 0, tzinfo=UTC))
    await _seed_session_student_enrollment(
        db, acad, billing_start=datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    )
    await _set_discount(db, clock=clock, category="sibling", kind="percent", percent_bps=1000)
    now = datetime(2026, 5, 20, tzinfo=UTC)
    await db["billing_invoice_keys"].insert_one(
        {
            "academy_id": acad,
            "invoice_key_id": "key-legacy-net",
            "payment_id": "pay-legacy-net",
            "enrollment_id": "enroll-1",
            "period": "2026-06",
            "status": "claimed",
            "created_at": now,
            "updated_at": now,
        }
    )
    await db["invoices"].insert_one(
        {
            "academy_id": acad,
            "invoice_id": "inv-monthly-enroll-1-2026-06",
            "parent_id": "parent-1",
            "student_id": "student-1",
            "enrollment_id": "enroll-1",
            "period": "2026-06",
            "status": "open",
            "subtotal_cents": 9_000,
            "discount_cents": 0,
            "total_cents": 9_000,
            "balance_due_cents": 9_000,
            "currency": "usd",
            "due_date": datetime(2026, 6, 30, tzinfo=UTC),
            "delivery_status": "not_sent",
            "sent_at": None,
            "last_sent_at": None,
            "finalized_at": None,
            "created_at": now,
            "updated_at": now,
            "idempotency_key": "monthly-ledger-enroll-1-2026-06",
        }
    )
    await db["invoice_lines"].insert_one(
        {
            "academy_id": acad,
            "invoice_id": "inv-monthly-enroll-1-2026-06",
            "line_id": "line-monthly-enroll-1-2026-06",
            "line_type": "tuition",
            "description": "Monthly tuition 2026-06",
            "quantity": 1,
            "unit_amount_cents": 9_000,
            "amount_cents": 9_000,
            "source_type": "payment",
            "source_id": "pay-legacy-net",
            "created_at": now,
            "idempotency_key": "monthly-ledger-enroll-1-2026-06",
        }
    )

    result = await _payment_repo(db, clock).generate_monthly_payments("2026-06")

    assert result.failed_repair == 1
    assert result.created == 0
    invoice = await _monthly_invoice(db, acad, "2026-06")
    assert invoice is not None
    assert invoice["subtotal_cents"] == 9_000
    assert invoice["total_cents"] == 9_000
    assert invoice["balance_due_cents"] == 9_000
    assert await _monthly_lines(db, acad, invoice["invoice_id"]) == [("tuition", 9_000)]
    key = await db["billing_invoice_keys"].find_one(
        {"academy_id": acad, "enrollment_id": "enroll-1", "period": "2026-06"}
    )
    assert key is not None
    assert key["status"] == "repair_failed"
