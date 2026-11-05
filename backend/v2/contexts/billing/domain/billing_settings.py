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

#: The processing markup every NEW academy starts on (AI strategy plan §5,
#: Phase 2 slice A1): 100 bps = 1% of each Stripe Connect charge. Existing
#: academies keep whatever is stored (0 when nothing is); the platform admin
#: sets theirs by hand.
NEW_ACADEMY_APPLICATION_FEE_BPS = 100

#: The processing-fee agreement an academy accepts, versioned in code so the
#: accepted version on the settings document always names an exact text.
#: Never "forever": the offer stays two-way.
APPLICATION_FEE_AGREEMENT_VERSION = "2026-11-04"
APPLICATION_FEE_AGREEMENT_TEXT = (
    "Core operations (rosters, attendance, billing, the parent app, the pipeline board "
    "and templated messages) are free. CourtMastr takes a processing markup on card and "
    "ACH payments collected through Stripe Connect. 12 months notice on any pricing "
    "change, applied to new signups first."
)


class ApplicationFeeAgreementAcceptance(BaseModel):
    """Who accepted which version of the processing-fee agreement, and when.

    Recorded WITH the fee on the billing settings document (platform-only
    fields), separate from the tenant-level platform agreement (roadmap L9c).
    """

    model_config = ConfigDict(frozen=True)

    version: str = Field(min_length=1)
    accepted_by: str = Field(min_length=1)
    accepted_at: datetime


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

    # Human-facing invoice-number prefix (``BLNO`` -> ``BLNO-2026-09-0042``).
    # No default on purpose: it used to default to "BLNO", so every new
    # academy would have issued BLNO-numbered invoices. It is set per academy
    # by the PLATFORM (derived from the slug at creation, editable by a
    # platform admin until the first numbered invoice; see
    # ``domain.invoice_prefix``). The tenant settings write
    # (``BillingSettingsRepository.upsert``) never persists it. ``None`` means
    # "not configured": ``mint_invoice_number`` then mints nothing.
    invoice_number_prefix: str | None = None

    # Whether this academy's parent charges may settle on the PLATFORM Stripe
    # account instead of refusing when it has no charge-ready connected
    # account. Derived on read by the billing-settings repository: true only
    # for the house academy (BLNO, which owns the platform account), false for
    # every other academy. Never written by the app. See
    # ``infrastructure/house_academy.py``.
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
    # Acceptance of the processing-fee agreement, recorded with the fee by the
    # platform admin (``set_application_fee_bps``). PLATFORM-ADMIN ONLY, like
    # the fee itself. All three are None until an acceptance is recorded.
    application_fee_agreement_version: str | None = None
    application_fee_accepted_at: datetime | None = None
    application_fee_accepted_by: str | None = None

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
