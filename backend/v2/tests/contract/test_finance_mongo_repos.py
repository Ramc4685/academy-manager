"""Contract tests for finance-context Mongo repositories (Wave 5A).

Two repo groups under test:

1. ``MongoPayoutPeriodRepository`` — persisted payout period + lines,
   including the natural-key idempotency and tenant isolation.
2. The three snapshot repos —
   ``MongoAcademyRevenueSnapshotRepository``,
   ``MongoSessionAttendanceSnapshotRepository``,
   ``MongoCoachPayoutSnapshotRepository`` — natural-key upsert and
   cross-tenant isolation.

We use ``mongomock-motor`` (same as the existing contract suite) and
exercise the repos through the tenant ContextVar fixtures from
``conftest.py``.
"""

from __future__ import annotations

import importlib
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from backend.v2.contexts.billing.application.use_cases.finance import (
    MongoTuitionDiscountSummaryQuery,
)
from backend.v2.contexts.finance.domain.payout_period import (
    PayoutPeriod,
    PayoutWarning,
    PersistedPayoutLine,
)
from backend.v2.contexts.finance.domain.reporting_snapshots import (
    AcademyRevenueSnapshot,
    CoachPayoutSnapshot,
    SessionAttendanceSnapshot,
)
from backend.v2.contexts.finance.infrastructure.mongo_payout_period_repo import (
    MongoPayoutPeriodRepository,
)
from backend.v2.contexts.finance.infrastructure.mongo_reporting_snapshot_repos import (
    MongoAcademyRevenueSnapshotRepository,
    MongoCoachPayoutSnapshotRepository,
    MongoSessionAttendanceSnapshotRepository,
)
from backend.v2.shared.tenancy.context import _current as _tenant_var


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


def _make_period(
    *,
    period_id: str = "pp-1",
    academy_id: str = "test-academy",
    coach_id: str = "coach-A",
    period_start: datetime | None = None,
    period_end: datetime | None = None,
    total: int = 5000,
    line_count: int = 1,
    payout_warnings: list[PayoutWarning] | None = None,
) -> PayoutPeriod:
    period_start = period_start or _dt("2026-05-01T00:00:00")
    period_end = period_end or _dt("2026-06-01T00:00:00")
    if line_count > 0:
        line_amount = total // line_count
        lines = [
            PersistedPayoutLine(
                occurrence_id=f"occ-{i}",
                coach_id=coach_id,
                basis="scheduled",
                minutes=Decimal("60"),
                amount_minor=line_amount,
                currency="USD",
                rate_id="cr-1",
            )
            for i in range(line_count)
        ]
        # Top up the last line to make the sum match exactly.
        sum_so_far = sum(line.amount_minor for line in lines)
        if sum_so_far != total and lines:
            last = lines[-1]
            lines[-1] = PersistedPayoutLine(
                occurrence_id=last.occurrence_id,
                coach_id=last.coach_id,
                basis=last.basis,
                minutes=last.minutes,
                amount_minor=last.amount_minor + (total - sum_so_far),
                currency=last.currency,
                rate_id=last.rate_id,
            )
    else:
        lines = []
    return PayoutPeriod(
        period_id=period_id,
        academy_id=academy_id,
        coach_id=coach_id,
        period_start=period_start,
        period_end=period_end,
        currency="USD",
        total_minor=total,
        lines=lines,
        payout_warnings=payout_warnings or [],
        generated_at=_dt("2026-06-01T00:00:00"),
    )


def _warning(**overrides) -> PayoutWarning:
    base = dict(
        occurrence_id="occ-warning",
        reason="missing_session_price_for_percent_revenue",
        severity="blocking",
        message="Missing session price for percent-of-revenue pay.",
        occurred_at=_dt("2026-05-10T18:00:00"),
        session_id="sess-1",
        session_title="Junior Squad",
        coach_id="coach-A",
        repair_action="set_session_fee_and_recompute",
    )
    base.update(overrides)
    return PayoutWarning(**base)


