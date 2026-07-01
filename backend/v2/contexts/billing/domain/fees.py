"""Billing fee and discount calculations."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from backend.v2.contexts.billing.domain.billing_settings import BillingSettings

_ACH_FUNDING_TYPES = frozenset({"ach", "us_bank_account"})


def compute_ach_discount(
    subtotal_cents: int,
    settings: BillingSettings | None,
    funding_type: str | None,
) -> int:
    """Return the ACH cash-discount amount in cents.

    Fail-safe defaults are deliberate: card, debit, unknown funding, disabled
    settings, and non-positive subtotals all receive no discount.
    """
    if subtotal_cents <= 0 or settings is None or not settings.ach_discount_enabled:
        return 0
    if str(funding_type or "").lower() not in _ACH_FUNDING_TYPES:
        return 0

    percent = min(
        Decimal(str(settings.ach_discount_percent)),
        Decimal(str(settings.max_ach_discount_percent)),
    )
    if percent <= 0:
        return 0

    cents = (Decimal(subtotal_cents) * percent / Decimal("100")).quantize(
        Decimal("1"),
        rounding=ROUND_HALF_UP,
    )
    return max(0, int(cents))
