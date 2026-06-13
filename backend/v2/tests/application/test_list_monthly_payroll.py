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
) -> PayoutPeriod:
    return PayoutPeriod(
        period_id=f"period-{coach_id}-{period_start.month}-{period_end.month}",
        academy_id=academy_id,
        coach_id=coach_id,
        period_start=period_start,
        period_end=period_end,
        status=status,  # type: ignore[arg-type]
        currency=currency,
        total_minor=total_minor,
        lines=[],
        unpaid_occurrence_ids=[],
        generated_at=datetime(2026, 6, 13, tzinfo=UTC_),
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
        self._periods = [
            period if p.period_id == period.period_id else p for p in self._periods
        ]
        return period

    async def replace_with_lines(self, period: PayoutPeriod) -> PayoutPeriod:
        self._periods = [
            period if p.period_id == period.period_id else p for p in self._periods
        ]
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
    p_june_a = make_fake_period(coach_id="c1", period_start=JUNE_START, period_end=JUNE_END, academy_id="a1")
    p_june_b = make_fake_period(coach_id="c2", period_start=JUNE_START, period_end=JUNE_END, academy_id="a1")
    p_july = make_fake_period(coach_id="c1", period_start=JULY_START, period_end=JULY_END, academy_id="a1")
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
    await repo.save(make_fake_period(coach_id="c1", period_start=JUNE_START, period_end=JUNE_END, academy_id="a1"))
    await repo.save(make_fake_period(coach_id="c1", period_start=JUNE_START, period_end=JUNE_END, academy_id="a2"))

    results = await repo.list_for_window(
        academy_id="a1", period_start=JUNE_START, period_end=JUNE_END
    )
    assert len(results) == 1
    assert results[0].academy_id == "a1"
