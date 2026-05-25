"""Tests for the persisted ``PayoutPeriod`` (Wave 5A Stream J).

Three behaviours under test:

1. **Generation**: ``GeneratePayoutPeriod`` calls the calculator, builds a
   draft period, and persists it. Re-running for the same window is
   idempotent — same period, same lines, no second write.
2. **State machine**: ``ApprovePayoutPeriod`` and ``MarkPayoutPaid`` enforce
   ``draft -> approved -> paid`` and refuse illegal transitions.
3. **Domain invariants**: ``PayoutPeriod`` rejects bad date windows,
   line-sum mismatches, and missing timestamps for non-draft states.

All persistence here uses an in-memory fake of the repo port; the
Mongo-backed adapter is covered by the contract test.
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
from backend.v2.contexts.finance.domain.payout_period import (
    PayoutPeriod,
    PayoutPeriodStateError,
    PersistedPayoutLine,
    approve,
    mark_paid,
)


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _Calculation:
    """In-memory ``PayoutCalculation`` for tests."""

    def __init__(
        self,
        *,
        coach_id: str,
        academy_id: str,
        period_start: datetime,
        period_end: datetime,
        currency: str = "USD",
        total_minor: int = 0,
        lines: list[PersistedPayoutLine] | None = None,
        unpaid: list[str] | None = None,
    ) -> None:
        self.coach_id = coach_id
        self.academy_id = academy_id
        self.period_start = period_start
        self.period_end = period_end
        self.currency = currency
        self.total_minor = total_minor
        self.lines = lines or []
        self.unpaid_occurrence_ids = unpaid or []


class FakeCalculator:
    def __init__(self, result: _Calculation) -> None:
        self._result = result
        self.calls = 0

    async def calculate(
        self,
        *,
        coach_id: str,
        academy_id: str,
        period_start: datetime,
        period_end: datetime,
    ) -> _Calculation:
        self.calls += 1
        return self._result


class FakeRepo:
    def __init__(self) -> None:
        self._by_id: dict[str, PayoutPeriod] = {}
        self.save_calls = 0
        self.replace_calls = 0

    @staticmethod
    def _key(p: PayoutPeriod) -> tuple[str, str, datetime, datetime]:
        return (p.academy_id, p.coach_id, p.period_start, p.period_end)

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
        existing = await self.find_by_window(
            coach_id=period.coach_id,
            period_start=period.period_start,
            period_end=period.period_end,
        )
        if existing is not None:
            return existing
        self.save_calls += 1
        self._by_id[period.period_id] = period
        return period

    async def replace(self, period: PayoutPeriod) -> PayoutPeriod:
        if period.period_id not in self._by_id:
            raise LookupError(period.period_id)
        self.replace_calls += 1
        self._by_id[period.period_id] = period
        return period


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------


def test_period_rejects_inverted_window() -> None:
    with pytest.raises(ValueError, match="period_end must be after period_start"):
        PayoutPeriod(
            period_id="pp-1",
            academy_id="acad-1",
            coach_id="coach-A",
            period_start=_dt("2026-06-01T00:00:00"),
            period_end=_dt("2026-05-01T00:00:00"),
            currency="USD",
            total_minor=0,
            lines=[],
            generated_at=_dt("2026-06-01T00:00:00"),
        )


def test_period_rejects_total_that_does_not_match_lines() -> None:
    line = PersistedPayoutLine(
        occurrence_id="occ-1",
        coach_id="coach-A",
        basis="scheduled",
        minutes=Decimal("60"),
        amount_minor=5000,
        currency="USD",
        rate_id="cr-1",
    )
    with pytest.raises(ValueError, match="does not"):
        PayoutPeriod(
            period_id="pp-1",
            academy_id="acad-1",
            coach_id="coach-A",
            period_start=_dt("2026-05-01T00:00:00"),
            period_end=_dt("2026-06-01T00:00:00"),
            currency="USD",
            total_minor=9999,  # wrong
            lines=[line],
            generated_at=_dt("2026-06-01T00:00:00"),
        )


def test_paid_status_requires_both_approved_and_paid_timestamps() -> None:
    with pytest.raises(ValueError, match="paid_at"):
        PayoutPeriod(
            period_id="pp-1",
            academy_id="acad-1",
            coach_id="coach-A",
            period_start=_dt("2026-05-01T00:00:00"),
            period_end=_dt("2026-06-01T00:00:00"),
            status="paid",
            currency="USD",
            total_minor=0,
            lines=[],
            generated_at=_dt("2026-06-01T00:00:00"),
            approved_at=_dt("2026-06-02T00:00:00"),
            paid_at=None,
        )


# ---------------------------------------------------------------------------
# Pure transitions
# ---------------------------------------------------------------------------


def _draft_period(**overrides) -> PayoutPeriod:
    base = dict(
        period_id="pp-1",
        academy_id="acad-1",
        coach_id="coach-A",
        period_start=_dt("2026-05-01T00:00:00"),
        period_end=_dt("2026-06-01T00:00:00"),
        currency="USD",
        total_minor=0,
        lines=[],
        unpaid_occurrence_ids=[],
        generated_at=_dt("2026-06-01T00:00:00"),
        paid_method=None,
        paid_amount_minor=None,
        paid_reference=None,
    )
    base.update(overrides)
    return PayoutPeriod(**base)


def test_approve_moves_draft_to_approved() -> None:
    period = _draft_period()
    approved = approve(period, at=_dt("2026-06-02T12:00:00"))
    assert approved.status == "approved"
    assert approved.approved_at == _dt("2026-06-02T12:00:00")


def test_approve_is_idempotent_on_approved() -> None:
    period = approve(_draft_period(), at=_dt("2026-06-02T12:00:00"))
    again = approve(period, at=_dt("2026-06-03T12:00:00"))
    assert again is period
    assert again.approved_at == _dt("2026-06-02T12:00:00")


def test_approve_rejects_paid_period() -> None:
    period = approve(_draft_period(), at=_dt("2026-06-02T12:00:00"))
    period = mark_paid(
        period,
        at=_dt("2026-06-03T12:00:00"),
        method="cash",
        amount_minor=0,
    )
    with pytest.raises(PayoutPeriodStateError):
        approve(period, at=_dt("2026-06-04T12:00:00"))


def test_mark_paid_rejects_draft() -> None:
    with pytest.raises(PayoutPeriodStateError):
        mark_paid(
            _draft_period(),
            at=_dt("2026-06-02T12:00:00"),
            method="cash",
            amount_minor=0,
        )


# ---------------------------------------------------------------------------
# GeneratePayoutPeriod
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_persists_a_draft_period() -> None:
    line = PersistedPayoutLine(
        occurrence_id="occ-1",
        coach_id="coach-A",
        basis="scheduled",
        minutes=Decimal("60"),
        amount_minor=5000,
        currency="USD",
        rate_id="cr-1",
    )
    calc = _Calculation(
        coach_id="coach-A",
        academy_id="acad-1",
        period_start=_dt("2026-05-01T00:00:00"),
        period_end=_dt("2026-06-01T00:00:00"),
        currency="USD",
        total_minor=5000,
        lines=[line],
        unpaid=["occ-2"],
    )
    repo = FakeRepo()
    use_case = GeneratePayoutPeriod(
        calculator=FakeCalculator(calc),
        repository=repo,
        clock=lambda: _dt("2026-06-01T00:00:00"),
        id_factory=lambda: "pp-generated",
    )
    period = await use_case.execute(
        coach_id="coach-A",
        academy_id="acad-1",
        period_start=_dt("2026-05-01T00:00:00"),
        period_end=_dt("2026-06-01T00:00:00"),
    )
    assert period.period_id == "pp-generated"
    assert period.status == "draft"
    assert period.total_minor == 5000
    assert len(period.lines) == 1
    assert period.unpaid_occurrence_ids == ["occ-2"]
    assert repo.save_calls == 1


@pytest.mark.asyncio
async def test_generate_is_idempotent_on_natural_key() -> None:
    calc = _Calculation(
        coach_id="coach-A",
        academy_id="acad-1",
        period_start=_dt("2026-05-01T00:00:00"),
        period_end=_dt("2026-06-01T00:00:00"),
        total_minor=0,
    )
    calculator = FakeCalculator(calc)
    repo = FakeRepo()
    use_case = GeneratePayoutPeriod(
        calculator=calculator,
        repository=repo,
        clock=lambda: _dt("2026-06-01T00:00:00"),
        id_factory=lambda: "pp-generated",
    )
    first = await use_case.execute(
        coach_id="coach-A",
        academy_id="acad-1",
        period_start=_dt("2026-05-01T00:00:00"),
        period_end=_dt("2026-06-01T00:00:00"),
    )
    second = await use_case.execute(
        coach_id="coach-A",
        academy_id="acad-1",
        period_start=_dt("2026-05-01T00:00:00"),
        period_end=_dt("2026-06-01T00:00:00"),
    )
    assert first.period_id == second.period_id
    assert repo.save_calls == 1
    # Calculator is not called twice; the second call short-circuits.
    assert calculator.calls == 1


@pytest.mark.asyncio
async def test_generate_rejects_inverted_window() -> None:
    repo = FakeRepo()
    use_case = GeneratePayoutPeriod(
        calculator=FakeCalculator(
            _Calculation(
                coach_id="coach-A",
                academy_id="acad-1",
                period_start=_dt("2026-05-01T00:00:00"),
                period_end=_dt("2026-06-01T00:00:00"),
            )
        ),
        repository=repo,
    )
    with pytest.raises(ValueError, match="period_end must be after"):
        await use_case.execute(
            coach_id="coach-A",
            academy_id="acad-1",
            period_start=_dt("2026-06-01T00:00:00"),
            period_end=_dt("2026-05-01T00:00:00"),
        )


# ---------------------------------------------------------------------------
# Approve / MarkPaid use cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approve_use_case_persists_transition() -> None:
    repo = FakeRepo()
    period = _draft_period()
    await repo.save(period)
    uc = ApprovePayoutPeriod(repository=repo, clock=lambda: _dt("2026-06-02T12:00:00"))
    approved = await uc.execute(period_id="pp-1")
    assert approved.status == "approved"
    assert approved.approved_at == _dt("2026-06-02T12:00:00")
    assert repo.replace_calls == 1


@pytest.mark.asyncio
async def test_approve_use_case_is_idempotent() -> None:
    repo = FakeRepo()
    period = _draft_period()
    await repo.save(period)
    uc = ApprovePayoutPeriod(repository=repo, clock=lambda: _dt("2026-06-02T12:00:00"))
    await uc.execute(period_id="pp-1")
    await uc.execute(period_id="pp-1")
    # Only the first call writes.
    assert repo.replace_calls == 1


@pytest.mark.asyncio
async def test_mark_paid_use_case_requires_approval_first() -> None:
    repo = FakeRepo()
    await repo.save(_draft_period())
    uc = MarkPayoutPaid(repository=repo, clock=lambda: _dt("2026-06-03T12:00:00"))
    with pytest.raises(PayoutPeriodStateError):
        await uc.execute(period_id="pp-1")


@pytest.mark.asyncio
async def test_mark_paid_use_case_full_flow() -> None:
    repo = FakeRepo()
    await repo.save(_draft_period())
    approver = ApprovePayoutPeriod(repository=repo, clock=lambda: _dt("2026-06-02T12:00:00"))
    payer = MarkPayoutPaid(repository=repo, clock=lambda: _dt("2026-06-03T12:00:00"))
    await approver.execute(period_id="pp-1")
    paid = await payer.execute(
        MarkPayoutPaidCommand(
            period_id="pp-1",
            method="bank_transfer",
            paid_at=_dt("2026-06-03T12:00:00"),
            amount_minor=0,
            reference="ach-123",
        )
    )
    assert paid.status == "paid"
    assert paid.paid_at == _dt("2026-06-03T12:00:00")
    assert paid.approved_at == _dt("2026-06-02T12:00:00")
    assert paid.paid_method == "bank_transfer"
    assert paid.paid_amount_minor == 0
    assert paid.paid_reference == "ach-123"


@pytest.mark.asyncio
async def test_mark_paid_use_case_is_idempotent_and_preserves_payment_metadata() -> None:
    repo = FakeRepo()
    await repo.save(_draft_period())
    approver = ApprovePayoutPeriod(repository=repo, clock=lambda: _dt("2026-06-02T12:00:00"))
    payer = MarkPayoutPaid(repository=repo, clock=lambda: _dt("2026-06-03T12:00:00"))
    await approver.execute(period_id="pp-1")
    first = await payer.execute(
        MarkPayoutPaidCommand(
            period_id="pp-1",
            method="cash",
            paid_at=_dt("2026-06-03T12:00:00"),
            amount_minor=0,
            reference="cash-envelope-7",
        )
    )
    second = await payer.execute(
        MarkPayoutPaidCommand(
            period_id="pp-1",
            method="check",
            paid_at=_dt("2026-06-04T12:00:00"),
            amount_minor=9999,
            reference="retry-should-not-overwrite",
        )
    )
    assert second is first
    assert second.paid_method == "cash"
    assert second.paid_at == _dt("2026-06-03T12:00:00")
    assert second.paid_amount_minor == 0
    assert second.paid_reference == "cash-envelope-7"
    assert repo.replace_calls == 2


@pytest.mark.asyncio
async def test_approve_use_case_raises_when_period_missing() -> None:
    repo = FakeRepo()
    uc = ApprovePayoutPeriod(repository=repo)
    with pytest.raises(LookupError):
        await uc.execute(period_id="missing")