# ---------------------------------------------------------------------------
# Tuition discount summary query
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tuition_discount_summary_groups_discount_lines_by_category(db, acad) -> None:
    await db["invoices"].insert_many(
        [
            {
                "academy_id": acad,
                "invoice_id": "inv-1",
                "parent_id": "parent-1",
                "student_id": "student-1",
                "enrollment_id": "enroll-1",
                "period": "2026-06",
                "status": "open",
                "subtotal_cents": 10_000,
                "discount_cents": 1_000,
                "total_cents": 9_000,
                "balance_due_cents": 9_000,
                "currency": "usd",
                "due_date": _dt("2026-06-30T00:00:00"),
                "created_at": _dt("2026-06-01T00:00:00"),
                "updated_at": _dt("2026-06-01T00:00:00"),
            },
            {
                "academy_id": acad,
                "invoice_id": "inv-2",
                "parent_id": "parent-2",
                "student_id": "student-2",
                "enrollment_id": "enroll-2",
                "period": "2026-06",
                "status": "open",
                "subtotal_cents": 12_000,
                "discount_cents": 12_000,
                "total_cents": 0,
                "balance_due_cents": 0,
                "currency": "usd",
                "due_date": _dt("2026-06-30T00:00:00"),
                "created_at": _dt("2026-06-01T00:00:00"),
                "updated_at": _dt("2026-06-01T00:00:00"),
            },
            {
                "academy_id": "other-academy",
                "invoice_id": "inv-other",
                "parent_id": "parent-other",
                "period": "2026-06",
                "status": "open",
                "subtotal_cents": 99_000,
                "discount_cents": 99_000,
                "total_cents": 0,
                "balance_due_cents": 0,
                "currency": "usd",
                "due_date": _dt("2026-06-30T00:00:00"),
                "created_at": _dt("2026-06-01T00:00:00"),
                "updated_at": _dt("2026-06-01T00:00:00"),
            },
        ]
    )
    await db["invoice_lines"].insert_many(
        [
            {
                "academy_id": acad,
                "invoice_id": "inv-1",
                "line_id": "line-tuition-1",
                "line_type": "tuition",
                "description": "Monthly tuition",
                "quantity": 1,
                "unit_amount_cents": 10_000,
                "amount_cents": 10_000,
                "created_at": _dt("2026-06-01T00:00:00"),
            },
            {
                "academy_id": acad,
                "invoice_id": "inv-1",
                "line_id": "line-discount-1",
                "line_type": "discount",
                "description": "Sibling discount",
                "quantity": 1,
                "unit_amount_cents": -1_000,
                "amount_cents": -1_000,
                "source_type": "tuition_discount",
                "source_id": "disc-1",
                "category": "sibling",
                "created_at": _dt("2026-06-01T00:00:00"),
            },
            {
                "academy_id": acad,
                "invoice_id": "inv-2",
                "line_id": "line-tuition-2",
                "line_type": "tuition",
                "description": "Monthly tuition",
                "quantity": 1,
                "unit_amount_cents": 12_000,
                "amount_cents": 12_000,
                "created_at": _dt("2026-06-01T00:00:00"),
            },
            {
                "academy_id": acad,
                "invoice_id": "inv-2",
                "line_id": "line-discount-2",
                "line_type": "discount",
                "description": "Scholarship discount",
                "quantity": 1,
                "unit_amount_cents": -12_000,
                "amount_cents": -12_000,
                "source_type": "tuition_discount",
                "source_id": "disc-2",
                "category": "scholarship",
                "created_at": _dt("2026-06-01T00:00:00"),
            },
            {
                "academy_id": "other-academy",
                "invoice_id": "inv-other",
                "line_id": "line-other",
                "line_type": "discount",
                "description": "Scholarship discount",
                "quantity": 1,
                "unit_amount_cents": -99_000,
                "amount_cents": -99_000,
                "source_type": "tuition_discount",
                "source_id": "disc-other",
                "category": "scholarship",
                "created_at": _dt("2026-06-01T00:00:00"),
            },
        ]
    )

    summary = await MongoTuitionDiscountSummaryQuery(db).execute("2026-06")

    assert summary.period == "2026-06"
    assert summary.gross_tuition_cents == 22_000
    assert summary.discount_cents == 13_000
    assert summary.net_tuition_cents == 9_000
    assert [(row.category, row.discount_cents) for row in summary.by_category] == [
        ("scholarship", 12_000),
        ("sibling", 1_000),
    ]


