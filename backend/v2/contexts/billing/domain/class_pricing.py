"""Class-to-plan link rules (Settings overhaul Phase 3 PR 11b, Pricing page).

A *plan* is a session type (the academy price list). A *class* is a session,
and what a family is charged for it is the class's own monthly fee, read by
every charge path (checkout quote, monthly invoice, "Bill this month",
cancellation credits) exactly as before this module existed.

A link records which plan a class is priced from. It is a label, never an
amount: nothing here writes a fee and no charge path reads a link. The one
invariant is that a link can never disagree with what is charged:

* a class may be linked to a plan only when the plan's price equals the
  class fee (``ensure_link_allowed``);
* the initial automatic link is made only when exactly ONE active plan has
  the class's price (``initial_plan_link``); zero or several matches leave
  the class "custom";
* on read, a stored link whose plan no longer has the class's price (the fee
  or the plan price changed since) is shown as custom
  (``effective_plan_link``), so the Pricing page never shows a plan price
  that is not what the family pays.

Pure: no I/O, no academy id.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from backend.v2.contexts.billing.domain.errors import PlanPriceMismatch

#: How a plan charges. ``monthly`` is today's rule for every class: the fee
#: buys 4 classes per weekly slot and a 5th date in the month is free.
#: ``per_session`` (pay per class date) is a later phase and is not accepted
#: by any write yet. Billing code does not read this value.
PlanType = Literal["monthly", "per_session"]

#: What every existing plan is, filled at read time (no migration).
DEFAULT_PLAN_TYPE: PlanType = "monthly"


@dataclass(frozen=True)
class PlanPrice:
    """The part of a plan the link rules need."""

    plan_id: str
    price_cents: int
    is_active: bool = True


def matching_plan_ids(fee_cents: int, plans: Iterable[PlanPrice]) -> list[str]:
    """Active plans whose price is exactly the class fee, in input order."""
    return [plan.plan_id for plan in plans if plan.is_active and plan.price_cents == fee_cents]


def initial_plan_link(fee_cents: int, plans: Iterable[PlanPrice]) -> str | None:
    """The plan to link a never-decided class to, or ``None`` to leave it custom.

    Only an unambiguous match links: exactly one active plan at the class fee.
    """
    matches = matching_plan_ids(fee_cents, plans)
    return matches[0] if len(matches) == 1 else None


def effective_plan_link(
    stored_plan_id: str | None, fee_cents: int, plans: Iterable[PlanPrice]
) -> str | None:
    """The link to show: the stored one only while it still agrees with the fee."""
    if stored_plan_id is None:
        return None
    for plan in plans:
        if plan.plan_id == stored_plan_id:
            return stored_plan_id if plan.is_active and plan.price_cents == fee_cents else None
    return None


def ensure_link_allowed(fee_cents: int, plan: PlanPrice) -> None:
    """Refuse a link that would disagree with what the class is charged."""
    if not plan.is_active:
        raise PlanPriceMismatch("That plan is archived.", plan_id=plan.plan_id)
    if plan.price_cents != fee_cents:
        raise PlanPriceMismatch(
            "A class can only use a plan with the same price as its monthly fee.",
            plan_id=plan.plan_id,
            plan_price_cents=plan.price_cents,
            class_fee_cents=fee_cents,
        )
