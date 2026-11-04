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


def application_fee_cents(amount_cents: int, fee_bps: int) -> int:
    """Return the platform application fee for one charge, in integer cents.

    ``fee_bps`` is basis points of ``amount_cents`` (100 bps = 1%). Rounding
    is DOWN (floor): a fractional cent always stays with the academy, never
    with the platform. The result is never negative and never exceeds the
    charge itself, so Stripe can never be asked to take more than it collects.
    """
    if amount_cents < 0:
        raise ValueError("amount_cents must not be negative")
    if fee_bps < 0:
        raise ValueError("fee_bps must not be negative")
    if amount_cents == 0 or fee_bps == 0:
        return 0
    fee = (amount_cents * fee_bps) // 10_000
    return min(fee, amount_cents)


def check_application_fee_cents(
    *, fee_cents: int, amount_cents: int, connected_account_id: str | None
) -> int:
    """Validate an ``application_fee_amount`` before it is sent to Stripe.

    The fee must be a non-negative integer no larger than the charge, and a
    non-zero fee is only meaningful on a destination charge (a connected
    account). A platform-direct charge already settles entirely to the
    platform, so a fee there is a caller bug, not something to drop silently.
    """
    if isinstance(fee_cents, bool) or not isinstance(fee_cents, int):
        raise ValueError("application fee must be an integer number of cents")
    if fee_cents < 0:
        raise ValueError("application fee must not be negative")
    if fee_cents > amount_cents:
        raise ValueError("application fee must not exceed the charge amount")
    if fee_cents and not connected_account_id:
        raise ValueError("application fee requires a connected-account destination charge")
    return fee_cents
