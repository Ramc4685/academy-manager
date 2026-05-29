"""Compute a coach's payout statement for a date range (Wave 4A).

This use case is independent of the billing ledger — payout is a function
of *what work happened* (occurrences) and *how the coach is paid* (rate
sheet), not of whether the academy has been paid by the customer yet.
That deliberate separation keeps the academy from withholding coach pay
on accounts-receivable timing.

Eligibility (per occurrence):

1. ``period_start <= occurrence.start_at < period_end``
2. ``occurrence.status == "completed"``
3. ``occurrence.is_payable is True``
4. Attributed coach == requested ``coach_id``, where the attribution rule is:
   ``actual_coach_id ?? substitute_coach_id ?? scheduled_coach_id``.
5. A ``CoachRate`` exists for that coach effective at
   ``occurrence.start_at``. If not, the occurrence is reported in
   ``unpaid_occurrence_ids`` rather than silently dropped.

Amount calculation:

- ``per_session`` rates yield ``rate.amount_minor`` per occurrence.
- ``per_hour`` rates yield
  ``int(round_half_even(amount_minor * minutes / 60))``.
"""

from __future__ import annotations

from datetime import datetime
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Protocol

from backend.v2.contexts.coaching.domain.payout import (
    CoachRate,
    PayableOccurrence,
    PayoutBasis,
    PayoutLine,
    PayoutStatement,
)


class PayableOccurrenceQuery(Protocol):
    """Returns occurrences in the period for a given academy.

    The query is per-academy (not per-coach) because attribution to the
    paying coach is a domain rule that lives in this use case, not in the
    adapter.
    """

    async def list_in_period(
        self,
        academy_id: str,
        period_start: datetime,
        period_end: datetime,
    ) -> list[PayableOccurrence]: ...


class CoachRateRepository(Protocol):
    async def find_for_coach_at(self, coach_id: str, at_time: datetime) -> CoachRate | None: ...


def _paying_coach(occ: PayableOccurrence) -> tuple[str, PayoutBasis]:
    if occ.actual_coach_id:
        return occ.actual_coach_id, "actual"
    if occ.substitute_coach_id:
        return occ.substitute_coach_id, "substitute"
    return occ.scheduled_coach_id, "scheduled"


def _occurrence_minutes(occ: PayableOccurrence) -> Decimal:
    seconds = Decimal((occ.end_at - occ.start_at).total_seconds())
    return (seconds / Decimal(60)).quantize(Decimal("0.0001"))


def _compute_line_amount_minor(rate: CoachRate, minutes: Decimal) -> int:
    if rate.billing_unit == "per_session":
        return rate.amount_minor
    if rate.billing_unit == "per_hour":
        amount = (Decimal(rate.amount_minor) * minutes / Decimal(60)).quantize(
            Decimal("1"), rounding=ROUND_HALF_EVEN
        )
        return int(amount)
    raise ValueError(f"Unknown billing_unit: {rate.billing_unit!r}")


def _ensure_statement_currency(current: str | None, incoming: str, *, coach_id: str) -> str:
    if current is None:
        return incoming
    if current != incoming:
        raise ValueError(
            f"Currency mismatch for coach {coach_id!r}: statement "
            f"started in {current!r} but next line is {incoming!r}"
        )
    return current


class ComputeCoachPayout:
    """Returns the ``PayoutStatement`` for one coach over a period."""

    def __init__(
        self,
        occurrences: PayableOccurrenceQuery,
        rates: CoachRateRepository,
    ) -> None:
        self._occurrences = occurrences
        self._rates = rates

    async def execute(
        self,
        *,
        coach_id: str,
        academy_id: str,
        period_start: datetime,
        period_end: datetime,
    ) -> PayoutStatement:
        if period_end <= period_start:
            raise ValueError("period_end must be after period_start")

        occs = await self._occurrences.list_in_period(academy_id, period_start, period_end)

        lines: list[PayoutLine] = []
        unpaid: list[str] = []
        currency: str | None = None

        for occ in occs:
            if not occ.is_payable:
                continue

            if occ.coach_attendance:
                for attendance in occ.coach_attendance:
                    if attendance.coach_id != coach_id or attendance.status != "present":
                        continue

                    minutes = _occurrence_minutes(occ)
                    if attendance.rate_override_minor is not None:
                        line_currency = currency or "USD"
                        currency = _ensure_statement_currency(
                            currency, line_currency, coach_id=coach_id
                        )
                        lines.append(
                            PayoutLine(
                                occurrence_id=occ.occurrence_id,
                                coach_id=coach_id,
                                basis=attendance.role,
                                minutes=minutes,
                                amount_minor=attendance.rate_override_minor,
                                currency=line_currency,
                                rate_id=f"override:{occ.occurrence_id}:{coach_id}",
                            )
                        )
                        continue

                    rate = await self._rates.find_for_coach_at(coach_id, occ.start_at)
                    if rate is None:
                        unpaid.append(occ.occurrence_id)
                        continue

                    currency = _ensure_statement_currency(
                        currency, rate.currency, coach_id=coach_id
                    )
                    lines.append(
                        PayoutLine(
                            occurrence_id=occ.occurrence_id,
                            coach_id=coach_id,
                            basis=attendance.role,
                            minutes=minutes,
                            amount_minor=_compute_line_amount_minor(rate, minutes),
                            currency=rate.currency,
                            rate_id=rate.rate_id,
                        )
                    )
                continue

            if occ.status != "completed":
                continue

            paying_coach, basis = _paying_coach(occ)
            if paying_coach != coach_id:
                continue

            rate = await self._rates.find_for_coach_at(coach_id, occ.start_at)
            if rate is None:
                unpaid.append(occ.occurrence_id)
                continue

            currency = _ensure_statement_currency(currency, rate.currency, coach_id=coach_id)

            minutes = _occurrence_minutes(occ)
            amount_minor = _compute_line_amount_minor(rate, minutes)
            lines.append(
                PayoutLine(
                    occurrence_id=occ.occurrence_id,
                    coach_id=coach_id,
                    basis=basis,
                    minutes=minutes,
                    amount_minor=amount_minor,
                    currency=rate.currency,
                    rate_id=rate.rate_id,
                )
            )

        return PayoutStatement(
            coach_id=coach_id,
            academy_id=academy_id,
            period_start=period_start,
            period_end=period_end,
            currency=currency or "USD",
            lines=lines,
            total_minor=sum(line.amount_minor for line in lines),
            unpaid_occurrence_ids=unpaid,
        )
