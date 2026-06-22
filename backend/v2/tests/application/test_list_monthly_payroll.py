"""Tests for list_for_window (Task 2.1) and ListMonthlyPayroll (Task 2.3)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.contexts.finance.domain.payout_period import PayoutPeriod

UTC_ = UTC


def make_fake_period(
    *,
    coach_id: str,
    period_start: datetime,
    period_end: datetime,
    academy_id: str,
    status: str = "draft",
    total_minor: int = 0,
    currency: str = "MYR",
    unpaid_occurrence_ids: list[str] | None = None,
) -> PayoutPeriod:
    # model_construct bypasses the total_minor == sum(lines) validator so tests
    # can supply arbitrary totals without building matching line objects.
    return PayoutPeriod.model_construct(
        period_id=f"period-{coach_id}-{period_start.month}-{period_end.month}",
        academy_id=academy_id,
        coach_id=coach_id,
        period_start=period_start,
        period_end=period_end,
        status=status,
        currency=currency,
        total_minor=total_minor,
        lines=[],
        unpaid_occurrence_ids=unpaid_occurrence_ids or [],
        unpaid_occurrences=[],
        generated_at=datetime(2026, 6, 13, tzinfo=UTC_),
        approved_at=None,
        paid_at=None,
        paid_method=None,
        paid_amount_minor=None,
        paid_reference=None,
    )


class FakePayoutPeriodRepository:
    def __init__(self) -> None:
        self._periods: list[PayoutPeriod] = []

    async def save(self, period: PayoutPeriod) -> PayoutPeriod:
        self._periods.append(period)
        return period

    async def find_by_window(
        self, *, coach_id: str, period_start: datetime, period_end: datetime
    ) -> PayoutPeriod | None:
        for p in self._periods:
            if (
                p.coach_id == coach_id
                and p.period_start == period_start
                and p.period_end == period_end
            ):
                return p
        return None

    async def find_by_id(self, period_id: str) -> PayoutPeriod | None:
        return next((p for p in self._periods if p.period_id == period_id), None)

    async def replace(self, period: PayoutPeriod) -> PayoutPeriod:
        self._periods = [period if p.period_id == period.period_id else p for p in self._periods]
        return period

    async def replace_with_lines(self, period: PayoutPeriod) -> PayoutPeriod:
        self._periods = [period if p.period_id == period.period_id else p for p in self._periods]
        return period

    async def list_for_window(
        self, *, academy_id: str, period_start: datetime, period_end: datetime
    ) -> list[PayoutPeriod]:
        return [
            p
            for p in self._periods
            if (
                p.academy_id == academy_id
                and p.period_start == period_start
                and p.period_end == period_end
            )
        ]


# ---------------------------------------------------------------------------
# Task 2.1 — list_for_window
# ---------------------------------------------------------------------------

JUNE_START = datetime(2026, 6, 1, tzinfo=UTC_)
JUNE_END = datetime(2026, 7, 1, tzinfo=UTC_)
JULY_START = datetime(2026, 7, 1, tzinfo=UTC_)
JULY_END = datetime(2026, 8, 1, tzinfo=UTC_)


@pytest.mark.asyncio
async def test_list_for_window_returns_only_matching_month() -> None:
    repo = FakePayoutPeriodRepository()
    p_june_a = make_fake_period(
        coach_id="c1", period_start=JUNE_START, period_end=JUNE_END, academy_id="a1"
    )
    p_june_b = make_fake_period(
        coach_id="c2", period_start=JUNE_START, period_end=JUNE_END, academy_id="a1"
    )
    p_july = make_fake_period(
        coach_id="c1", period_start=JULY_START, period_end=JULY_END, academy_id="a1"
    )
    for p in [p_june_a, p_june_b, p_july]:
        await repo.save(p)

    results = await repo.list_for_window(
        academy_id="a1", period_start=JUNE_START, period_end=JUNE_END
    )
    assert {r.coach_id for r in results} == {"c1", "c2"}
    assert len(results) == 2


@pytest.mark.asyncio
async def test_list_for_window_tenant_scoped() -> None:
    repo = FakePayoutPeriodRepository()
    await repo.save(
        make_fake_period(
            coach_id="c1", period_start=JUNE_START, period_end=JUNE_END, academy_id="a1"
        )
    )
    await repo.save(
        make_fake_period(
            coach_id="c1", period_start=JUNE_START, period_end=JUNE_END, academy_id="a2"
        )
    )

    results = await repo.list_for_window(
        academy_id="a1", period_start=JUNE_START, period_end=JUNE_END
    )
    assert len(results) == 1
    assert results[0].academy_id == "a1"


# ---------------------------------------------------------------------------
# Task 2.3 — ListMonthlyPayroll
# ---------------------------------------------------------------------------

from backend.v2.contexts.finance.application.use_cases.list_monthly_payroll import (
    ListMonthlyPayroll,
)


class _FakeOccurrenceReader:
    def __init__(self, rows: list[tuple[str, int]]) -> None:
        self._rows = rows
        self.last_academy_id: str | None = None

    async def coaches_with_occurrences(
        self, *, academy_id: str, period_start: datetime, period_end: datetime
    ):
        self.last_academy_id = academy_id
        from dataclasses import dataclass

        @dataclass(frozen=True)
        class _Row:
            coach_id: str
            session_count: int

        return [_Row(coach_id=cid, session_count=cnt) for cid, cnt in self._rows]


class _FakeCalculator:
    def __init__(self, totals: dict[str, tuple[int, str, list[str] | None]]) -> None:
        self._totals = totals  # coach_id -> (total_minor, currency, unpaid_ids)

    async def calculate(
        self, *, coach_id: str, academy_id: str, period_start: datetime, period_end: datetime
    ):
        from dataclasses import dataclass

        @dataclass(frozen=True)
        class _Calc:
            total_minor: int
            currency: str
            lines: list = None
            unpaid_occurrence_ids: list = None
            unpaid_occurrences: list = None

            def __post_init__(self):
                object.__setattr__(self, "lines", self.lines or [])
                object.__setattr__(self, "unpaid_occurrence_ids", self.unpaid_occurrence_ids or [])
                object.__setattr__(self, "unpaid_occurrences", self.unpaid_occurrences or [])

        total, currency, unpaid_ids = self._totals.get(coach_id, (0, "MYR", []))
        return _Calc(total_minor=total, currency=currency, unpaid_occurrence_ids=unpaid_ids)


@pytest.mark.asyncio
async def test_lists_generated_and_ungenerated_coaches() -> None:
    reader = _FakeOccurrenceReader([("c1", 4), ("c2", 2)])
    repo = FakePayoutPeriodRepository()
    # c1 has an approved period
    await repo.save(
        make_fake_period(
            coach_id="c1",
            period_start=JUNE_START,
            period_end=JUNE_END,
            academy_id="a1",
            status="approved",
            total_minor=40000,
        )
    )
    calc = _FakeCalculator({"c2": (18000, "MYR", [])})

    uc = ListMonthlyPayroll(reader=reader, periods=repo, calculator=calc)
    rows = await uc.execute(academy_id="a1", period_start=JUNE_START, period_end=JUNE_END)
    by_coach = {r.coach_id: r for r in rows}

    assert by_coach["c1"].status == "approved"
    assert by_coach["c1"].total_minor == 40000
    assert by_coach["c1"].unresolved_unpaid_count == 0
    assert by_coach["c1"].period_id is not None
    assert by_coach["c2"].status == "not_generated"
    assert by_coach["c2"].total_minor == 18000
    assert by_coach["c2"].unresolved_unpaid_count == 0
    assert by_coach["c2"].period_id is None


@pytest.mark.asyncio
async def test_rows_include_unresolved_unpaid_count_even_when_total_is_nonzero() -> None:
    reader = _FakeOccurrenceReader([("c1", 4), ("c2", 3)])
    repo = FakePayoutPeriodRepository()
    await repo.save(
        make_fake_period(
            coach_id="c1",
            period_start=JUNE_START,
            period_end=JUNE_END,
            academy_id="a1",
            total_minor=40000,
            unpaid_occurrence_ids=["occ-gap"],
        )
    )
    calc = _FakeCalculator({"c2": (18000, "MYR", ["occ-missing-price"])})

    rows = await ListMonthlyPayroll(reader=reader, periods=repo, calculator=calc).execute(
        academy_id="a1", period_start=JUNE_START, period_end=JUNE_END
    )
    by_coach = {r.coach_id: r for r in rows}

    assert by_coach["c1"].total_minor == 40000
    assert by_coach["c1"].unresolved_unpaid_count == 1
    assert by_coach["c2"].total_minor == 18000
    assert by_coach["c2"].unresolved_unpaid_count == 1


@pytest.mark.asyncio
async def test_reader_receives_correct_academy_id() -> None:
    reader = _FakeOccurrenceReader([("c1", 1)])
    repo = FakePayoutPeriodRepository()
    calc = _FakeCalculator({"c1": (10000, "MYR", [])})

    uc = ListMonthlyPayroll(reader=reader, periods=repo, calculator=calc)
    await uc.execute(academy_id="acad_blno_badminton", period_start=JUNE_START, period_end=JUNE_END)
    assert reader.last_academy_id == "acad_blno_badminton"


@pytest.mark.asyncio
async def test_rows_sorted_by_coach_id() -> None:
    reader = _FakeOccurrenceReader([("c3", 1), ("c1", 2), ("c2", 1)])
    repo = FakePayoutPeriodRepository()
    calc = _FakeCalculator({})

    uc = ListMonthlyPayroll(reader=reader, periods=repo, calculator=calc)
    rows = await uc.execute(academy_id="a1", period_start=JUNE_START, period_end=JUNE_END)
    assert [r.coach_id for r in rows] == ["c1", "c2", "c3"]
