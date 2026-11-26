"""Unit tests for GetAttendanceTrends use case.

All tests use a simple stub ``HeldClassReader`` — no Mongo required.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pytest

from backend.v2.contexts.finance.application.use_cases.attendance_trends import (
    AttendanceTrendsResult,
    GetAttendanceTrends,
)


@dataclass(frozen=True)
class _Counts:
    period: str
    scheduled_count: int
    completed_count: int
    no_show_count: int


def _snap(
    session_id: str, period: str, scheduled: int, completed: int, no_show: int, **_: object
) -> _Counts:
    return _Counts(
        period=period, scheduled_count=scheduled, completed_count=completed, no_show_count=no_show
    )


class StubHeldClassReader:
    """Stub ``HeldClassReader`` returning fixed per-period rows."""

    def __init__(self, rows: list[_Counts]) -> None:
        self._rows = rows

    async def class_counts_for_periods(
        self, *, academy_id: str, periods: list[str]
    ) -> list[_Counts]:
        return [r for r in self._rows if r.period in periods]

    async def coach_hours_for_periods(self, *, academy_id: str, periods: list[str]) -> list:
        return []


def _use_case(rows: list[_Counts]) -> GetAttendanceTrends:
    return GetAttendanceTrends(classes=StubHeldClassReader(rows), academy_id="test-academy")


@pytest.mark.asyncio
async def test_aggregates_completion_rate_across_sessions():
    """Multiple sessions in one period are summed; completion_rate is per-period."""
    # Period 2026-05: two sessions — 10+5=15 scheduled, 8+4=12 completed
    uc = _use_case(
        [
            _snap("sess-1", "2026-05", scheduled=10, completed=8, no_show=2),
            _snap("sess-2", "2026-05", scheduled=5, completed=4, no_show=1),
        ]
    )
    result = await uc.execute(["2026-05"])

    assert len(result.periods) == 1
    point = result.periods[0]
    assert point.period == "2026-05"
    assert point.scheduled_count == 15
    assert point.completed_count == 12
    assert point.no_show_count == 3
    # 12 / 15 = 0.8000
    assert point.completion_rate == Decimal("0.8000")


@pytest.mark.asyncio
async def test_overall_rate_is_weighted_by_scheduled_count():
    """overall_completion_rate uses total_completed / total_scheduled across all periods."""
    # 2026-04: 10 scheduled, 10 completed → rate 1.0
    # 2026-05: 90 scheduled, 45 completed → rate 0.5
    # Overall: 55 / 100 = 0.5500
    uc = _use_case(
        [
            _snap("sess-1", "2026-04", scheduled=10, completed=10, no_show=0),
            _snap("sess-2", "2026-05", scheduled=90, completed=45, no_show=45),
        ]
    )
    result = await uc.execute(["2026-04", "2026-05"])

    assert len(result.periods) == 2
    assert result.overall_completion_rate == Decimal("0.5500")

    # Verify individual period rates are independent
    apr = next(p for p in result.periods if p.period == "2026-04")
    may = next(p for p in result.periods if p.period == "2026-05")
    assert apr.completion_rate == Decimal("1.0000")
    assert may.completion_rate == Decimal("0.5000")


@pytest.mark.asyncio
async def test_empty_periods_returns_empty_result():
    """Passing an empty periods list returns a result with no points and rate 0."""
    uc = _use_case(
        [
            _snap("sess-1", "2026-05", scheduled=10, completed=8, no_show=2),
        ]
    )
    result = await uc.execute([])

    assert result.periods == []
    assert result.overall_completion_rate == Decimal("0")
    assert isinstance(result, AttendanceTrendsResult)


@pytest.mark.asyncio
async def test_overall_rate_zero_when_no_scheduled():
    """When all periods have zero scheduled counts, overall rate is 0 (no ZeroDivisionError)."""
    uc = _use_case(
        [
            _snap("sess-1", "2026-05", scheduled=0, completed=0, no_show=0),
        ]
    )
    result = await uc.execute(["2026-05"])

    assert len(result.periods) == 1
    assert result.periods[0].completion_rate == Decimal("0")
    assert result.overall_completion_rate == Decimal("0")
