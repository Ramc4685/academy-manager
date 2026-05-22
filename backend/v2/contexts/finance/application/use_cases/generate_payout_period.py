"""Generate (or fetch existing) ``PayoutPeriod`` for a coach + window.

Calls the injected ``PayoutCalculator`` adapter (which wraps the coaching
context's ``ComputeCoachPayout``), then persists the resulting period and
its lines atomically through the ``PayoutPeriodRepository``.

Idempotency:

- The natural key is ``(academy_id, coach_id, period_start, period_end)``.
- If a period already exists for that key, the use case returns it
  unchanged — the caller is expected to re-generate explicitly via a
  separate flow (out of scope for this slice) if rates changed and the
  period is still in ``draft``.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from backend.v2.contexts.finance.application.ports import (
    PayoutCalculator,
    PayoutPeriodRepository,
)
from backend.v2.contexts.finance.domain.payout_period import PayoutPeriod
from backend.v2.shared.ids import new_ulid


class GeneratePayoutPeriod:
    def __init__(
        self,
        *,
        calculator: PayoutCalculator,
        repository: PayoutPeriodRepository,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        id_factory: Callable[[], str] = lambda: str(new_ulid()),
    ) -> None:
        self._calc = calculator
        self._repo = repository
        self._clock = clock
        self._id = id_factory

    async def execute(
        self,
        *,
        coach_id: str,
        academy_id: str,
        period_start: datetime,
        period_end: datetime,
    ) -> PayoutPeriod:
        if period_end <= period_start:
            raise ValueError("period_end must be after period_start")

        existing = await self._repo.find_by_window(
            coach_id=coach_id,
            period_start=period_start,
            period_end=period_end,
        )
        if existing is not None:
            return existing

        calc = await self._calc.calculate(
            coach_id=coach_id,
            academy_id=academy_id,
            period_start=period_start,
            period_end=period_end,
        )

        period = PayoutPeriod(
            period_id=self._id(),
            academy_id=academy_id,
            coach_id=coach_id,
            period_start=period_start,
            period_end=period_end,
            status="draft",
            currency=calc.currency,
            total_minor=calc.total_minor,
            lines=list(calc.lines),
            unpaid_occurrence_ids=list(calc.unpaid_occurrence_ids),
            generated_at=self._clock(),
            approved_at=None,
            paid_at=None,
        )
        return await self._repo.save(period)
