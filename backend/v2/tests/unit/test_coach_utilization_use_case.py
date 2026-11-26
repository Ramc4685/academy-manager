"""Unit tests for GetCoachUtilization use case.

All tests use a simple stub ``HeldClassReader`` — no Mongo required.
The use case derives utilization_rate as ``hours / max_hours`` (default
max_hours=40), capped at 1.0, 4dp.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pytest

from backend.v2.contexts.finance.application.use_cases.coach_utilization import (
    CoachUtilizationResult,
    GetCoachUtilization,
)


@dataclass(frozen=True)
class _Hours:
    coach_id: str
    period: str
    hours: Decimal
    payout_minor: int


def _snap(coach_id: str, period: str, hours: str, payout_minor: int) -> _Hours:
    return _Hours(coach_id=coach_id, period=period, hours=Decimal(hours), payout_minor=payout_minor)


class StubHeldClassReader:
    """Stub ``HeldClassReader`` returning fixed coach-hour rows."""

    def __init__(self, rows: list[_Hours]) -> None:
        self._rows = rows

    async def coach_hours_for_periods(self, *, academy_id: str, periods: list[str]) -> list[_Hours]:
        return [r for r in self._rows if r.period in periods]

    async def class_counts_for_periods(self, *, academy_id: str, periods: list[str]) -> list:
        return []


def _use_case(rows: list[_Hours], max_hours: int = 40) -> GetCoachUtilization:
    return GetCoachUtilization(
        classes=StubHeldClassReader(rows),
        academy_id="test-academy",
        max_hours=max_hours,
    )


@pytest.mark.asyncio
async def test_aggregates_payout_minor_across_periods():
    """total_payout_minor is the sum of all coach payout_minor across all periods."""
    uc = _use_case(
        [
            _snap("coach-1", "2026-04", hours="20.0", payout_minor=100000),
            _snap("coach-2", "2026-04", hours="10.0", payout_minor=50000),
            _snap("coach-1", "2026-05", hours="30.0", payout_minor=150000),
        ]
    )
    result = await uc.execute(["2026-04", "2026-05"])

    assert result.total_payout_minor == 300000
    assert len(result.coaches) == 3
    assert result.periods == ["2026-04", "2026-05"]


@pytest.mark.asyncio
async def test_utilization_rate_capped_at_one():
    """A coach with hours exceeding max_hours gets utilization_rate == 1.0."""
    uc = _use_case(
        [
            _snap("coach-1", "2026-05", hours="50.0", payout_minor=200000),
        ],
        max_hours=40,
    )
    result = await uc.execute(["2026-05"])

    assert len(result.coaches) == 1
    point = result.coaches[0]
    assert point.utilization_rate == Decimal("1.0")


@pytest.mark.asyncio
async def test_utilization_rate_calculated_correctly():
    """utilization_rate = hours / max_hours, rounded to 4dp."""
    # 20 hours / 40 max = 0.5000
    uc = _use_case(
        [
            _snap("coach-1", "2026-05", hours="20.0", payout_minor=80000),
        ],
        max_hours=40,
    )
    result = await uc.execute(["2026-05"])

    assert len(result.coaches) == 1
    point = result.coaches[0]
    assert point.coach_id == "coach-1"
    assert point.period == "2026-05"
    assert point.hours == Decimal("20.0")
    assert point.payout_minor == 80000
    assert point.utilization_rate == Decimal("0.5000")


class _ComplianceRow:
    def __init__(
        self, coach_id: str, marked_within_24h_count: int, total_marked_count: int
    ) -> None:
        self.coach_id = coach_id
        self.marked_within_24h_count = marked_within_24h_count
        self.total_marked_count = total_marked_count


class StubComplianceReader:
    """Stub implementation of MarkedWithin24hReader for unit tests."""

    def __init__(self, rows: list[_ComplianceRow]) -> None:
        self._rows = rows

    async def compliance_for_periods(
        self, *, academy_id: str, periods: list[str]
    ) -> list[_ComplianceRow]:
        return self._rows


@pytest.mark.asyncio
async def test_compliance_within_24h_rate_from_reader():
    """compliance_within_24h_rate = marked_within_24h_count / total_marked_count, 4dp."""
    uc = GetCoachUtilization(
        classes=StubHeldClassReader(
            [_snap("coach-1", "2026-05", hours="20.0", payout_minor=80000)]
        ),
        compliance_reader=StubComplianceReader([_ComplianceRow("coach-1", 3, 4)]),
        academy_id="test-academy",
    )
    result = await uc.execute(["2026-05"])

    assert len(result.coaches) == 1
    assert result.coaches[0].compliance_within_24h_rate == Decimal("0.7500")


@pytest.mark.asyncio
async def test_compliance_within_24h_rate_none_without_reader():
    """Without a compliance_reader, the field stays None rather than defaulting to 0."""
    uc = _use_case([_snap("coach-1", "2026-05", hours="20.0", payout_minor=80000)])
    result = await uc.execute(["2026-05"])

    assert result.coaches[0].compliance_within_24h_rate is None


@pytest.mark.asyncio
async def test_compliance_within_24h_rate_none_when_no_marks_yet():
    """A coach with zero marked occurrences yet has no rate to report (avoid 0/0)."""
    uc = GetCoachUtilization(
        classes=StubHeldClassReader(
            [_snap("coach-1", "2026-05", hours="20.0", payout_minor=80000)]
        ),
        compliance_reader=StubComplianceReader([_ComplianceRow("coach-1", 0, 0)]),
        academy_id="test-academy",
    )
    result = await uc.execute(["2026-05"])

    assert result.coaches[0].compliance_within_24h_rate is None


@pytest.mark.asyncio
async def test_empty_periods_returns_empty_coaches():
    """Passing an empty periods list returns a result with no coaches and payout 0."""
    uc = _use_case(
        [
            _snap("coach-1", "2026-05", hours="20.0", payout_minor=80000),
        ]
    )
    result = await uc.execute([])

    assert result.coaches == []
    assert result.periods == []
    assert result.total_payout_minor == 0
    assert isinstance(result, CoachUtilizationResult)
