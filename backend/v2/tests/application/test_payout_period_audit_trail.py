"""Money-moving payout transitions are audited, and paid is not silently reopenable (#787).

``PayoutAuditAction`` has always declared ``generated``/``approved``/
``marked_paid``, but only recompute/reopen/override ever wrote an entry —
the three transitions that actually move payroll money left no trace.

Reopen had the mirror-image problem: it cleared ``paid_*`` on a period the
academy had already paid out, with no acknowledgement that the money has to
be clawed back. These tests pin both.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from backend.v2.contexts.finance.application.use_cases.approve_payout_period import (
    ApprovePayoutPeriod,
    MarkPayoutPaid,
    MarkPayoutPaidCommand,
)
from backend.v2.contexts.finance.application.use_cases.generate_payout_period import (
    GeneratePayoutPeriod,
)
from backend.v2.contexts.finance.application.use_cases.manage_payout_period import (
    ReopenPayoutPeriod,
)
from backend.v2.contexts.finance.domain.payout_audit import PayoutAuditEntry
from backend.v2.contexts.finance.domain.payout_period import (
    PayoutPeriod,
    PayoutPeriodStateError,
    PersistedPayoutLine,
    approve,
    mark_paid,
    reopen,
)


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


class FakeRepo:
    def __init__(self) -> None:
        self._by_id: dict[str, PayoutPeriod] = {}

    async def find_by_window(
        self, *, coach_id: str, period_start: datetime, period_end: datetime
    ) -> PayoutPeriod | None:
        for period in self._by_id.values():
            if (
                period.coach_id == coach_id
                and period.period_start == period_start
                and period.period_end == period_end
            ):
                return period
        return None

    async def find_overlapping(
        self, *, coach_id: str, period_start: datetime, period_end: datetime
    ) -> PayoutPeriod | None:
        return None

    async def find_by_id(self, period_id: str) -> PayoutPeriod | None:
        return self._by_id.get(period_id)

    async def find_locked_status_for_coach(self, *, coach_id: str, at: datetime) -> str | None:
        for period in self._by_id.values():
            if (
                period.coach_id == coach_id
                and period.status in {"approved", "paid"}
                and period.period_start <= at < period.period_end
            ):
                return period.status
        return None

    async def save(self, period: PayoutPeriod) -> PayoutPeriod:
        self._by_id[period.period_id] = period
        return period

    async def replace(self, period: PayoutPeriod) -> PayoutPeriod:
        if period.period_id not in self._by_id:
            raise LookupError(period.period_id)
        self._by_id[period.period_id] = period
        return period

    async def replace_with_lines(self, period: PayoutPeriod) -> PayoutPeriod:
        return await self.replace(period)


class FakeAudit:
    def __init__(self) -> None:
        self.entries: list[PayoutAuditEntry] = []

    async def append(self, entry: PayoutAuditEntry) -> None:
        self.entries.append(entry)

    async def list_for_period(self, period_id: str) -> list[PayoutAuditEntry]:
        return [entry for entry in self.entries if entry.period_id == period_id]


class _Calc:
    def __init__(self, lines: list[PersistedPayoutLine]) -> None:
        self.currency = "USD"
        self.lines = lines
        self.total_minor = sum(line.amount_minor for line in lines)
        self.unpaid_occurrence_ids: list[str] = []
        self.unpaid_occurrences: list[object] = []
        self.payout_warnings: list[object] = []


class FakeCalculator:
    def __init__(self, result: _Calc) -> None:
        self._result = result

    async def calculate(
        self, *, coach_id: str, academy_id: str, period_start: datetime, period_end: datetime
    ) -> _Calc:
        return self._result


def _line(occurrence_id: str, amount: int) -> PersistedPayoutLine:
    return PersistedPayoutLine(
        occurrence_id=occurrence_id,
        coach_id="coach-A",
        basis="scheduled",
        minutes=Decimal("60"),
        amount_minor=amount,
        currency="USD",
        rate_id="cr-1",
    )


def _period(**overrides) -> PayoutPeriod:
    lines = [_line("occ-1", 5_000)]
    base = dict(
        period_id="pp-1",
        academy_id="acad-1",
        coach_id="coach-A",
        period_start=_dt("2026-05-01T00:00:00"),
        period_end=_dt("2026-06-01T00:00:00"),
        currency="USD",
        total_minor=sum(line.amount_minor for line in lines),
        lines=lines,
        generated_at=_dt("2026-06-01T00:00:00"),
    )
    base.update(overrides)
    return PayoutPeriod(**base)


# ---------------------------------------------------------------------------
# The three missing audit entries
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_writes_a_generated_audit_entry() -> None:
    repo = FakeRepo()
    audit = FakeAudit()
    use_case = GeneratePayoutPeriod(
        calculator=FakeCalculator(_Calc([_line("occ-1", 5_000)])),
        repository=repo,
        audit=audit,
        clock=lambda: _dt("2026-06-01T00:00:00"),
        id_factory=lambda: "pp-new",
    )

    period = await use_case.execute(
        coach_id="coach-A",
        academy_id="acad-1",
        period_start=_dt("2026-05-01T00:00:00"),
        period_end=_dt("2026-06-01T00:00:00"),
        actor_id="owner-1",
    )

    entries = await audit.list_for_period(period.period_id)
    assert [entry.action for entry in entries] == ["generated"]
    assert entries[0].actor_id == "owner-1"
    assert entries[0].after == {"total_minor": 5_000, "line_count": 1}


@pytest.mark.asyncio
async def test_generate_of_an_existing_window_does_not_double_audit() -> None:
    repo = FakeRepo()
    audit = FakeAudit()
    await repo.save(_period())
    use_case = GeneratePayoutPeriod(
        calculator=FakeCalculator(_Calc([_line("occ-1", 5_000)])),
        repository=repo,
        audit=audit,
    )

    await use_case.execute(
        coach_id="coach-A",
        academy_id="acad-1",
        period_start=_dt("2026-05-01T00:00:00"),
        period_end=_dt("2026-06-01T00:00:00"),
        actor_id="owner-1",
    )

    assert audit.entries == []


@pytest.mark.asyncio
async def test_approve_writes_an_approved_audit_entry() -> None:
    repo = FakeRepo()
    audit = FakeAudit()
    await repo.save(_period())
    use_case = ApprovePayoutPeriod(
        repository=repo,
        audit=audit,
        clock=lambda: _dt("2026-06-02T12:00:00"),
    )

    await use_case.execute(period_id="pp-1", actor_id="owner-1")

    entries = await audit.list_for_period("pp-1")
    assert [entry.action for entry in entries] == ["approved"]
    assert entries[0].before == {"status": "draft"}
    assert entries[0].after == {"status": "approved", "total_minor": 5_000}

    # Idempotent re-approve must not append a second entry.
    await use_case.execute(period_id="pp-1", actor_id="owner-1")
    assert len(await audit.list_for_period("pp-1")) == 1


@pytest.mark.asyncio
async def test_mark_paid_writes_a_marked_paid_audit_entry() -> None:
    repo = FakeRepo()
    audit = FakeAudit()
    await repo.save(approve(_period(), at=_dt("2026-06-02T12:00:00")))
    use_case = MarkPayoutPaid(repository=repo, audit=audit)

    await use_case.execute(
        MarkPayoutPaidCommand(
            period_id="pp-1",
            method="ach",
            paid_at=_dt("2026-06-03T12:00:00"),
            amount_minor=5_000,
            reference="ref-9",
        ),
        actor_id="owner-1",
    )

    entries = await audit.list_for_period("pp-1")
    assert [entry.action for entry in entries] == ["marked_paid"]
    assert entries[0].after == {
        "paid_amount_minor": 5_000,
        "paid_method": "ach",
        "paid_reference": "ref-9",
        "status": "paid",
    }


# ---------------------------------------------------------------------------
# Reopening a PAID period requires an explicit clawback acknowledgement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reopen_of_a_paid_period_requires_clawback_acknowledgement() -> None:
    repo = FakeRepo()
    audit = FakeAudit()
    paid = mark_paid(
        approve(_period(), at=_dt("2026-06-02T12:00:00")),
        at=_dt("2026-06-03T12:00:00"),
        method="ach",
        amount_minor=5_000,
        reference="ref-9",
    )
    await repo.save(paid)
    use_case = ReopenPayoutPeriod(repository=repo, audit=audit)

    with pytest.raises(PayoutPeriodStateError):
        await use_case.execute(period_id="pp-1", actor_id="owner-1", reason="wrong rate")

    assert audit.entries == []
    assert (await repo.find_by_id("pp-1")).status == "paid"


@pytest.mark.asyncio
async def test_reopen_of_a_paid_period_with_acknowledgement_clears_payment() -> None:
    repo = FakeRepo()
    audit = FakeAudit()
    paid = mark_paid(
        approve(_period(), at=_dt("2026-06-02T12:00:00")),
        at=_dt("2026-06-03T12:00:00"),
        method="ach",
        amount_minor=5_000,
        reference="ref-9",
    )
    await repo.save(paid)
    use_case = ReopenPayoutPeriod(repository=repo, audit=audit)

    stored = await use_case.execute(
        period_id="pp-1",
        actor_id="owner-1",
        reason="wrong rate",
        acknowledge_paid_clawback=True,
    )

    assert stored.status == "draft"
    assert stored.paid_at is None and stored.paid_amount_minor is None
    entry = (await audit.list_for_period("pp-1"))[0]
    assert entry.action == "reopened"
    assert entry.before["paid_amount_minor"] == 5_000
    assert entry.after["paid_clawback_acknowledged"] is True


@pytest.mark.asyncio
async def test_reopen_of_an_approved_period_needs_no_acknowledgement() -> None:
    repo = FakeRepo()
    audit = FakeAudit()
    await repo.save(approve(_period(), at=_dt("2026-06-02T12:00:00")))
    use_case = ReopenPayoutPeriod(repository=repo, audit=audit)

    stored = await use_case.execute(period_id="pp-1", actor_id="owner-1", reason="rate fix")

    assert stored.status == "draft"


def test_domain_reopen_refuses_a_paid_period_without_acknowledgement() -> None:
    paid = mark_paid(
        approve(_period(), at=_dt("2026-06-02T12:00:00")),
        at=_dt("2026-06-03T12:00:00"),
        method="ach",
        amount_minor=5_000,
    )
    with pytest.raises(PayoutPeriodStateError, match="clawed back"):
        reopen(paid)
    assert reopen(paid, acknowledge_paid_clawback=True).status == "draft"