# ---------------------------------------------------------------------------
# PayoutPeriod repo
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_and_find_by_window_round_trips(db, acad) -> None:
    repo = MongoPayoutPeriodRepository(db)
    saved = await repo.save(_make_period(line_count=2, total=10_000))

    fetched = await repo.find_by_window(
        coach_id="coach-A",
        period_start=_dt("2026-05-01T00:00:00"),
        period_end=_dt("2026-06-01T00:00:00"),
    )
    assert fetched is not None
    assert fetched.period_id == saved.period_id
    assert fetched.total_minor == 10_000
    assert len(fetched.lines) == 2


@pytest.mark.asyncio
async def test_find_overlapping_detects_intersecting_window(db, acad) -> None:
    repo = MongoPayoutPeriodRepository(db)
    saved = await repo.save(_make_period())  # May 2026

    # A one-week window inside May intersects the saved period.
    overlap = await repo.find_overlapping(
        coach_id="coach-A",
        period_start=_dt("2026-05-04T00:00:00"),
        period_end=_dt("2026-05-11T00:00:00"),
    )
    assert overlap is not None
    assert overlap.period_id == saved.period_id

    # An adjacent June window does not ([start, end) semantics).
    assert (
        await repo.find_overlapping(
            coach_id="coach-A",
            period_start=_dt("2026-06-01T00:00:00"),
            period_end=_dt("2026-07-01T00:00:00"),
        )
        is None
    )

    # Another coach is unaffected.
    assert (
        await repo.find_overlapping(
            coach_id="coach-B",
            period_start=_dt("2026-05-04T00:00:00"),
            period_end=_dt("2026-05-11T00:00:00"),
        )
        is None
    )


@pytest.mark.asyncio
async def test_payout_warnings_round_trip_and_legacy_docs_hydrate(db, acad) -> None:
    repo = MongoPayoutPeriodRepository(db)
    saved = await repo.save(
        _make_period(
            line_count=0,
            total=0,
            payout_warnings=[_warning(occurrence_id="occ-no-price")],
        )
    )

    fetched = await repo.find_by_id(saved.period_id)
    assert fetched is not None
    assert fetched.unpaid_occurrence_ids == []
    assert [warning.occurrence_id for warning in fetched.payout_warnings] == ["occ-no-price"]
    assert fetched.payout_warnings[0].reason == "missing_session_price_for_percent_revenue"

    await db["payout_periods"].insert_one(
        {
            "academy_id": "test-academy",
            "period_id": "pp-legacy-unpaid",
            "coach_id": "coach-A",
            "period_start": _dt("2026-07-01T00:00:00"),
            "period_end": _dt("2026-08-01T00:00:00"),
            "status": "draft",
            "currency": "USD",
            "total_minor": 0,
            "unpaid_occurrence_ids": ["occ-legacy"],
            "generated_at": _dt("2026-08-01T00:00:00"),
        }
    )
    legacy = await repo.find_by_id("pp-legacy-unpaid")
    assert legacy is not None
    assert legacy.unpaid_occurrence_ids == ["occ-legacy"]
    assert legacy.payout_warnings == []


@pytest.mark.asyncio
async def test_replaced_occurrence_row_round_trips(db, acad) -> None:
    """The displaced-coach trace and who was paid instead must persist (#228)."""
    from backend.v2.contexts.finance.domain.payout_period import PersistedUnpaidOccurrence

    repo = MongoPayoutPeriodRepository(db)
    saved = await repo.save(
        _make_period(line_count=0, total=0).model_copy(
            update={
                "unpaid_occurrences": [
                    PersistedUnpaidOccurrence(
                        occurrence_id="occ-replaced",
                        reason="replaced_by_actual_coach",
                        detail="Scheduled coach was replaced.",
                        unresolved=False,
                        attributed_coach_id="coach-B",
                    )
                ]
            }
        )
    )

    fetched = await repo.find_by_id(saved.period_id)
    assert fetched is not None
    row = fetched.unpaid_occurrences[0]
    assert row.reason == "replaced_by_actual_coach"
    assert row.attributed_coach_id == "coach-B"
    assert row.unresolved is False
    assert fetched.unpaid_occurrence_ids == []


