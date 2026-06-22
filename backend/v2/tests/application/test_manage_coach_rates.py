"""SetCoachPayRate / ListCoachPayRates — versioned rate sheet writes."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.contexts.coaching.application.use_cases.manage_coach_rates import (
    DiagnoseCoachRateTimeline,
    ListCoachPayRates,
    RepairCoachRateWindow,
    RepairCoachRateWindowCommand,
    SetCoachPayRate,
    SetCoachPayRateCommand,
    normalize_effective_datetime,
)
from backend.v2.contexts.coaching.domain.payout import CoachRate
from backend.v2.shared.tenancy.context import tenant_scope


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


def _rate(**overrides) -> CoachRate:
    base = dict(
        rate_id="cr-1",
        academy_id="acad-1",
        coach_id="coach-A",
        billing_unit="per_session",
        amount_minor=5000,
        percent_bps=None,
        currency="USD",
        effective_from=_dt("2026-01-01T00:00:00"),
        effective_until=None,
        status="active",
    )
    base.update(overrides)
    return CoachRate(**base)


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


class FakeRateAudit:
    def __init__(self) -> None:
        self.entries: list[object] = []

    async def append(self, entry: object) -> None:
        self.entries.append(entry)


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


@pytest.mark.asyncio
async def test_timeline_diagnostics_detect_gap_overlap_duplicate_start_and_duplicate_active() -> (
    None
):
    writer = FakeRateWriter(
        [
            _rate(
                rate_id="cr-jan",
                effective_from=_dt("2026-01-01T00:00:00"),
                effective_until=_dt("2026-02-01T00:00:00"),
                status="superseded",
            ),
            _rate(
                rate_id="cr-gap-after",
                effective_from=_dt("2026-03-01T00:00:00"),
                effective_until=_dt("2026-04-15T00:00:00"),
                status="superseded",
            ),
            _rate(
                rate_id="cr-overlap",
                effective_from=_dt("2026-04-01T00:00:00"),
                effective_until=None,
                status="active",
            ),
            _rate(
                rate_id="cr-dup-start",
                effective_from=_dt("2026-04-01T00:00:00"),
                effective_until=None,
                status="active",
            ),
        ]
    )

    diagnostics = await DiagnoseCoachRateTimeline(rates=writer).execute(coach_id="coach-A")

    issue_types = {issue.issue_type for issue in diagnostics.issues}
    assert "gap" in issue_types
    assert "overlap" in issue_types
    assert "duplicate_effective_from" in issue_types
    assert "duplicate_active_rows" in issue_types
    assert "multiple_open_ended_rows" in issue_types
    assert diagnostics.has_blocking_issues is True


@pytest.mark.asyncio
async def test_set_rate_blocks_when_existing_timeline_is_malformed() -> None:
    writer = FakeRateWriter(
        [
            _rate(rate_id="cr-active-1", effective_from=_dt("2026-01-01T00:00:00")),
            _rate(rate_id="cr-active-2", effective_from=_dt("2026-02-01T00:00:00")),
        ]
    )

    with tenant_scope("acad-1"):
        with pytest.raises(ValueError, match="repair workflow"):
            await _use_case(writer, now="2026-06-01T00:00:00").execute(
                SetCoachPayRateCommand(
                    coach_id="coach-A",
                    billing_unit="per_session",
                    amount_minor=6000,
                )
            )


@pytest.mark.parametrize(
    ("incoming", "expected"),
    [
        (datetime(2026, 6, 1), _dt("2026-06-01T00:00:00")),
        (_dt("2026-06-01T05:00:00"), _dt("2026-06-01T05:00:00")),
    ],
)
def test_effective_datetime_normalization_uses_utc(incoming: datetime, expected: datetime) -> None:
    assert normalize_effective_datetime(incoming) == expected


@pytest.mark.asyncio
async def test_repair_gap_inserts_bounded_rate_and_writes_audit_record() -> None:
    writer = FakeRateWriter(
        [
            _rate(
                rate_id="cr-old",
                effective_from=_dt("2026-01-01T00:00:00"),
                effective_until=_dt("2026-05-01T00:00:00"),
                status="superseded",
            ),
            _rate(rate_id="cr-active", effective_from=_dt("2026-06-01T00:00:00")),
        ]
    )
    audit = FakeRateAudit()

    with tenant_scope("acad-1"):
        repaired = await RepairCoachRateWindow(
            rates=writer,
            audit=audit,
            id_factory=lambda: "cr-repair",
            audit_id_factory=lambda: "audit-repair",
            clock=lambda: _dt("2026-06-10T12:00:00"),
        ).execute(
            RepairCoachRateWindowCommand(
                coach_id="coach-A",
                billing_unit="per_session",
                amount_minor=5000,
                currency="USD",
                effective_from=_dt("2026-05-01T00:00:00"),
                effective_until=_dt("2026-06-01T00:00:00"),
                reason="Backfill imported gap before June payroll approval.",
                actor_id="admin-1",
            )
        )

    assert repaired.rate_id == "cr-repair"
    assert repaired.status == "superseded"
    assert repaired.effective_until == _dt("2026-06-01T00:00:00")
    assert len(audit.entries) == 1
    entry = audit.entries[0]
    assert entry.action == "rate_repaired"
    assert entry.actor_id == "admin-1"
    assert entry.reason == "Backfill imported gap before June payroll approval."
    assert entry.after["rate_id"] == "cr-repair"
