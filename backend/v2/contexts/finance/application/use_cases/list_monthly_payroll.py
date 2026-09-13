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
    warning_count: int = 0
    warning_status: str = "clear"  # "clear" | "unresolved"


@dataclass(frozen=True)
class _DepartedCoach:
    """A coach with a persisted period in the window but no occurrences in it.

    Same shape the occurrence reader returns, so the row loop below needs no
    branch for them.
    """

    coach_id: str
    session_count: int = 0


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
        # #785: enumeration used to start and end at "coaches with occurrences
        # in this window". A coach who left the academy mid-period has none, so
        # their already-generated — and possibly still unpaid — period dropped
        # off the payroll screen entirely and the money was never paid out. A
        # persisted period in this window is itself a row, with a session_count
        # of 0 because there is no occurrence scan to count; the period carries
        # the real figures.
        seen = {c.coach_id for c in coaches}
        coaches = [
            *coaches,
            *(_DepartedCoach(coach_id=coach_id) for coach_id in sorted(set(existing) - seen)),
        ]
        # One batched preview computation for every coach lacking a persisted
        # period — the underlying academy-month occurrence scan is shared
        # instead of repeated per coach (#529).
        ungenerated = [c.coach_id for c in coaches if c.coach_id not in existing]
        calculations = (
            await self._calculator.calculate_many(
                coach_ids=ungenerated,
                academy_id=academy_id,
                period_start=period_start,
                period_end=period_end,
            )
            if ungenerated
            else {}
        )
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
                        unresolved_unpaid_count=len(
                            [row for row in period.unpaid_occurrences if row.unresolved]
                        )
                        or len(period.unpaid_occurrence_ids),
                        warning_count=len(period.payout_warnings),
                        warning_status=(
                            "unresolved"
                            if period.payout_warnings
                            or period.unpaid_occurrence_ids
                            or any(row.unresolved for row in period.unpaid_occurrences)
                            else "clear"
                        ),
                    )
                )
            else:
                calc = calculations[c.coach_id]
                rows.append(
                    MonthlyPayrollRow(
                        coach_id=c.coach_id,
                        session_count=c.session_count,
                        total_minor=calc.total_minor,
                        currency=calc.currency,
                        status="not_generated",
                        period_id=None,
                        unresolved_unpaid_count=len(calc.unpaid_occurrence_ids),
                        warning_count=len(getattr(calc, "payout_warnings", [])),
                        warning_status=(
                            "unresolved"
                            if getattr(calc, "payout_warnings", [])
                            or getattr(calc, "unpaid_occurrence_ids", [])
                            else "clear"
                        ),
                    )
                )
        return sorted(rows, key=lambda r: r.coach_id)