@pytest.mark.asyncio
async def test_save_is_idempotent_on_natural_key(db, acad) -> None:
    repo = MongoPayoutPeriodRepository(db)
    first = await repo.save(_make_period(period_id="pp-1"))
    # A second save with a different ``period_id`` but same natural key
    # must return the original, not create a duplicate.
    second = await repo.save(_make_period(period_id="pp-2"))
    assert first.period_id == second.period_id == "pp-1"

    count = await db["payout_periods"].count_documents({"academy_id": "test-academy"})
    assert count == 1


@pytest.mark.asyncio
async def test_find_by_window_does_not_leak_across_tenants(db, acad) -> None:
    repo = MongoPayoutPeriodRepository(db)
    await repo.save(_make_period(period_id="pp-1", academy_id="test-academy"))

    # Same window, different tenant.
    token = _tenant_var.set("other-academy")
    try:
        other_repo = MongoPayoutPeriodRepository(db)
        await other_repo.save(_make_period(period_id="pp-2", academy_id="other-academy"))
        result_other = await other_repo.find_by_window(
            coach_id="coach-A",
            period_start=_dt("2026-05-01T00:00:00"),
            period_end=_dt("2026-06-01T00:00:00"),
        )
        assert result_other is not None
        assert result_other.period_id == "pp-2"
    finally:
        _tenant_var.reset(token)

    # Back in the original tenant scope.
    result = await repo.find_by_window(
        coach_id="coach-A",
        period_start=_dt("2026-05-01T00:00:00"),
        period_end=_dt("2026-06-01T00:00:00"),
    )
    assert result is not None
    assert result.period_id == "pp-1"


@pytest.mark.asyncio
async def test_replace_persists_state_transition(db, acad) -> None:
    repo = MongoPayoutPeriodRepository(db)
    saved = await repo.save(_make_period())
    updated = saved.model_copy(
        update={"status": "approved", "approved_at": _dt("2026-06-02T12:00:00")}
    )
    replaced = await repo.replace(updated, expected_status="draft")
    assert replaced.status == "approved"

    fetched = await repo.find_by_id(saved.period_id)
    assert fetched is not None
    assert fetched.status == "approved"
    # Hydration re-attaches UTC to the naive datetimes the driver returns.
    assert fetched.approved_at == _dt("2026-06-02T12:00:00")


@pytest.mark.asyncio
async def test_replace_missing_period_raises(db, acad) -> None:
    repo = MongoPayoutPeriodRepository(db)
    period = _make_period(period_id="pp-missing")
    with pytest.raises(LookupError):
        await repo.replace(period, expected_status="draft")


@pytest.mark.asyncio
async def test_lines_persist_with_decimal_minutes(db, acad) -> None:
    repo = MongoPayoutPeriodRepository(db)
    period = PayoutPeriod(
        period_id="pp-dec",
        academy_id="test-academy",
        coach_id="coach-A",
        period_start=_dt("2026-05-01T00:00:00"),
        period_end=_dt("2026-06-01T00:00:00"),
        currency="USD",
        total_minor=7500,
        lines=[
            PersistedPayoutLine(
                occurrence_id="occ-frac",
                coach_id="coach-A",
                basis="scheduled",
                minutes=Decimal("90.0000"),
                amount_minor=7500,
                currency="USD",
                rate_id="cr-1",
            )
        ],
        generated_at=_dt("2026-06-01T00:00:00"),
    )
    await repo.save(period)
    fetched = await repo.find_by_id("pp-dec")
    assert fetched is not None
    assert fetched.lines[0].minutes == Decimal("90.0000")


