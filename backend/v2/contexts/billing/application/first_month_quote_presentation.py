"""Presentation helpers for the first-month proration quote.

The parent and admin BFFs both render the same quote (amount, formula, and the
copy that explains what the charge buys). Those routes must not reach into the
billing domain directly (ADR-0005 layering), so the domain's four-class rule is
re-exposed here, in the application layer, for the interfaces to consume.
"""

from __future__ import annotations

from backend.v2.contexts.billing.domain.proration import (
    BILLABLE_CLASSES_PER_MONTH,
    BillingCalculationSnapshot,
    first_month_charge_description,
    snapshot_charge_denominator,
    snapshot_classes_charged,
)

__all__ = [
    "BILLABLE_CLASSES_PER_MONTH",
    "billable_classes_charged",
    "billable_classes_denominator",
    "first_month_charge_description",
    "first_month_quote_formula",
]


def billable_classes_denominator(snapshot: BillingCalculationSnapshot) -> int:
    """The classes one month of this session's tuition buys (4 per weekly meeting)."""
    return snapshot_charge_denominator(snapshot)


def billable_classes_charged(snapshot: BillingCalculationSnapshot) -> int:
    """How many of the paid classes this first-month quote charges for."""
    return snapshot_classes_charged(snapshot)


def first_month_quote_formula(snapshot: BillingCalculationSnapshot) -> str:
    """Human-readable arithmetic behind ``final_amount_cents``."""
    if not snapshot.total_eligible_classes:
        return "$0.00"
    monthly = snapshot.monthly_price_cents
    billable = billable_classes_charged(snapshot)
    return f"${monthly / 100:.2f} x {billable} / {billable_classes_denominator(snapshot)}"
