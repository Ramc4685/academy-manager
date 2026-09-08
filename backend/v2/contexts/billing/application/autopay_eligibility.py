"""Autopay eligibility — the ONE definition of "the worker would charge this invoice".

Both the dunning worker (``MongoDunningStateRepository.prepare_due_states`` /
``claim_next_due``, ``ChargeInvoiceViaAutopay``) and the admin collections read
model call these predicates. Never re-implement them; the Payments page must
not promise a charge the worker will skip (spec 2026-09-05 §2.1).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

CHARGEABLE_INVOICE_STATUSES: frozenset[str] = frozenset({"open", "partially_paid"})

# Only an actively-autopaying enrollment may be auto-charged. paused / disabled
# / not_offered / offered / setup_started are all ineligible (Security P2).
AUTOPAY_ACTIVE_STATUS = "active"

EligibilityStatus = Literal["eligible", "ineligible", "unknown"]


@dataclass(frozen=True)
class Eligibility:
    status: EligibilityStatus
    reason: str | None = None

    @property
    def eligible(self) -> bool:
        return self.status == "eligible"


ELIGIBLE = Eligibility("eligible")


def invoice_is_chargeable(status: str | None, balance_due_cents: int) -> bool:
    return status in CHARGEABLE_INVOICE_STATUSES and balance_due_cents > 0


def ladder_eligibility(
    *,
    invoice_status: str | None,
    balance_due_cents: int,
    enrollment_id: str | None,
    autopay_enrollment_status: str | None,
) -> Eligibility:
    """The conditions ``prepare_due_states`` applies before opening a ladder."""
    if invoice_status not in CHARGEABLE_INVOICE_STATUSES:
        return Eligibility("ineligible", "invoice_not_chargeable")
    if balance_due_cents <= 0:
        return Eligibility("ineligible", "no_balance")
    if not enrollment_id:
        return Eligibility("ineligible", "no_enrollment")
    if autopay_enrollment_status != AUTOPAY_ACTIVE_STATUS:
        return Eligibility("ineligible", "autopay_not_active")
    return ELIGIBLE


def autopay_eligibility(
    *,
    invoice_status: str | None,
    balance_due_cents: int,
    enrollment_id: str | None,
    autopay_enrollment_status: str | None,
    has_payment_method: bool | None,
    connected_account_ready: bool | None,
) -> Eligibility:
    """Ladder conditions plus the charge-time guards of ``ChargeInvoiceViaAutopay``.

    ``None`` for the card or connected-account state means "could not be
    determined" and yields ``unknown`` — never ``eligible`` (spec §6).
    """
    ladder = ladder_eligibility(
        invoice_status=invoice_status,
        balance_due_cents=balance_due_cents,
        enrollment_id=enrollment_id,
        autopay_enrollment_status=autopay_enrollment_status,
    )
    if not ladder.eligible:
        return ladder
    if has_payment_method is None:
        return Eligibility("unknown", "card_state_unknown")
    if not has_payment_method:
        return Eligibility("ineligible", "no_card_on_file")
    if connected_account_ready is None:
        return Eligibility("unknown", "connected_account_unknown")
    if not connected_account_ready:
        return Eligibility("ineligible", "connected_account_not_ready")
    return ELIGIBLE