# ---------------------------------------------------------------------------
# Revenue snapshot repo
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revenue_snapshot_upsert_is_idempotent(db, acad) -> None:
    repo = MongoAcademyRevenueSnapshotRepository(db)
    snapshot = AcademyRevenueSnapshot(
        academy_id="test-academy",
        period="2026-05",
        gross_minor=100,
        refunded_minor=10,
        outstanding_minor=20,
        currency="USD",
        computed_at=_dt("2026-06-01T00:00:00"),
    )
    await repo.upsert(snapshot)
    updated = snapshot.model_copy(update={"gross_minor": 200})
    await repo.upsert(updated)
    fetched = await repo.find(academy_id="test-academy", period="2026-05")
    assert fetched is not None
    assert fetched.gross_minor == 200

    count = await db["academy_revenue_snapshots"].count_documents({"academy_id": "test-academy"})
    assert count == 1


@pytest.mark.asyncio
async def test_revenue_snapshot_does_not_leak_across_tenants(db, acad) -> None:
    repo = MongoAcademyRevenueSnapshotRepository(db)
    await repo.upsert(
        AcademyRevenueSnapshot(
            academy_id="test-academy",
            period="2026-05",
            gross_minor=100,
            refunded_minor=0,
            outstanding_minor=0,
            currency="USD",
            computed_at=_dt("2026-06-01T00:00:00"),
        )
    )
    token = _tenant_var.set("other-academy")
    try:
        other_repo = MongoAcademyRevenueSnapshotRepository(db)
        assert await other_repo.find(academy_id="other-academy", period="2026-05") is None
    finally:
        _tenant_var.reset(token)


# ---------------------------------------------------------------------------
# Attendance snapshot repo
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_attendance_snapshot_upsert_round_trip(db, acad) -> None:
    repo = MongoSessionAttendanceSnapshotRepository(db)
    snap = SessionAttendanceSnapshot(
        academy_id="test-academy",
        session_id="sess-1",
        period="2026-05",
        scheduled_count=10,
        completed_count=8,
        no_show_count=2,
        computed_at=_dt("2026-06-01T00:00:00"),
    )
    await repo.upsert(snap)
    fetched = await repo.find(academy_id="test-academy", session_id="sess-1", period="2026-05")
    assert fetched is not None
    assert fetched.scheduled_count == 10
    assert fetched.completed_count == 8


# ---------------------------------------------------------------------------
# Coach payout snapshot repo
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_coach_payout_snapshot_preserves_decimal_hours(db, acad) -> None:
    repo = MongoCoachPayoutSnapshotRepository(db)
    snap = CoachPayoutSnapshot(
        academy_id="test-academy",
        coach_id="coach-A",
        period="2026-05",
        hours=Decimal("12.7500"),
        payout_minor=63_750,
        currency="USD",
        computed_at=_dt("2026-06-01T00:00:00"),
    )
    await repo.upsert(snap)
    fetched = await repo.find(academy_id="test-academy", coach_id="coach-A", period="2026-05")
    assert fetched is not None
    assert fetched.hours == Decimal("12.7500")
    assert fetched.payout_minor == 63_750


# ---------------------------------------------------------------------------
# Migration smoke
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_payout_period_migration_creates_natural_key_index(db) -> None:
    module = importlib.import_module("backend.v2.migrations.0103_payout_period_indexes")
    await module.up(db)
    indexes = await db["payout_periods"].index_information()
    assert "payout_periods_natural_key" in indexes
    assert indexes["payout_periods_natural_key"].get("unique") is True


@pytest.mark.asyncio
async def test_reporting_snapshot_migration_creates_unique_indexes(db) -> None:
    module = importlib.import_module("backend.v2.migrations.0104_reporting_snapshot_indexes")
    await module.up(db)
    rev_indexes = await db["academy_revenue_snapshots"].index_information()
    assert "academy_revenue_snapshots_natural_key" in rev_indexes
    assert rev_indexes["academy_revenue_snapshots_natural_key"].get("unique") is True

    coach_indexes = await db["coach_payout_snapshots"].index_information()
    assert "coach_payout_snapshots_natural_key" in coach_indexes
    assert coach_indexes["coach_payout_snapshots_natural_key"].get("unique") is True
