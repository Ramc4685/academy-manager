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
   ``actual_coach_id ?? scheduled_coach_id``. A replacement coach is paid
   by being set as ``actual_coach_id``; the originally scheduled coach then
   no longer matches and is not paid for that occurrence.
5. The attributed coach is not marked **absent** in coach attendance for
   the occurrence. Absent occurrences are reported in
   ``absent_occurrence_ids`` (policy: a coach is paid unless explicitly
   marked absent).
6. A ``CoachRate`` exists for that coach effective at
   ``occurrence.start_at``, OR the coach's attendance row carries a
   ``rate_override_minor``. Occurrences with neither are reported in
   ``unpaid_occurrence_ids`` rather than silently dropped.

Amount calculation (in precedence order):

- An attendance ``rate_override_minor`` pays exactly that amount.
- ``per_session`` rates yield ``rate.amount_minor`` per occurrence.
- ``per_hour`` rates yield
  ``int(round_half_even(amount_minor * minutes / 60))``.
- ``percent_of_revenue`` rates yield
  ``int(round_half_even(expected_revenue_minor * percent_bps / 10000))``.
  If the occurrence has no ``expected_revenue_minor`` (session has no
  price), it is reported in ``unpaid_occurrence_ids``.
"""

from __future__ import annotations

from datetime import datetime
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Protocol

from backend.v2.contexts.coaching.domain.payout import (
    CoachAttendanceForPayout,
    CoachRate,
    PayableOccurrence,
    PayoutBasis,
    PayoutLine,
    PayoutStatement,
)

ATTENDANCE_OVERRIDE_RATE_ID = "attendance-override"


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
        if occ.actual_coach_id != occ.scheduled_coach_id:
            return occ.actual_coach_id, "substitute"
        return occ.actual_coach_id, "actual"
    return occ.scheduled_coach_id, "scheduled"


def _attendance_for(occ: PayableOccurrence, coach_id: str) -> CoachAttendanceForPayout | None:
    for row in occ.coach_attendance:
        if row.coach_id == coach_id:
            return row
    return None


def _occurrence_minutes(occ: PayableOccurrence) -> Decimal:
    seconds = Decimal((occ.end_at - occ.start_at).total_seconds())
    return (seconds / Decimal(60)).quantize(Decimal("0.0001"))


def _round_half_even_minor(amount: Decimal) -> int:
    return int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_EVEN))


def _compute_line_amount_minor(
    rate: CoachRate,
    minutes: Decimal,
    expected_revenue_minor: int | None,
) -> int | None:
    """Returns the line amount, or ``None`` when the rate cannot be applied
    (percent rate with no revenue basis)."""
    if rate.billing_unit == "per_session":
        return rate.amount_minor
    if rate.billing_unit == "per_hour":
        return _round_half_even_minor(Decimal(rate.amount_minor) * minutes / Decimal(60))
    if rate.billing_unit == "percent_of_revenue":
        if expected_revenue_minor is None or rate.percent_bps is None:
            return None
        return _round_half_even_minor(
            Decimal(expected_revenue_minor) * Decimal(rate.percent_bps) / Decimal(10000)
        )
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
        absent: list[str] = []
        currency: str | None = None

        for occ in occs:
            if not occ.is_payable:
                continue

            if occ.status != "completed":
                continue

            paying_coach, basis = _paying_coach(occ)
            if paying_coach != coach_id:
                continue

            attendance = _attendance_for(occ, coach_id)
            if attendance is not None and attendance.status == "absent":
                absent.append(occ.occurrence_id)
                continue

            rate = await self._rates.find_for_coach_at(coach_id, occ.start_at)
            override_minor = attendance.rate_override_minor if attendance else None
            if rate is None and override_minor is None:
                unpaid.append(occ.occurrence_id)
                continue

            minutes = _occurrence_minutes(occ)
            if override_minor is not None:
                amount_minor = override_minor
            else:
                assert rate is not None
                computed = _compute_line_amount_minor(rate, minutes, occ.expected_revenue_minor)
                if computed is None:
                    unpaid.append(occ.occurrence_id)
                    continue
                amount_minor = computed

            line_currency = rate.currency if rate is not None else (currency or "USD")
            currency = _ensure_statement_currency(currency, line_currency, coach_id=coach_id)

            is_percent = (
                override_minor is None
                and rate is not None
                and rate.billing_unit == "percent_of_revenue"
            )
            lines.append(
                PayoutLine(
                    occurrence_id=occ.occurrence_id,
                    coach_id=coach_id,
                    basis=basis,
                    minutes=minutes,
                    amount_minor=amount_minor,
                    currency=line_currency,
                    rate_id=(
                        rate.rate_id
                        if override_minor is None and rate is not None
                        else ATTENDANCE_OVERRIDE_RATE_ID
                    ),
                    percent_bps=rate.percent_bps if is_percent else None,
                    expected_revenue_minor=occ.expected_revenue_minor if is_percent else None,
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
            absent_occurrence_ids=absent,
        )
