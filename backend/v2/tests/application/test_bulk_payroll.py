"""Tests for BulkGeneratePayroll and BulkRecomputePayroll."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from backend.v2.contexts.finance.application.use_cases.bulk_payroll import (
    BulkGeneratePayroll,
    BulkRecomputePayroll,
)
from backend.v2.contexts.finance.domain.payout_period import PayoutPeriod

UTC_ = UTC
START = datetime(2026, 6, 1, tzinfo=UTC_)
END = datetime(2026, 7, 1, tzinfo=UTC_)


_APPROVED_AT = datetime(2026, 6, 13, 10, 0, tzinfo=UTC_)
_GENERATED_AT = datetime(2026, 6, 13, tzinfo=UTC_)


def _make_period(coach_id: str, status: str = "draft") -> PayoutPeriod:
    extra: dict = {}
    if status in ("approved", "paid"):
        extra["approved_at"] = _APPROVED_AT
    if status == "paid":
        extra["paid_at"] = _APPROVED_AT
        extra["paid_method"] = "bank_transfer"
        extra["paid_amount_minor"] = 0
    return PayoutPeriod(
        period_id=f"p-{coach_id}",
        academy_id="a1",
        coach_id=coach_id,
        period_start=START,
        period_end=END,
        status=status,
        currency="MYR",
        total_minor=0,
        lines=[],
        unpaid_occurrence_ids=[],
        generated_at=_GENERATED_AT,
        **extra,
    )


@dataclass(frozen=True)
class _FakeOccRow:
    coach_id: str
    session_count: int


class _FakeReader:
    def __init__(self, coach_ids: list[str]) -> None:
        self._coach_ids = coach_ids

    async def coaches_with_occurrences(
        self, *, academy_id: str, period_start: datetime, period_end: datetime
    ):
        return [_FakeOccRow(coach_id=c, session_count=1) for c in self._coach_ids]


class _FakePeriodRepo:
    def __init__(self, periods: list[PayoutPeriod] | None = None) -> None:
        self._periods: list[PayoutPeriod] = list(periods or [])

    async def find_by_window(self, *, coach_id: str, period_start: datetime, period_end: datetime):
        return next((p for p in self._periods if p.coach_id == coach_id), None)

    async def find_overlapping(
        self, *, coach_id: str, period_start: datetime, period_end: datetime
    ):
        return next(
            (
                p
                for p in self._periods
                if p.coach_id == coach_id
                and p.period_start < period_end
                and p.period_end > period_start
            ),
            None,
        )

    async def list_for_window(
        self, *, academy_id: str, period_start: datetime, period_end: datetime
    ):
        return list(self._periods)

    async def save(self, period: PayoutPeriod) -> PayoutPeriod:
        self._periods.append(period)
        return period

    async def find_by_id(self, period_id: str):
        return None

    async def replace(self, period: PayoutPeriod) -> PayoutPeriod:
        return period

    async def replace_with_lines(self, period: PayoutPeriod) -> PayoutPeriod:
        return period


class _FakeGenerate:
    def __init__(self, repo: _FakePeriodRepo) -> None:
        self._repo = repo
        self.calls: list[str] = []

    async def execute(
        self, *, coach_id: str, academy_id: str, period_start: datetime, period_end: datetime
    ):
        self.calls.append(coach_id)
        period = _make_period(coach_id)
        await self._repo.save(period)
        return period


class _FakeRecompute:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def execute(self, *, period_id: str, actor_id: str):
        self.calls.append(period_id)


@pytest.mark.asyncio
async def test_bulk_generate_is_idempotent() -> None:
    repo = _FakePeriodRepo()
    generate = _FakeGenerate(repo)
    reader = _FakeReader(["c1", "c2"])
    uc = BulkGeneratePayroll(reader=reader, periods=repo, generate=generate)

    first = await uc.execute(academy_id="a1", period_start=START, period_end=END)
    assert first.generated == 2 and first.skipped == 0

    second = await uc.execute(academy_id="a1", period_start=START, period_end=END)
    assert second.generated == 0 and second.skipped == 2


@pytest.mark.asyncio
async def test_bulk_recompute_skips_non_draft() -> None:
    periods = [
        _make_period("c1", status="draft"),
        _make_period("c2", status="approved"),
        _make_period("c3", status="paid"),
    ]
    repo = _FakePeriodRepo(periods)
    recompute = _FakeRecompute()
    uc = BulkRecomputePayroll(periods=repo, recompute=recompute)

    result = await uc.execute(
        academy_id="a1", period_start=START, period_end=END, actor_id="admin-1"
    )
    assert result.recomputed == 1
    assert result.skipped == 2
    assert recompute.calls == ["p-c1"]
