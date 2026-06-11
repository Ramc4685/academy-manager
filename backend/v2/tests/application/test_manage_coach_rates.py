"""SetCoachPayRate / ListCoachPayRates — versioned rate sheet writes."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.contexts.coaching.application.use_cases.manage_coach_rates import (
    ListCoachPayRates,
    SetCoachPayRate,
    SetCoachPayRateCommand,
)
from backend.v2.contexts.coaching.domain.payout import CoachRate
from backend.v2.shared.tenancy.context import tenant_scope


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


class FakeRateWriter:
    def __init__(self, rates: list[CoachRate] | None = None) -> None:
        self.rates = list(rates or [])

    async def list_for_coach(self, coach_id: str) -> list[CoachRate]:
        return [r for r in self.rates if r.coach_id == coach_id]

    async def find_active(self, coach_id: str) -> CoachRate | None:
        active = [r for r in self.rates if r.coach_id == coach_id and r.status == "active"]
        if not active:
            return None
        return max(active, key=lambda r: r.effective_from)

    async def supersede(self, rate_id: str, *, effective_until: datetime) -> None:
        self.rates = [
            r.model_copy(update={"status": "superseded", "effective_until": effective_until})
            if r.rate_id == rate_id
            else r
            for r in self.rates
        ]

    async def insert(self, rate: CoachRate) -> None:
        self.rates.append(rate)


def _use_case(writer: FakeRateWriter, *, now: str = "2026-06-01T00:00:00") -> SetCoachPayRate:
    counter = iter(range(1, 100))
    return SetCoachPayRate(
        rates=writer,
        clock=lambda: _dt(now),
        id_factory=lambda: f"cr-{next(counter)}",
    )


@pytest.mark.asyncio
async def test_first_percent_rate_is_created_active() -> None:
    writer = FakeRateWriter()
    with tenant_scope("acad-1"):
        rate = await _use_case(writer).execute(
            SetCoachPayRateCommand(
                coach_id="coach-A",
                billing_unit="percent_of_revenue",
                percent_bps=6000,
            )
        )
    assert rate.status == "active"
    assert rate.percent_bps == 6000
    assert rate.academy_id == "acad-1"
    assert writer.rates == [rate]


@pytest.mark.asyncio
async def test_new_rate_supersedes_active_rate() -> None:
    writer = FakeRateWriter()
    with tenant_scope("acad-1"):
        first = await _use_case(writer, now="2026-05-01T00:00:00").execute(
            SetCoachPayRateCommand(
                coach_id="coach-A",
                billing_unit="per_session",
                amount_minor=5000,
            )
        )
        second = await _use_case(writer, now="2026-06-01T00:00:00").execute(
            SetCoachPayRateCommand(
                coach_id="coach-A",
                billing_unit="percent_of_revenue",
                percent_bps=5500,
            )
        )
    old = next(r for r in writer.rates if r.rate_id == first.rate_id)
    assert old.status == "superseded"
    assert old.effective_until == second.effective_from
    active = await writer.find_active("coach-A")
    assert active is not None and active.rate_id == second.rate_id


@pytest.mark.asyncio
async def test_percent_rate_requires_percent() -> None:
    writer = FakeRateWriter()
    with tenant_scope("acad-1"):
        with pytest.raises(ValueError, match="percent is required"):
            await _use_case(writer).execute(
                SetCoachPayRateCommand(
                    coach_id="coach-A",
                    billing_unit="percent_of_revenue",
                )
            )


@pytest.mark.asyncio
async def test_flat_rate_requires_positive_amount() -> None:
    writer = FakeRateWriter()
    with tenant_scope("acad-1"):
        with pytest.raises(ValueError, match="amount must be positive"):
            await _use_case(writer).execute(
                SetCoachPayRateCommand(
                    coach_id="coach-A",
                    billing_unit="per_session",
                    amount_minor=0,
                )
            )


@pytest.mark.asyncio
async def test_effective_from_must_advance() -> None:
    writer = FakeRateWriter()
    with tenant_scope("acad-1"):
        await _use_case(writer, now="2026-06-01T00:00:00").execute(
            SetCoachPayRateCommand(
                coach_id="coach-A",
                billing_unit="per_session",
                amount_minor=5000,
            )
        )
        with pytest.raises(ValueError, match="must be after"):
            await _use_case(writer).execute(
                SetCoachPayRateCommand(
                    coach_id="coach-A",
                    billing_unit="per_session",
                    amount_minor=6000,
                    effective_from=_dt("2026-05-01T00:00:00"),
                )
            )


@pytest.mark.asyncio
async def test_list_returns_newest_first() -> None:
    writer = FakeRateWriter()
    with tenant_scope("acad-1"):
        await _use_case(writer, now="2026-04-01T00:00:00").execute(
            SetCoachPayRateCommand(
                coach_id="coach-A", billing_unit="per_session", amount_minor=4000
            )
        )
        await _use_case(writer, now="2026-06-01T00:00:00").execute(
            SetCoachPayRateCommand(
                coach_id="coach-A", billing_unit="percent_of_revenue", percent_bps=6000
            )
        )
    rates = await ListCoachPayRates(rates=writer).execute(coach_id="coach-A")
    assert [r.status for r in rates] == ["active", "superseded"]
