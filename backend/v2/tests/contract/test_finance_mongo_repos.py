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

from backend.v2.contexts.billing.application.use_cases.finance import MongoPayoutRepository
from backend.v2.contexts.finance.domain.payout_period import (
    PayoutPeriod,
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
        generated_at=_dt("2026-06-01T00:00:00"),
    )


# ---------------------------------------------------------------------------
# PayoutPeriod repo
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_payout_repo_derives_occurrence_attributed_payouts_when_no_periods_exist(
    db, acad
) -> None:
    repo = MongoPayoutRepository(db)
    await db["session_occurrences"].insert_many(
        [
            {
                "academy_id": acad,
                "occurrence_id": "occ-1",
                "session_id": "sess-1",
                "start_at": _dt("2026-05-27T18:00:00"),
                "end_at": _dt("2026-05-27T19:00:00"),
                "status": "completed",
                "scheduled_coach_id": "coach-blno",
                "is_payable": True,
            },
            {
                "academy_id": acad,
                "occurrence_id": "occ-2",
                "session_id": "sess-2",
                "start_at": _dt("2026-05-28T18:00:00"),
                "end_at": _dt("2026-05-28T19:00:00"),
                "status": "completed",
                "scheduled_coach_id": "coach-blno",
                "actual_coach_id": "coach-replacement",
                "is_payable": True,
            },
            {
                "academy_id": "other-academy",
                "occurrence_id": "occ-other",
                "session_id": "sess-other",
                "start_at": _dt("2026-05-29T18:00:00"),
                "end_at": _dt("2026-05-29T19:00:00"),
                "status": "completed",
                "scheduled_coach_id": "coach-other",
                "is_payable": True,
            },
        ]
    )
    await db["coach_rates"].insert_many(
        [
            {
                "academy_id": acad,
                "coach_id": "coach-blno",
                "rate_id": "rate-1",
                "billing_unit": "per_session",
                "amount_minor": 2500,
                "currency": "USD",
                "effective_from": _dt("2026-01-01T00:00:00"),
                "status": "active",
            },
            {
                "academy_id": acad,
                "coach_id": "coach-replacement",
                "rate_id": "rate-2",
                "billing_unit": "per_session",
                "amount_minor": 3000,
                "currency": "USD",
                "effective_from": _dt("2026-01-01T00:00:00"),
                "status": "active",
            },
            {
                "academy_id": "other-academy",
                "coach_id": "coach-other",
                "rate_id": "rate-other",
                "billing_unit": "per_session",
                "amount_minor": 9999,
                "currency": "USD",
                "effective_from": _dt("2026-01-01T00:00:00"),
                "status": "active",
            },
        ]
    )
    await db["attendance"].insert_many(
        [
            {
                "academy_id": acad,
                "attendance_id": "att-1",
                "occurrence_id": "occ-1",
                "session_id": "sess-1",
                "student_id": "student-1",
                "marked_by": "coach-blno",
                "marked_at": _dt("2026-05-27T19:00:00"),
                "status": "present",
            },
            {
                "academy_id": acad,
                "attendance_id": "att-2",
                "occurrence_id": "occ-2",
                "session_id": "sess-2",
                "student_id": "student-2",
                "marked_by": "coach-blno",
                "marked_at": _dt("2026-05-28T19:00:00"),
                "status": "late",
            },
            {
                "academy_id": "other-academy",
                "attendance_id": "att-other",
                "occurrence_id": "occ-other",
                "session_id": "sess-other",
                "student_id": "student-other",
                "marked_by": "coach-other",
                "marked_at": _dt("2026-05-29T19:00:00"),
                "status": "present",
            },
        ]
    )

    rows = await repo.list_all()

    by_coach = {row.coach_id: row for row in rows}
    assert set(by_coach) == {"coach-blno", "coach-replacement"}
    assert "coach-other" not in by_coach
    assert by_coach["coach-blno"].amount_cents == 2500
    assert by_coach["coach-blno"].students_count == 1
    assert by_coach["coach-blno"].sessions_count == 1
    assert by_coach["coach-blno"].rule_label == "Occurrence attribution"
    assert by_coach["coach-replacement"].amount_cents == 3000
    assert by_coach["coach-replacement"].students_count == 1
    assert by_coach["coach-replacement"].sessions_count == 1
    assert by_coach["coach-replacement"].rule_label == "Occurrence attribution"


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
    replaced = await repo.replace(updated)
    assert replaced.status == "approved"

    fetched = await repo.find_by_id(saved.period_id)
    assert fetched is not None
    assert fetched.status == "approved"
    # mongomock-motor drops tzinfo on datetimes; compare naive components.
    assert fetched.approved_at is not None
    assert fetched.approved_at.replace(tzinfo=UTC) == _dt("2026-06-02T12:00:00")


@pytest.mark.asyncio
async def test_replace_missing_period_raises(db, acad) -> None:
    repo = MongoPayoutPeriodRepository(db)
    period = _make_period(period_id="pp-missing")
    with pytest.raises(LookupError):
        await repo.replace(period)


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
