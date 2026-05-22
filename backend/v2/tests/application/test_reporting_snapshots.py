"""Tests for reporting snapshot use cases (Wave 5A Stream M).

Each snapshot type has its own use case + port. These tests:

- Verify the use case reads via the injected port (billing /
  occurrences / payout periods) and writes the snapshot via the
  injected repository.
- Verify upserts are idempotent on the natural key.
- Verify ``period_end <= period_start`` is rejected up front.
- Verify ``CoachPayoutSnapshot`` correctly aggregates persisted payout
  lines into a single ``hours`` total and pulls currency from the
  period.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from backend.v2.contexts.finance.application.use_cases.compute_reporting_snapshots import (
    ComputeAcademyRevenueSnapshot,
    ComputeCoachPayoutSnapshot,
    ComputeSessionAttendanceSnapshot,
)
from backend.v2.contexts.finance.domain.payout_period import (
    PayoutPeriod,
    PersistedPayoutLine,
)
from backend.v2.contexts.finance.domain.reporting_snapshots import (
    AcademyRevenueSnapshot,
    CoachPayoutSnapshot,
    SessionAttendanceSnapshot,
)


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _Totals:
    def __init__(self, *, gross: int, refunded: int, outstanding: int, currency: str) -> None:
        self.gross_minor = gross
        self.refunded_minor = refunded
        self.outstanding_minor = outstanding
        self.currency = currency


class FakeBillingReader:
    def __init__(self, totals: _Totals) -> None:
        self._totals = totals

    async def revenue_for_period(
        self, *, academy_id: str, period_start: datetime, period_end: datetime
    ) -> _Totals:
        return self._totals


class _Counts:
    def __init__(self, *, scheduled: int, completed: int, no_show: int) -> None:
        self.scheduled_count = scheduled
        self.completed_count = completed
        self.no_show_count = no_show


class FakeOccurrenceReader:
    def __init__(self, counts: _Counts) -> None:
        self._counts = counts

    async def counts_for_session(
        self,
        *,
        academy_id: str,
        session_id: str,
        period_start: datetime,
        period_end: datetime,
    ) -> _Counts:
        return self._counts


class FakeSnapshotRepo:
    def __init__(self) -> None:
        self._store: dict[tuple, object] = {}
        self.upsert_calls = 0

    @staticmethod
    def _key_for(snapshot: object) -> tuple:
        if isinstance(snapshot, AcademyRevenueSnapshot):
            return ("revenue", snapshot.academy_id, snapshot.period)
        if isinstance(snapshot, SessionAttendanceSnapshot):
            return ("attendance", snapshot.academy_id, snapshot.session_id, snapshot.period)
        if isinstance(snapshot, CoachPayoutSnapshot):
            return ("coach_payout", snapshot.academy_id, snapshot.coach_id, snapshot.period)
        raise AssertionError(type(snapshot))

    async def upsert(self, snapshot):
        self.upsert_calls += 1
        self._store[self._key_for(snapshot)] = snapshot
        return snapshot

    async def find(self, **kwargs):
        # Best-effort find for tests. Match by whichever fields are
        # supplied.
        for value in self._store.values():
            if all(getattr(value, k, None) == v for k, v in kwargs.items()):
                return value
        return None


class FakePayoutRepo:
    def __init__(self, period: PayoutPeriod | None) -> None:
        self._period = period

    async def find_by_window(
        self, *, coach_id: str, period_start: datetime, period_end: datetime
    ) -> PayoutPeriod | None:
        if self._period is None:
            return None
        if (
            self._period.coach_id == coach_id
            and self._period.period_start == period_start
            and self._period.period_end == period_end
        ):
            return self._period
        return None

    async def find_by_id(self, period_id: str):  # pragma: no cover - unused
        return None

    async def save(self, period):  # pragma: no cover - unused
        return period

    async def replace(self, period):  # pragma: no cover - unused
        return period


# ---------------------------------------------------------------------------
# Revenue snapshot
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revenue_snapshot_is_built_from_billing_totals() -> None:
    billing = FakeBillingReader(
        _Totals(gross=120_000, refunded=5_000, outstanding=10_000, currency="USD")
    )
    repo = FakeSnapshotRepo()
    uc = ComputeAcademyRevenueSnapshot(
        billing=billing,
        repository=repo,
        clock=lambda: _dt("2026-06-02T00:00:00"),
    )
    snap = await uc.execute(
        academy_id="acad-1",
        period="2026-05",
        period_start=_dt("2026-05-01T00:00:00"),
        period_end=_dt("2026-06-01T00:00:00"),
    )
    assert snap.gross_minor == 120_000
    assert snap.refunded_minor == 5_000
    assert snap.outstanding_minor == 10_000
    assert snap.net_minor == 115_000
    assert snap.currency == "USD"
    assert repo.upsert_calls == 1


@pytest.mark.asyncio
async def test_revenue_snapshot_is_idempotent_on_natural_key() -> None:
    billing = FakeBillingReader(
        _Totals(gross=100, refunded=0, outstanding=0, currency="USD")
    )
    repo = FakeSnapshotRepo()
    uc = ComputeAcademyRevenueSnapshot(
        billing=billing,
        repository=repo,
        clock=lambda: _dt("2026-06-02T00:00:00"),
    )
    for _ in range(3):
        await uc.execute(
            academy_id="acad-1",
            period="2026-05",
            period_start=_dt("2026-05-01T00:00:00"),
            period_end=_dt("2026-06-01T00:00:00"),
        )
    # Fake repo's store has only one entry (the upsert overwrites).
    assert len(repo._store) == 1
    assert repo.upsert_calls == 3


@pytest.mark.asyncio
async def test_revenue_snapshot_rejects_inverted_window() -> None:
    uc = ComputeAcademyRevenueSnapshot(
        billing=FakeBillingReader(
            _Totals(gross=0, refunded=0, outstanding=0, currency="USD")
        ),
        repository=FakeSnapshotRepo(),
    )
    with pytest.raises(ValueError, match="period_end must be after"):
        await uc.execute(
            academy_id="acad-1",
            period="2026-05",
            period_start=_dt("2026-06-01T00:00:00"),
            period_end=_dt("2026-05-01T00:00:00"),
        )


# ---------------------------------------------------------------------------
# Attendance snapshot
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_attendance_snapshot_is_built_from_occurrence_counts() -> None:
    occs = FakeOccurrenceReader(_Counts(scheduled=10, completed=8, no_show=2))
    repo = FakeSnapshotRepo()
    uc = ComputeSessionAttendanceSnapshot(
        occurrences=occs,
        repository=repo,
        clock=lambda: _dt("2026-06-02T00:00:00"),
    )
    snap = await uc.execute(
        academy_id="acad-1",
        session_id="sess-1",
        period="2026-05",
        period_start=_dt("2026-05-01T00:00:00"),
        period_end=_dt("2026-06-01T00:00:00"),
    )
    assert snap.session_id == "sess-1"
    assert snap.scheduled_count == 10
    assert snap.completed_count == 8
    assert snap.no_show_count == 2
    assert snap.completion_rate == Decimal("0.8000")


@pytest.mark.asyncio
async def test_attendance_completion_rate_handles_zero_scheduled() -> None:
    snap = SessionAttendanceSnapshot(
        academy_id="acad-1",
        session_id="sess-1",
        period="2026-05",
        scheduled_count=0,
        completed_count=0,
        no_show_count=0,
        computed_at=_dt("2026-06-02T00:00:00"),
    )
    assert snap.completion_rate == Decimal("0")


# ---------------------------------------------------------------------------
# Coach payout snapshot
# ---------------------------------------------------------------------------


def _period_with_lines() -> PayoutPeriod:
    lines = [
        PersistedPayoutLine(
            occurrence_id="occ-1",
            coach_id="coach-A",
            basis="scheduled",
            minutes=Decimal("60"),
            amount_minor=5_000,
            currency="USD",
            rate_id="cr-1",
        ),
        PersistedPayoutLine(
            occurrence_id="occ-2",
            coach_id="coach-A",
            basis="scheduled",
            minutes=Decimal("90"),
            amount_minor=7_500,
            currency="USD",
            rate_id="cr-1",
        ),
    ]
    return PayoutPeriod(
        period_id="pp-1",
        academy_id="acad-1",
        coach_id="coach-A",
        period_start=_dt("2026-05-01T00:00:00"),
        period_end=_dt("2026-06-01T00:00:00"),
        currency="USD",
        total_minor=12_500,
        lines=lines,
        generated_at=_dt("2026-06-01T00:00:00"),
    )


@pytest.mark.asyncio
async def test_coach_payout_snapshot_sums_hours_and_amount() -> None:
    repo = FakeSnapshotRepo()
    payouts = FakePayoutRepo(_period_with_lines())
    uc = ComputeCoachPayoutSnapshot(
        payout_periods=payouts,
        repository=repo,
        clock=lambda: _dt("2026-06-02T00:00:00"),
    )
    snap = await uc.execute(
        academy_id="acad-1",
        coach_id="coach-A",
        period="2026-05",
        period_start=_dt("2026-05-01T00:00:00"),
        period_end=_dt("2026-06-01T00:00:00"),
    )
    assert snap.hours == Decimal("2.5000")  # 60 + 90 minutes = 2.5 hours
    assert snap.payout_minor == 12_500
    assert snap.currency == "USD"


@pytest.mark.asyncio
async def test_coach_payout_snapshot_handles_missing_period() -> None:
    repo = FakeSnapshotRepo()
    payouts = FakePayoutRepo(None)
    uc = ComputeCoachPayoutSnapshot(
        payout_periods=payouts,
        repository=repo,
        clock=lambda: _dt("2026-06-02T00:00:00"),
    )
    snap = await uc.execute(
        academy_id="acad-1",
        coach_id="coach-A",
        period="2026-05",
        period_start=_dt("2026-05-01T00:00:00"),
        period_end=_dt("2026-06-01T00:00:00"),
    )
    assert snap.hours == Decimal("0")
    assert snap.payout_minor == 0


@pytest.mark.asyncio
async def test_coach_payout_snapshot_is_idempotent_on_natural_key() -> None:
    repo = FakeSnapshotRepo()
    payouts = FakePayoutRepo(_period_with_lines())
    uc = ComputeCoachPayoutSnapshot(
        payout_periods=payouts,
        repository=repo,
        clock=lambda: _dt("2026-06-02T00:00:00"),
    )
    for _ in range(2):
        await uc.execute(
            academy_id="acad-1",
            coach_id="coach-A",
            period="2026-05",
            period_start=_dt("2026-05-01T00:00:00"),
            period_end=_dt("2026-06-01T00:00:00"),
        )
    # Same natural key — only one entry remains.
    assert len(repo._store) == 1
