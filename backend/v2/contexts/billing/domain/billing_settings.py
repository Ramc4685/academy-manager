"""BillingSettings — academy-scoped cash-discount configuration.

Pure domain model. No infra imports. Defaults are fail-safe: discounts are
off unless an academy admin explicitly opts in.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class BillingSettings(BaseModel):
    """Academy-scoped billing configuration (cash/ACH discount + invoice numbering)."""

    model_config = ConfigDict(frozen=True)

    academy_id: str
    ach_discount_enabled: bool = False
    ach_discount_percent: float = 0
    ach_discount_label: str = "ACH autopay discount"
    max_ach_discount_percent: float = 3.0
    disclosure_text: str | None = None
    disclosure_version: str | None = None
    effective_at: datetime | None = None
    invoice_number_prefix: str = "BLNO"

    # TEMPORARY escape hatch while the platform's Stripe Connect application is
    # under review: when true, checkout/invoice/autopay may charge the
    # platform account directly instead of refusing when the academy's
    # connected account isn't charge-ready. Only safe while academy funds and
    # platform funds settle to the same Stripe account — remove once Connect
    # onboarding is fully rolled out.
    allow_platform_charge_fallback: bool = False

    # Automated monthly invoicing (issue #288). ``billing_day`` is the
    # day-of-month the generation job runs for this academy; it is capped at 28
    # so every month has the day and no academy silently skips February.
    # ``invoice_due_days`` is the grace window added to the generation date to
    # get the invoice due_date, which is also when the existing dunning ladder
    # makes its first autopay charge attempt (DUNNING_SCHEDULE_DAYS starts at 0).
    billing_day: int = Field(default=1, ge=1, le=28)
    invoice_due_days: int = Field(default=7, ge=0, le=60)

    @classmethod
    def default(cls, academy_id: str) -> BillingSettings:
        """Fail-safe defaults: all discounts off."""
        return cls(academy_id=academy_id)
