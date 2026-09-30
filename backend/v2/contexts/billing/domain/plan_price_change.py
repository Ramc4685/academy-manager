"""Scheduled plan price changes (Settings overhaul Phase 6 PR 26).

The owner changes a plan's price "from a month": the classes linked to the
plan (a snapshot of their ids, taken when the change is applied) are charged
the new price for every billing month on or after ``effective_period`` and
the old price for every month before it. Nothing already invoiced changes.

How a change reaches charges
----------------------------
Every charge path that reads a class's monthly fee (monthly invoice, "Bill
this month", checkout quote, first-month proration, move proration,
cancellation credits) reads it for a billing month through
:func:`class_fee_for_period`. With no change on record (BLNO today) it returns
the stored class fee unchanged.

A change goes through two states that matter to charges:

* ``scheduled``: nothing is written anywhere else. For a class in the
  snapshot whose stored fee is still the old price, a month on or after the
  effective month reads the new price.
* flipped: once the effective month starts, the scheduler writes the new fee
  onto each class (only where the fee is still the old price) and the new
  price onto the plan, so links stay current and the class editor shows the
  fee that is charged. Each class is recorded in ``flipped_session_ids``
  BEFORE its fee is written; for such a class a month BEFORE the effective
  month reads the old price again (a late "Bill this month" or a credit for
  the previous month).

So the answer for a given (class, month) is the same before, during and after
the flip: the flip only moves what is displayed. If the owner edits a class
fee by hand, that fee wins: the change stops applying to the class (its
stored fee is no longer the old price).

Pure: no I/O, no academy id.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from backend.v2.contexts.billing.domain.errors import PriceChangeMonthNotAllowed

PriceChangeStatus = Literal["scheduled", "applied", "cancelled"]

_PERIOD = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")


def stored_class_fee_cents(doc: Mapping[str, object]) -> int:
    """The class's stored monthly fee, read the way the monthly run reads it.

    ``amount_cents`` first; legacy/imported docs carry only
    ``monthly_price_cents`` or ``monthly_price`` (#609, #671). No fee is 0.
    """
    amount: Any = doc.get("amount_cents")
    if amount is not None:
        return int(amount)
    monthly: Any = doc.get("monthly_price_cents")
    if monthly is not None:
        return int(monthly)
    if doc.get("monthly_price") is not None:
        return round(float(doc["monthly_price"]) * 100)  # type: ignore[arg-type]
    return 0


@dataclass(frozen=True)
class PlanPriceChange:
    """One owner decision: plan ``plan_id`` goes from ``old_cents`` to ``new_cents``."""

    change_id: str
    plan_id: str
    old_cents: int
    new_cents: int
    #: ``YYYY-MM``: the first billing month charged the new price.
    effective_period: str
    #: The classes linked to the plan when the change was applied.
    session_ids: tuple[str, ...]
    status: PriceChangeStatus = "scheduled"
    #: Classes whose stored fee the scheduler moved to ``new_cents``.
    flipped_session_ids: tuple[str, ...] = ()
    created_by: str = ""
    created_at: datetime | None = None


def is_period(value: str) -> bool:
    return bool(_PERIOD.match(value or ""))


def next_period(period: str) -> str:
    year, month = (int(part) for part in period.split("-"))
    return f"{year + 1}-01" if month == 12 else f"{year}-{month + 1:02d}"


def earliest_effective_period(*, current_period: str, latest_invoiced_period: str | None) -> str:
    """The first month a new price may start.

    Always a future month (never the current one), and never a month that
    already has a monthly invoice for a linked class: when next month's
    invoices exist, the earliest is the month after them.
    """
    earliest = next_period(current_period)
    if latest_invoiced_period and latest_invoiced_period >= earliest:
        earliest = next_period(latest_invoiced_period)
    return earliest


def ensure_effective_period_allowed(effective_period: str, *, earliest: str) -> None:
    if not is_period(effective_period):
        raise PriceChangeMonthNotAllowed(
            "Pick a month as YYYY-MM.", effective_period=effective_period, earliest=earliest
        )
    if effective_period < earliest:
        raise PriceChangeMonthNotAllowed(
            "That month has started or already has invoices. Pick a later month.",
            effective_period=effective_period,
            earliest=earliest,
        )


def class_fee_for_period(
    *,
    session_id: str,
    stored_fee_cents: int,
    period: str,
    changes: Iterable[PlanPriceChange],
) -> int:
    """What a class is charged per month for billing month ``period``.

    ``stored_fee_cents`` is the class's own stored fee. With no change on
    record the answer is exactly that fee (today's behaviour).
    """
    fee = stored_fee_cents
    relevant = [c for c in changes if c.status != "cancelled"]
    # Undo flips for months before their effective month, newest first, so
    # two changes in a row (100 -> 110 from Nov, 110 -> 120 from Jan) read
    # 100 for October.
    for change in sorted(relevant, key=lambda c: c.effective_period, reverse=True):
        if (
            session_id in change.flipped_session_ids
            and period < change.effective_period
            and fee == change.new_cents
        ):
            fee = change.old_cents
    # Scheduled changes, oldest first. A class recorded as flipped whose fee
    # has not moved yet (mid-flip) still reads the new price here; one whose
    # fee moved already reads it as its stored fee (``fee == old`` fails).
    for change in sorted(relevant, key=lambda c: c.effective_period):
        if (
            change.status == "scheduled"
            and session_id in change.session_ids
            and period >= change.effective_period
            and fee == change.old_cents
        ):
            fee = change.new_cents
    return fee


def pending_change_for_class(
    *, session_id: str, stored_fee_cents: int, changes: Iterable[PlanPriceChange]
) -> PlanPriceChange | None:
    """The scheduled change that will move this class's fee ("Scheduled: $X from <Month>").

    ``None`` when no scheduled change still applies (none on record, already
    flipped, or the owner edited the class fee since).
    """
    for change in sorted(changes, key=lambda c: c.effective_period):
        if (
            change.status == "scheduled"
            and session_id in change.session_ids
            and session_id not in change.flipped_session_ids
            and stored_fee_cents == change.old_cents
        ):
            return change
    return None
