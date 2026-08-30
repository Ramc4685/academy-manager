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

Overlap guard (#504):

- A requested window that intersects (but does not exactly match) an
  existing period for the same coach is rejected with
  ``OverlappingPayoutPeriodError`` — otherwise two periods could both
  contain lines for the same occurrence and independently be approved
  and paid, paying that occurrence twice.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from backend.v2.contexts.finance.application.ports import (
    PayoutCalculator,
    PayoutPeriodRepository,
)
from backend.v2.contexts.finance.domain.payout_period import PayoutPeriod, PayoutWarning
from backend.v2.shared.ids import new_ulid


class OverlappingPayoutPeriodError(ValueError):
    """Requested window intersects an existing payout period for the coach."""

    def __init__(self, existing: PayoutPeriod) -> None:
        super().__init__(
            "Requested window overlaps existing payout period "
            f"{existing.period_id!r} ({existing.period_start.isoformat()} — "
            f"{existing.period_end.isoformat()}, status {existing.status!r}) "
            "for this coach; the same occurrence must not be paid twice."
        )
        self.existing = existing


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

        overlapping = await self._repo.find_overlapping(
            coach_id=coach_id,
            period_start=period_start,
            period_end=period_end,
        )
        if overlapping is not None:
            raise OverlappingPayoutPeriodError(overlapping)

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
            unpaid_occurrences=list(calc.unpaid_occurrences),
            payout_warnings=[
                PayoutWarning.model_validate(
                    warning.model_dump() if hasattr(warning, "model_dump") else warning
                )
                for warning in getattr(calc, "payout_warnings", [])
            ],
            generated_at=self._clock(),
            approved_at=None,
            paid_at=None,
        )
        return await self._repo.save(period)
