"""S59: a coach's own hours and payslips (decision D-05, option 3).

What a coach may see about their pay: the classes they taught in a month and
the payslip once the academy approved or paid it. Never a draft, never a
rate, never a per-class amount, never the revenue behind a percentage rate.
The DTOs below are new and narrow on purpose: nothing here is a
``PayoutPeriod`` with fields dropped, so a field added to the payout model
can never leak through this read.

The coach id is always the signed-in user (the route passes
``claims.user_id``); there is no parameter to name another coach.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from typing import Literal, Protocol

from pydantic import BaseModel

from backend.v2.shared.http.errors import DomainError

#: How far back a coach can step: the current month and the 23 before it.
MONTHS_BACK = 23

PayRole = Literal["lead", "cover", "assistant"]

_METHOD_LABELS = {
    "bank_transfer": "bank transfer",
    "cash": "cash",
    "check": "check",
    "other": "other",
}


class InvalidPayMonth(DomainError):
    code = "Finance.InvalidPayMonth"
    status_code = 422


class CoachPayClass(BaseModel):
    model_config = {"frozen": True}

    occurrence_id: str
    start_at: datetime
    class_name: str
    minutes: int
    role: PayRole


class CoachPayslip(BaseModel):
    model_config = {"frozen": True}

    period_start: date
    period_end: date
    status: Literal["approved", "paid"]
    total_cents: int
    currency: str
    approved_on: date | None = None
    paid_on: date | None = None
    paid_method_label: str | None = None
    paid_amount_cents: int | None = None


class CoachPaySummary(BaseModel):
    model_config = {"frozen": True}

    month: str
    month_label: str
    classes_taught: int
    minutes_taught: int
    classes: list[CoachPayClass]
    payslip: CoachPayslip | None = None


class PayslipRow(BaseModel):
    """The only payout-period fields the reader may hand over."""

    model_config = {"frozen": True}

    period_start: date
    period_end: date
    status: str
    total_minor: int
    currency: str
    approved_on: date | None = None
    paid_on: date | None = None
    paid_method: str | None = None
    paid_amount_minor: int | None = None


class CoachPayReader(Protocol):
    async def academy_timezone(self, academy_id: str) -> str | None: ...

    async def taught_classes(
        self, *, academy_id: str, coach_id: str, start: datetime, end: datetime
    ) -> list[CoachPayClass]: ...

    async def released_payslip(
        self, *, academy_id: str, coach_id: str, start: datetime, end: datetime
    ) -> PayslipRow | None:
        """The latest approved or paid period overlapping ``[start, end)``."""
        ...


def _shift(year: int, month: int, by: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + by
    return index // 12, index % 12 + 1


def allowed_month(month: str | None, *, today: date) -> str:
    current = f"{today.year:04d}-{today.month:02d}"
    if month is None:
        return current
    try:
        year, mon = (int(part) for part in month.split("-", 1))
        if not 1 <= mon <= 12 or len(month) != 7:
            raise ValueError
    except ValueError as exc:
        raise InvalidPayMonth("month must be YYYY-MM", month=month) from exc
    first_year, first_month = _shift(today.year, today.month, -MONTHS_BACK)
    earliest = f"{first_year:04d}-{first_month:02d}"
    if not earliest <= f"{year:04d}-{mon:02d}" <= current:
        raise InvalidPayMonth("month is outside the last two years", month=month)
    return f"{year:04d}-{mon:02d}"


class GetCoachPaySummary:
    def __init__(
        self,
        *,
        reader: CoachPayReader,
        month_window: Callable[[str, str | None], tuple[datetime, datetime]],
        today: Callable[[str | None], date],
    ) -> None:
        # Injected so the academy clock (and tests) decide "this month".
        self._reader = reader
        self._month_window = month_window
        self._today = today

    async def execute(
        self, *, academy_id: str, coach_id: str, month: str | None
    ) -> CoachPaySummary:
        zone = await self._reader.academy_timezone(academy_id)
        period = allowed_month(month, today=self._today(zone))
        start, end = self._month_window(period, zone)
        classes = sorted(
            await self._reader.taught_classes(
                academy_id=academy_id, coach_id=coach_id, start=start, end=end
            ),
            key=lambda row: row.start_at,
            reverse=True,
        )
        row = await self._reader.released_payslip(
            academy_id=academy_id, coach_id=coach_id, start=start, end=end
        )
        # Anything but approved or paid reads exactly as "no payslip", so the
        # screen can never hint that a draft exists.
        payslip = (
            CoachPayslip(
                period_start=row.period_start,
                period_end=row.period_end,
                status=row.status,
                total_cents=row.total_minor,
                currency=row.currency.lower(),
                approved_on=row.approved_on,
                paid_on=row.paid_on if row.status == "paid" else None,
                paid_method_label=(
                    _METHOD_LABELS.get(row.paid_method or "", "other")
                    if row.status == "paid"
                    else None
                ),
                paid_amount_cents=row.paid_amount_minor if row.status == "paid" else None,
            )
            if row is not None and row.status in ("approved", "paid")
            else None
        )
        year, mon = (int(part) for part in period.split("-"))
        return CoachPaySummary(
            month=period,
            month_label=date(year, mon, 1).strftime("%B %Y"),
            classes_taught=len(classes),
            minutes_taught=sum(row.minutes for row in classes),
            classes=classes,
            payslip=payslip,
        )
