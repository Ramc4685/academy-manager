"""Percent-coach pay base = invoiced tuition per class and academy-local month (L7).

Runs on ``real_db`` (validators and indexes from the real migrations) with the
real ledger repository writing the invoices, so the read model sees the exact
line and header shapes the monthly generator stores.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from backend.v2.contexts.billing.domain.ledger import InvoiceLine, LedgerInvoice
from backend.v2.contexts.billing.infrastructure.invoiced_tuition_read_model import (
    MongoInvoicedTuitionReadModel,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_ledger_repo import (
    MongoBillingLedgerRepository,
)
from backend.v2.contexts.coaching.application.use_cases.compute_payout import (
    ComputeCoachPayout,
)
from backend.v2.contexts.coaching.infrastructure.mongo_payout_read_models import (
    MongoCoachRateLookup,
    MongoPayableOccurrenceQuery,
)

pytestmark = pytest.mark.asyncio

ACAD = "test-academy"
NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)
# Local October on the Central clock (CDT, UTC-5).
OCT_START, OCT_END = datetime(2026, 10, 1, 5, tzinfo=UTC), datetime(2026, 11, 1, 5, tzinfo=UTC)


async def _central(_academy_id: str) -> str:
    return "America/Chicago"


async def _invoice(
    db: Any,
    invoice_id: str,
    *,
    enrollment_id: str,
    lines: list[tuple[str, int] | tuple[str, int, str]],
    discount_cents: int = 0,
    status: str = "open",
    parent_id: str = "parent-1",
    period: str = "2026-10",
) -> None:
    subtotal = sum(cents for _, cents, *_ in lines if cents > 0)
    await MongoBillingLedgerRepository(db).create_invoice(
        LedgerInvoice(
            invoice_id=invoice_id,
            academy_id=ACAD,
            parent_id=parent_id,
            enrollment_id=enrollment_id,
            period=period,
            status=status,  # type: ignore[arg-type]
            subtotal_cents=subtotal,
            discount_cents=discount_cents,
            total_cents=max(0, subtotal - discount_cents),
            balance_due_cents=max(0, subtotal - discount_cents),
            currency="usd",
            due_date=date(2026, 10, 8),
            created_at=NOW,
            updated_at=NOW,
        ),
        lines=[
            InvoiceLine(
                line_id=f"{invoice_id}-{index}",
                academy_id=ACAD,
                invoice_id=invoice_id,
                line_type=line[0],
                description=line[0],
                quantity=1,
                unit_amount_cents=line[1],
                amount_cents=line[1],
                source_type=line[2] if len(line) > 2 else None,
                created_at=NOW,
            )
            for index, line in enumerate(lines)
        ],
        idempotency_key=f"seed:{invoice_id}",
    )


async def _enroll(db: Any, enrollment_id: str, session_id: str, status: str = "active") -> None:
    await db["enrollments"].insert_one(
        {
            "academy_id": ACAD,
            "enrollment_id": enrollment_id,
            "student_id": f"student-{enrollment_id}",
            "session_id": session_id,
            "status": status,
        }
    )


async def _occurrences(
    db: Any, session_id: str, starts: list[datetime], *, cancelled: tuple[int, ...] = ()
) -> None:
    await db["session_occurrences"].insert_many(
        [
            {
                "academy_id": ACAD,
                "occurrence_id": f"{session_id}-occ-{index}",
                "session_id": session_id,
                "start_at": start,
                "end_at": start + timedelta(hours=1),
                "status": "cancelled" if index in cancelled else "completed",
                "scheduled_coach_id": "coach-1",
                "is_payable": True,
            }
            for index, start in enumerate(starts)
        ]
    )


async def _settings(db: Any, **fields: Any) -> None:
    await db["billing_settings"].update_one(
        {"academy_id": ACAD}, {"$set": {"academy_id": ACAD, **fields}}, upsert=True
    )


async def _shares(db: Any) -> dict[str, int | None]:
    rows = await MongoPayableOccurrenceQuery(
        db, tuition=MongoInvoicedTuitionReadModel(db), academy_timezone=_central
    ).list_in_period(ACAD, OCT_START, OCT_END)
    return {row.occurrence_id: row.expected_revenue_minor for row in rows}


def _tuesdays(n: int = 4) -> list[datetime]:
    return [datetime(2026, 10, 6 + 7 * i, 23, tzinfo=UTC) for i in range(n)]


async def test_basis_nets_tuition_discounts_and_leaves_out_everything_else(real_db, acad) -> None:
    await _enroll(real_db, "enr-a", "sess-1")
    await _enroll(real_db, "enr-b", "sess-1")
    await _enroll(real_db, "enr-c", "sess-1")
    await _enroll(real_db, "enr-d", "sess-1")
    # Sibling discount nets in; referral credit (account credit), ACH, late fee,
    # move proration and an adjustment stay out: 10000 - 1000 = 9000.
    await _invoice(
        real_db,
        "inv-a",
        enrollment_id="enr-a",
        discount_cents=1000,
        lines=[
            ("tuition", 10_000),
            ("discount", -1_000, "tuition_discount"),
            ("credit", -2_000, "account_credit"),
            ("ach_discount", -300),
            ("late_fee", 1_500),
            ("move_proration", 500),
            ("adjustment", 700),
        ],
    )
    # Header-only discount with no line: 8000 - 800.
    await _invoice(
        real_db, "inv-b", enrollment_id="enr-b", discount_cents=800, lines=[("tuition", 8_000)]
    )
    # A full waiver nets to 0 and still marks the class-month as invoiced.
    await _invoice(
        real_db,
        "inv-c",
        enrollment_id="enr-c",
        discount_cents=5_000,
        lines=[("tuition", 5_000), ("discount", -5_000, "tuition_discount")],
    )
    # Void, draft and deleted invoices never count.
    await _invoice(
        real_db, "inv-void", enrollment_id="enr-d", status="void", lines=[("tuition", 9)]
    )
    await _invoice(
        real_db, "inv-draft", enrollment_id="enr-d", status="draft", lines=[("tuition", 9)]
    )
    await _invoice(
        real_db, "inv-del", enrollment_id="enr-d", period="2026-10", lines=[("tuition", 9)]
    )
    await real_db["invoices"].update_one({"invoice_id": "inv-del"}, {"$set": {"is_deleted": True}})
    # Another month and another class stay in their own buckets.
    await _invoice(
        real_db, "inv-nov", enrollment_id="enr-a", period="2026-11", lines=[("tuition", 777)]
    )

    model = MongoInvoicedTuitionReadModel(real_db)
    basis = await model.tuition_by_class_month(
        academy_id=ACAD, session_ids=["sess-1"], months=["2026-10", "2026-11"]
    )
    assert basis.amounts == {("sess-1", "2026-10"): 16_200, ("sess-1", "2026-11"): 777}
    assert (basis.cancelled_class_share, basis.missing_invoices) == ("ran_only", "block")

    await _settings(real_db, payroll_ach_discount_reduces_base=True)
    basis = await model.tuition_by_class_month(
        academy_id=ACAD, session_ids=["sess-1"], months=["2026-10"]
    )
    assert basis.amounts == {("sess-1", "2026-10"): 15_900}


async def test_checkout_first_month_counts_once_and_follows_the_setting(real_db, acad) -> None:
    await _enroll(real_db, "enr-2", "sess-1")
    # Family 2 has a ledger invoice for October: their checkout must not add again.
    await _invoice(
        real_db, "inv-2", enrollment_id="enr-2", parent_id="parent-2", lines=[("tuition", 10_000)]
    )
    payments = [
        ("pay-1", "parent-1", "snap-1", "succeeded"),
        ("pay-2", "parent-2", "snap-2", "succeeded"),
        ("pay-3", "parent-3", "snap-3", "pending"),
    ]
    for payment_id, parent_id, snapshot_id, status in payments:
        await real_db["payments"].insert_one(
            {
                "payment_id": payment_id,
                "academy_id": ACAD,
                "parent_id": parent_id,
                "session_id": "sess-1",
                "calculation_snapshot_id": snapshot_id,
                "amount_cents": 4_000,
                "status": status,
                "created_at": NOW,
                "updated_at": NOW,
            }
        )
        await real_db["billing_calculation_snapshots"].insert_one(
            {
                "academy_id": ACAD,
                "snapshot_id": snapshot_id,
                "calculation_type": "FIRST_MONTH_PRORATION",
                "billing_period_label": "2026-10",
                "final_amount_cents": 4_000,
                "status": "CONSUMED",
            }
        )

    model = MongoInvoicedTuitionReadModel(real_db)
    basis = await model.tuition_by_class_month(
        academy_id=ACAD, session_ids=["sess-1"], months=["2026-10"]
    )
    assert basis.amounts == {("sess-1", "2026-10"): 14_000}

    await _settings(real_db, payroll_count_checkout_first_month=False)
    basis = await model.tuition_by_class_month(
        academy_id=ACAD, session_ids=["sess-1"], months=["2026-10"]
    )
    assert basis.amounts == {("sess-1", "2026-10"): 10_000}


async def test_shares_bucket_on_the_academy_clock_and_sum_to_the_basis(real_db, acad) -> None:
    # Saturdays at 7pm Central. Oct 31 7pm CDT is Nov 1 00:00 UTC: it is an
    # October class and shares October's tuition.
    starts = [datetime(2026, 10, 4, 0, tzinfo=UTC) + timedelta(weeks=i) for i in range(5)]
    assert starts[-1] == datetime(2026, 11, 1, 0, tzinfo=UTC)
    await _occurrences(real_db, "sess-1", starts)
    # The family dropped on the 25th: the invoice they were billed still counts.
    await _enroll(real_db, "enr-1", "sess-1", status="dropped")
    await _invoice(real_db, "inv-1", enrollment_id="enr-1", lines=[("tuition", 10_001)])

    shares = await _shares(real_db)

    assert len(shares) == 5
    assert sum(v or 0 for v in shares.values()) == 10_001
    assert shares["sess-1-occ-0"] == 2_001  # the remainder cent goes to the earliest class
    assert shares["sess-1-occ-4"] == 2_000


async def test_cancelled_classes_follow_the_share_setting(real_db, acad) -> None:
    await _occurrences(real_db, "sess-1", _tuesdays(), cancelled=(3,))
    await _enroll(real_db, "enr-1", "sess-1")
    await _invoice(real_db, "inv-1", enrollment_id="enr-1", lines=[("tuition", 9_000)])

    ran_only = await _shares(real_db)
    assert ran_only == {
        "sess-1-occ-0": 3_000,
        "sess-1-occ-1": 3_000,
        "sess-1-occ-2": 3_000,
        "sess-1-occ-3": None,
    }

    await _settings(real_db, payroll_cancelled_class_share="all_scheduled")
    assert set((await _shares(real_db)).values()) == {2_250}


async def test_an_uninvoiced_class_month_blocks_unless_the_academy_pays_zero(real_db, acad) -> None:
    await _occurrences(real_db, "sess-1", _tuesdays(2))

    assert set((await _shares(real_db)).values()) == {None}

    await _settings(real_db, payroll_missing_invoices="pay_zero")
    assert set((await _shares(real_db)).values()) == {0}


async def test_percent_coach_is_paid_on_the_invoiced_share(real_db, acad) -> None:
    await _occurrences(real_db, "sess-1", _tuesdays(1))
    await _enroll(real_db, "enr-1", "sess-1")
    await _invoice(real_db, "inv-1", enrollment_id="enr-1", lines=[("tuition", 6_000)])
    # Legacy seeded rate fields still read as a percent rate.
    await real_db["coach_rates"].insert_one(
        {
            "academy_id": ACAD,
            "rate_id": "rate-legacy",
            "coach_id": "coach-1",
            "rate_type": "percentage_of_expected_revenue",
            "percentage": 30.0,
            "per_session_cents": 2500,
            "effective_from": datetime(2026, 9, 1, tzinfo=UTC),
            "status": "active",
        }
    )

    statement = await ComputeCoachPayout(
        occurrences=MongoPayableOccurrenceQuery(
            real_db, tuition=MongoInvoicedTuitionReadModel(real_db), academy_timezone=_central
        ),
        rates=MongoCoachRateLookup(real_db),
    ).execute(coach_id="coach-1", academy_id=ACAD, period_start=OCT_START, period_end=OCT_END)

    assert statement.total_minor == 1_800
    assert statement.lines[0].percent_bps == 3_000
    assert statement.lines[0].expected_revenue_minor == 6_000
