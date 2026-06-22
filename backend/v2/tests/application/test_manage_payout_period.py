"""Tests for Phase 2 payout-period corrections (recompute/reopen/override).

Behaviours under test:

1. **Recompute** re-runs the calculator and rewrites lines; manual line
   overrides survive (re-applied by occurrence_id on top of fresh amounts).
   Non-draft periods are rejected.
2. **Reopen** moves approved/paid back to draft, clears payment metadata,
   requires a reason, and records the before-snapshot in the audit trail.
3. **Override** sets or clears a manual amount on one line, rebuilds the
   period total, and is draft-gated.
4. Every mutation appends exactly one ``PayoutAuditEntry``.

All persistence uses in-memory fakes of the ports.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from backend.v2.contexts.finance.application.use_cases.manage_payout_period import (
    ListPayoutAuditEntries,
    OverridePayoutLine,
    RecomputePayoutPeriod,
    ReopenPayoutPeriod,
)
from backend.v2.contexts.finance.domain.payout_audit import PayoutAuditEntry
from backend.v2.contexts.finance.domain.payout_period import (
    PayoutPeriod,
    PayoutPeriodStateError,
    PayoutWarning,
    PersistedPayoutLine,
    PersistedUnpaidOccurrence,
    approve,
    mark_paid,
)


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeRepo:
    def __init__(self) -> None:
        self._by_id: dict[str, PayoutPeriod] = {}
        self.replace_calls = 0
        self.replace_with_lines_calls = 0

    async def find_by_window(
        self,
        *,
        coach_id: str,
        period_start: datetime,
        period_end: datetime,
    ) -> PayoutPeriod | None:
        for p in self._by_id.values():
            if (
                p.coach_id == coach_id
                and p.period_start == period_start
                and p.period_end == period_end
            ):
                return p
        return None

    async def find_by_id(self, period_id: str) -> PayoutPeriod | None:
        return self._by_id.get(period_id)

    async def save(self, period: PayoutPeriod) -> PayoutPeriod:
        self._by_id[period.period_id] = period
        return period

    async def replace(self, period: PayoutPeriod) -> PayoutPeriod:
        if period.period_id not in self._by_id:
            raise LookupError(period.period_id)
        self.replace_calls += 1
        self._by_id[period.period_id] = period
        return period

    async def replace_with_lines(self, period: PayoutPeriod) -> PayoutPeriod:
        if period.period_id not in self._by_id:
            raise LookupError(period.period_id)
        self.replace_with_lines_calls += 1
        self._by_id[period.period_id] = period
        return period


class FakeAudit:
    def __init__(self) -> None:
        self.entries: list[PayoutAuditEntry] = []

    async def append(self, entry: PayoutAuditEntry) -> None:
        self.entries.append(entry)

    async def list_for_period(self, period_id: str) -> list[PayoutAuditEntry]:
        return [e for e in self.entries if e.period_id == period_id]


class _Calc:
    """In-memory ``PayoutCalculation`` result."""

    def __init__(
        self,
        *,
        currency: str = "USD",
        lines: list[PersistedPayoutLine] | None = None,
        unpaid: list[str] | None = None,
        warnings: list[PayoutWarning] | None = None,
        unpaid_occurrences: list[PersistedUnpaidOccurrence] | None = None,
    ) -> None:
        self.coach_id = "coach-A"
        self.academy_id = "acad-1"
        self.period_start = _dt("2026-05-01T00:00:00")
        self.period_end = _dt("2026-06-01T00:00:00")
        self.currency = currency
        self.lines = lines or []
        self.total_minor = sum(line.amount_minor for line in self.lines)
        self.unpaid_occurrence_ids = unpaid or []
        self.payout_warnings = warnings or []
        self.unpaid_occurrences = unpaid_occurrences or []


class FakeCalculator:
    def __init__(self, result: _Calc) -> None:
        self._result = result
        self.calls = 0

    async def calculate(
        self,
        *,
        coach_id: str,
        academy_id: str,
        period_start: datetime,
        period_end: datetime,
    ) -> _Calc:
        self.calls += 1
        return self._result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _line(occurrence_id: str, amount: int, **overrides) -> PersistedPayoutLine:
    base = dict(
        occurrence_id=occurrence_id,
        coach_id="coach-A",
        basis="scheduled",
        minutes=Decimal("60"),
        amount_minor=amount,
        currency="USD",
        rate_id="cr-1",
    )
    base.update(overrides)
    return PersistedPayoutLine(**base)


def _unpaid(occurrence_id: str, reason: str) -> PersistedUnpaidOccurrence:
    return PersistedUnpaidOccurrence(
        occurrence_id=occurrence_id,
        reason=reason,
        detail="Payroll could not compute this occurrence.",
        unresolved=True,
    )


def _period(lines: list[PersistedPayoutLine], **overrides) -> PayoutPeriod:
    base = dict(
        period_id="pp-1",
        academy_id="acad-1",
        coach_id="coach-A",
        period_start=_dt("2026-05-01T00:00:00"),
        period_end=_dt("2026-06-01T00:00:00"),
        currency="USD",
        total_minor=sum(line.amount_minor for line in lines),
        lines=lines,
        unpaid_occurrence_ids=[],
        unpaid_occurrences=[],
        payout_warnings=[],
        generated_at=_dt("2026-06-01T00:00:00"),
    )
    base.update(overrides)
    return PayoutPeriod(**base)


def _warning(**overrides) -> PayoutWarning:
    base = dict(
        occurrence_id="occ-warning",
        reason="missing_session_price_for_percent_revenue",
        severity="blocking",
        message="Missing session price for percent-of-revenue pay.",
        occurred_at=_dt("2026-05-10T18:00:00"),
        session_id=None,
        session_title=None,
        coach_id="coach-A",
        repair_action="set_session_fee_and_recompute",
    )
    base.update(overrides)
    return PayoutWarning(**base)


def _clock() -> datetime:
    return _dt("2026-06-05T12:00:00")


# ---------------------------------------------------------------------------
# RecomputePayoutPeriod
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recompute_rewrites_lines_and_audits() -> None:
    repo = FakeRepo()
    audit = FakeAudit()
    await repo.save(_period([_line("occ-1", 5000)]))
    fresh = _Calc(
        lines=[_line("occ-1", 6000), _line("occ-2", 4000)],
        unpaid=["occ-3"],
        unpaid_occurrences=[_unpaid("occ-3", "rate_gap")],
    )
    uc = RecomputePayoutPeriod(
        calculator=FakeCalculator(fresh),
        repository=repo,
        audit=audit,
        clock=_clock,
        id_factory=lambda: "audit-1",
    )

    stored = await uc.execute(period_id="pp-1", actor_id="admin-1")

    assert stored.total_minor == 10000
    assert [line.occurrence_id for line in stored.lines] == ["occ-1", "occ-2"]
    assert stored.unpaid_occurrence_ids == ["occ-3"]
    assert stored.unpaid_occurrences[0].reason == "rate_gap"
    assert repo.replace_with_lines_calls == 1
    assert len(audit.entries) == 1
    entry = audit.entries[0]
    assert entry.action == "recomputed"
    assert entry.actor_id == "admin-1"
    assert entry.before == {"total_minor": 5000, "line_count": 1}
    assert entry.after == {"total_minor": 10000, "line_count": 2}


@pytest.mark.asyncio
async def test_recompute_refreshes_payout_warnings() -> None:
    repo = FakeRepo()
    audit = FakeAudit()
    await repo.save(
        _period(
            [_line("occ-old", 5000)],
            unpaid_occurrence_ids=["occ-old-warning"],
            payout_warnings=[_warning(occurrence_id="occ-old-warning")],
        )
    )
    fresh = _Calc(
        lines=[_line("occ-1", 6000)],
        unpaid=["occ-new-warning"],
        warnings=[_warning(occurrence_id="occ-new-warning", reason="missing_rate")],
    )
    uc = RecomputePayoutPeriod(
        calculator=FakeCalculator(fresh),
        repository=repo,
        audit=audit,
        clock=_clock,
    )

    stored = await uc.execute(period_id="pp-1", actor_id="admin-1")

    assert stored.unpaid_occurrence_ids == ["occ-new-warning"]
    assert [warning.occurrence_id for warning in stored.payout_warnings] == ["occ-new-warning"]
    assert [warning.reason for warning in stored.payout_warnings] == ["missing_rate"]


@pytest.mark.asyncio
async def test_recompute_preserves_manual_overrides() -> None:
    repo = FakeRepo()
    audit = FakeAudit()
    overridden = _line("occ-1", 7500, original_amount_minor=5000, adjustment_reason="agreed bonus")
    await repo.save(_period([overridden, _line("occ-2", 3000)]))
    fresh = _Calc(lines=[_line("occ-1", 5500), _line("occ-2", 3200)])
    uc = RecomputePayoutPeriod(
        calculator=FakeCalculator(fresh), repository=repo, audit=audit, clock=_clock
    )

    stored = await uc.execute(period_id="pp-1", actor_id="admin-1")

    by_occ = {line.occurrence_id: line for line in stored.lines}
    # The override sticks; the freshly computed amount becomes the original.
    assert by_occ["occ-1"].amount_minor == 7500
    assert by_occ["occ-1"].original_amount_minor == 5500
    assert by_occ["occ-1"].adjustment_reason == "agreed bonus"
    # The unadjusted line takes the fresh amount.
    assert by_occ["occ-2"].amount_minor == 3200
    assert stored.total_minor == 7500 + 3200


@pytest.mark.asyncio
async def test_recompute_rejects_non_draft_period() -> None:
    repo = FakeRepo()
    approved = approve(_period([]), at=_dt("2026-06-02T00:00:00"))
    await repo.save(approved)
    uc = RecomputePayoutPeriod(
        calculator=FakeCalculator(_Calc()), repository=repo, audit=FakeAudit()
    )
    with pytest.raises(PayoutPeriodStateError, match="reopen it first"):
        await uc.execute(period_id="pp-1", actor_id="admin-1")


# ---------------------------------------------------------------------------
# ReopenPayoutPeriod
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reopen_paid_period_clears_payment_and_audits_before_snapshot() -> None:
    repo = FakeRepo()
    audit = FakeAudit()
    paid = mark_paid(
        approve(_period([]), at=_dt("2026-06-02T00:00:00")),
        at=_dt("2026-06-03T00:00:00"),
        method="cash",
        amount_minor=0,
        reference="env-7",
    )
    await repo.save(paid)
    uc = ReopenPayoutPeriod(repository=repo, audit=audit, clock=_clock)

    stored = await uc.execute(period_id="pp-1", actor_id="admin-1", reason="attendance was wrong")

    assert stored.status == "draft"
    assert stored.paid_at is None
    assert stored.paid_method is None
    assert stored.paid_reference is None
    assert repo.replace_calls == 1
    entry = audit.entries[0]
    assert entry.action == "reopened"
    assert entry.reason == "attendance was wrong"
    assert entry.before is not None
    assert entry.before["status"] == "paid"
    assert entry.before["paid_method"] == "cash"
    assert entry.after == {"status": "draft"}


@pytest.mark.asyncio
async def test_reopen_requires_reason() -> None:
    repo = FakeRepo()
    await repo.save(approve(_period([]), at=_dt("2026-06-02T00:00:00")))
    uc = ReopenPayoutPeriod(repository=repo, audit=FakeAudit())
    with pytest.raises(ValueError, match="reason is required"):
        await uc.execute(period_id="pp-1", actor_id="admin-1", reason="   ")


@pytest.mark.asyncio
async def test_reopen_rejects_draft_period() -> None:
    repo = FakeRepo()
    await repo.save(_period([]))
    uc = ReopenPayoutPeriod(repository=repo, audit=FakeAudit())
    with pytest.raises(PayoutPeriodStateError, match="already in status 'draft'"):
        await uc.execute(period_id="pp-1", actor_id="admin-1", reason="oops")


# ---------------------------------------------------------------------------
# OverridePayoutLine
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_override_sets_amount_and_rebuilds_total() -> None:
    repo = FakeRepo()
    audit = FakeAudit()
    await repo.save(_period([_line("occ-1", 5000), _line("occ-2", 3000)]))
    uc = OverridePayoutLine(repository=repo, audit=audit, clock=_clock)

    stored = await uc.execute(
        period_id="pp-1",
        occurrence_id="occ-1",
        amount_minor=6500,
        reason="covered extra time",
        actor_id="admin-1",
    )

    by_occ = {line.occurrence_id: line for line in stored.lines}
    assert by_occ["occ-1"].amount_minor == 6500
    assert by_occ["occ-1"].original_amount_minor == 5000
    assert by_occ["occ-1"].adjustment_reason == "covered extra time"
    assert stored.total_minor == 6500 + 3000
    entry = audit.entries[0]
    assert entry.action == "line_overridden"
    assert entry.occurrence_id == "occ-1"
    assert entry.before == {"amount_minor": 5000, "total_minor": 8000}
    assert entry.after == {"amount_minor": 6500, "total_minor": 9500}


@pytest.mark.asyncio
async def test_override_twice_keeps_first_computed_amount_as_original() -> None:
    repo = FakeRepo()
    await repo.save(_period([_line("occ-1", 5000)]))
    uc = OverridePayoutLine(repository=repo, audit=FakeAudit(), clock=_clock)

    await uc.execute(
        period_id="pp-1",
        occurrence_id="occ-1",
        amount_minor=6000,
        reason="first edit",
        actor_id="admin-1",
    )
    stored = await uc.execute(
        period_id="pp-1",
        occurrence_id="occ-1",
        amount_minor=7000,
        reason="second edit",
        actor_id="admin-1",
    )

    assert stored.lines[0].amount_minor == 7000
    assert stored.lines[0].original_amount_minor == 5000


@pytest.mark.asyncio
async def test_clear_override_restores_original_amount() -> None:
    repo = FakeRepo()
    audit = FakeAudit()
    overridden = _line("occ-1", 6500, original_amount_minor=5000, adjustment_reason="extra time")
    await repo.save(_period([overridden]))
    uc = OverridePayoutLine(repository=repo, audit=audit, clock=_clock)

    stored = await uc.execute(
        period_id="pp-1",
        occurrence_id="occ-1",
        amount_minor=None,
        reason="entered by mistake",
        actor_id="admin-1",
    )

    assert stored.lines[0].amount_minor == 5000
    assert stored.lines[0].original_amount_minor is None
    assert stored.lines[0].adjustment_reason is None
    assert stored.total_minor == 5000
    assert audit.entries[0].action == "line_override_cleared"


@pytest.mark.asyncio
async def test_clear_override_on_unadjusted_line_is_rejected() -> None:
    repo = FakeRepo()
    await repo.save(_period([_line("occ-1", 5000)]))
    uc = OverridePayoutLine(repository=repo, audit=FakeAudit())
    with pytest.raises(ValueError, match="no override to clear"):
        await uc.execute(
            period_id="pp-1",
            occurrence_id="occ-1",
            amount_minor=None,
            reason="undo",
            actor_id="admin-1",
        )


@pytest.mark.asyncio
async def test_override_rejects_non_draft_and_unknown_line() -> None:
    repo = FakeRepo()
    await repo.save(approve(_period([_line("occ-1", 5000)]), at=_dt("2026-06-02T00:00:00")))
    uc = OverridePayoutLine(repository=repo, audit=FakeAudit())
    with pytest.raises(PayoutPeriodStateError, match="reopen it first"):
        await uc.execute(
            period_id="pp-1",
            occurrence_id="occ-1",
            amount_minor=100,
            reason="x",
            actor_id="admin-1",
        )

    repo2 = FakeRepo()
    await repo2.save(_period([_line("occ-1", 5000)]))
    uc2 = OverridePayoutLine(repository=repo2, audit=FakeAudit())
    with pytest.raises(LookupError, match="not on payout period"):
        await uc2.execute(
            period_id="pp-1",
            occurrence_id="occ-missing",
            amount_minor=100,
            reason="x",
            actor_id="admin-1",
        )


@pytest.mark.asyncio
async def test_override_requires_reason_and_non_negative_amount() -> None:
    repo = FakeRepo()
    await repo.save(_period([_line("occ-1", 5000)]))
    uc = OverridePayoutLine(repository=repo, audit=FakeAudit())
    with pytest.raises(ValueError, match="reason is required"):
        await uc.execute(
            period_id="pp-1",
            occurrence_id="occ-1",
            amount_minor=100,
            reason="",
            actor_id="admin-1",
        )
    with pytest.raises(ValueError, match="must not be negative"):
        await uc.execute(
            period_id="pp-1",
            occurrence_id="occ-1",
            amount_minor=-1,
            reason="x",
            actor_id="admin-1",
        )


# ---------------------------------------------------------------------------
# ListPayoutAuditEntries
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_audit_entries_filters_by_period() -> None:
    audit = FakeAudit()
    await audit.append(
        PayoutAuditEntry(
            audit_id="a-1",
            academy_id="acad-1",
            period_id="pp-1",
            action="reopened",
            actor_id="admin-1",
            at=_dt("2026-06-05T12:00:00"),
            reason="fix",
        )
    )
    await audit.append(
        PayoutAuditEntry(
            audit_id="a-2",
            academy_id="acad-1",
            period_id="pp-other",
            action="recomputed",
            actor_id="admin-1",
            at=_dt("2026-06-05T12:01:00"),
        )
    )
    uc = ListPayoutAuditEntries(audit=audit)
    entries = await uc.execute(period_id="pp-1")
    assert [e.audit_id for e in entries] == ["a-1"]
