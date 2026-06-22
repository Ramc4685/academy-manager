"""List one row per coach with occurrences in a month, sourced from PayoutPeriod."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from backend.v2.contexts.finance.application.ports import (
    MonthlyCoachOccurrenceReader,
    PayoutCalculator,
    PayoutPeriodRepository,
)


@dataclass(frozen=True)
class MonthlyPayrollRow:
    coach_id: str
    session_count: int
    total_minor: int
    currency: str
    status: str  # "not_generated" | "draft" | "approved" | "paid"
    period_id: str | None
    unresolved_unpaid_count: int = 0


class ListMonthlyPayroll:
    def __init__(
        self,
        *,
        reader: MonthlyCoachOccurrenceReader,
        periods: PayoutPeriodRepository,
        calculator: PayoutCalculator,
    ) -> None:
        self._reader = reader
        self._periods = periods
        self._calculator = calculator

    async def execute(
        self, *, academy_id: str, period_start: datetime, period_end: datetime
    ) -> list[MonthlyPayrollRow]:
        coaches = await self._reader.coaches_with_occurrences(
            academy_id=academy_id, period_start=period_start, period_end=period_end
        )
        existing = {
            p.coach_id: p
            for p in await self._periods.list_for_window(
                academy_id=academy_id, period_start=period_start, period_end=period_end
            )
        }
        rows: list[MonthlyPayrollRow] = []
        for c in coaches:
            period = existing.get(c.coach_id)
            if period is not None:
                rows.append(
                    MonthlyPayrollRow(
                        coach_id=c.coach_id,
                        session_count=c.session_count,
                        total_minor=period.total_minor,
                        currency=period.currency,
                        status=period.status,
                        period_id=period.period_id,
                        unresolved_unpaid_count=len(period.unpaid_occurrence_ids),
                    )
                )
            else:
                calc = await self._calculator.calculate(
                    coach_id=c.coach_id,
                    academy_id=academy_id,
                    period_start=period_start,
                    period_end=period_end,
                )
                rows.append(
                    MonthlyPayrollRow(
                        coach_id=c.coach_id,
                        session_count=c.session_count,
                        total_minor=calc.total_minor,
                        currency=calc.currency,
                        status="not_generated",
                        period_id=None,
                        unresolved_unpaid_count=len(calc.unpaid_occurrence_ids),
                    )
                )
        return sorted(rows, key=lambda r: r.coach_id)
