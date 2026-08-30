"""Bulk month-level payroll operations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from backend.v2.contexts.finance.application.ports import (
    MonthlyCoachOccurrenceReader,
    PayoutPeriodRepository,
)
from backend.v2.contexts.finance.application.use_cases.generate_payout_period import (
    GeneratePayoutPeriod,
    OverlappingPayoutPeriodError,
)
from backend.v2.contexts.finance.application.use_cases.manage_payout_period import (
    RecomputePayoutPeriod,
)


@dataclass(frozen=True)
class BulkGenerateResult:
    generated: int
    skipped: int


@dataclass(frozen=True)
class BulkRecomputeResult:
    recomputed: int
    skipped: int


class BulkGeneratePayroll:
    def __init__(
        self,
        *,
        reader: MonthlyCoachOccurrenceReader,
        periods: PayoutPeriodRepository,
        generate: GeneratePayoutPeriod,
    ) -> None:
        self._reader = reader
        self._periods = periods
        self._generate = generate

    async def execute(
        self, *, academy_id: str, period_start: datetime, period_end: datetime
    ) -> BulkGenerateResult:
        coaches = await self._reader.coaches_with_occurrences(
            academy_id=academy_id, period_start=period_start, period_end=period_end
        )
        generated = skipped = 0
        for c in coaches:
            existing = await self._periods.find_by_window(
                coach_id=c.coach_id, period_start=period_start, period_end=period_end
            )
            if existing is not None:
                skipped += 1
                continue
            try:
                await self._generate.execute(
                    coach_id=c.coach_id,
                    academy_id=academy_id,
                    period_start=period_start,
                    period_end=period_end,
                )
            except OverlappingPayoutPeriodError:
                # A pre-existing custom-window period intersects this
                # month for the coach; skip rather than double-pay (#504).
                skipped += 1
                continue
            generated += 1
        return BulkGenerateResult(generated=generated, skipped=skipped)


class BulkRecomputePayroll:
    def __init__(
        self, *, periods: PayoutPeriodRepository, recompute: RecomputePayoutPeriod
    ) -> None:
        self._periods = periods
        self._recompute = recompute

    async def execute(
        self, *, academy_id: str, period_start: datetime, period_end: datetime, actor_id: str
    ) -> BulkRecomputeResult:
        periods = await self._periods.list_for_window(
            academy_id=academy_id, period_start=period_start, period_end=period_end
        )
        recomputed = skipped = 0
        for p in periods:
            if p.status != "draft":
                skipped += 1
                continue
            await self._recompute.execute(period_id=p.period_id, actor_id=actor_id)
            recomputed += 1
        return BulkRecomputeResult(recomputed=recomputed, skipped=skipped)
