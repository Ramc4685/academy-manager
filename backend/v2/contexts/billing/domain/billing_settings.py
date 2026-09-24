"""BillingSettings — academy-scoped cash-discount configuration.

Pure domain model. No infra imports. Defaults are fail-safe: discounts are
off unless an academy admin explicitly opts in.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: Upper bound on the platform's per-academy application fee, in basis points
#: (1 bps = 0.01%). 1,000 bps = 10% of the charge: a guard rail against a
#: fat-fingered value, not a pricing decision. Raising it is a code change.
MAX_APPLICATION_FEE_BPS = 1_000


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

    # Automated past-due reminders (issue #774). Each entry is a number of days
    # AFTER an invoice's due date on which the reminder job emails the parent,
    # so ``(15, 20)`` is the owner's "due+15 and due+20". An EMPTY tuple means
    # the academy sends no automatic reminders at all — that is the off switch,
    # which is why there is no separate boolean beside it. Days are stored
    # sorted and de-duplicated so the job can never send two emails for the
    # same calendar day.
    reminder_days: tuple[int, ...] = Field(default=(15, 20))

    # Platform application fee (roadmap L9b), in basis points of each
    # destination charge routed to this academy's connected account; Stripe's
    # ``application_fee_amount`` is derived from it per charge by
    # ``domain.fees.application_fee_cents``. Default 0 keeps every existing
    # academy's charges exactly as before. PLATFORM-ADMIN ONLY: the tenant
    # settings write path (``BillingSettingsRepository.upsert``) never
    # persists this field; only ``set_application_fee_bps`` does, from the
    # platform BFF.
    application_fee_bps: int = Field(default=0, ge=0, le=MAX_APPLICATION_FEE_BPS)

    @field_validator("reminder_days", mode="before")
    @classmethod
    def _clean_reminder_days(cls, value: object) -> tuple[int, ...]:
        if value is None:
            return ()
        if isinstance(value, int):
            value = (value,)
        if not isinstance(value, list | tuple):
            return ()
        return tuple(sorted({int(day) for day in value}))

    @classmethod
    def default(cls, academy_id: str) -> BillingSettings:
        """Fail-safe defaults: all discounts off."""
        return cls(academy_id=academy_id)
