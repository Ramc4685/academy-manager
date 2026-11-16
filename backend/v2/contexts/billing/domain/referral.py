"""Referral programme rules (L9 C2). Pure: no I/O.

A parent shares their academy's link with their own ``referral_code``. A new
family arrives with that code in its attribution (a website inquiry that
later registered, or a registration). Once the new family's first invoice is
paid and the owner's hold has passed, the referring family (and, when the
owner set one, the new family) gets an account credit.

* One referral per referred family per academy, ever.
* A self-referral never earns: the same parent, the same email, or the same
  household (a shared phone number).
* A family that already had an invoice before it was referred is not new.
* The referring family earns at most the owner's yearly number of rewards;
  a referral over the cap earns nothing (neither family).
* Granted credits are never clawed back (owner decision).
"""

from __future__ import annotations

import secrets
from collections.abc import Iterable
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

ReferralStatus = Literal["pending", "granted", "ineligible"]
IneligibleReason = Literal[
    "unknown_code",
    "self_referral",
    "existing_family",
    "yearly_cap_reached",
]
ReferralSource = Literal["contact", "application"]
CreditRole = Literal["referrer", "referred"]

#: ``account_credit_ledger.source_type`` of a referral credit. With
#: :func:`credit_source_id` it is the key ``academy_credit_source_unique``
#: holds unique, which makes each grant exactly-once.
REFERRAL_CREDIT_SOURCE_TYPE = "REFERRAL"

#: Codes are minted from this alphabet (no 0/O, 1/I/L) and compared upper-case.
CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
CODE_LENGTH = 8


def new_referral_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def normalize_code(value: str | None) -> str | None:
    """Upper-case and trimmed; ``None`` when blank."""
    text = (value or "").strip().upper()
    return text or None


def credit_source_id(referral_id: str, role: CreditRole) -> str:
    """Deterministic per referral and role, so a retry or a replay can only
    ever hit the same unique key."""
    return f"{referral_id}:{role}"


def reward_key(referrer_parent_id: str, year: int, slot: int) -> str:
    """One of the referrer's ``max_rewards`` yearly slots. Unique per academy:
    two referrals can never hold the same slot, so the cap holds atomically."""
    return f"{referrer_parent_id}:{year}:{slot}"


def normalize_phone(value: str | None) -> str | None:
    digits = "".join(ch for ch in (value or "") if ch.isdigit())
    return digits[-10:] if len(digits) >= 7 else None


def is_self_referral(
    *,
    referrer_ids: Iterable[str],
    referrer_emails: Iterable[str | None],
    referrer_phones: Iterable[str | None],
    referred_parent_id: str,
    referred_emails: Iterable[str | None],
    referred_phones: Iterable[str | None],
) -> bool:
    """Same parent (any id the parent answers to), same email, or same
    household phone."""
    if referred_parent_id in set(referrer_ids):
        return True
    mine = {e.strip().lower() for e in referrer_emails if e and e.strip()}
    if mine & {e.strip().lower() for e in referred_emails if e and e.strip()}:
        return True
    phones = {p for p in map(normalize_phone, referrer_phones) if p}
    return bool(phones & {p for p in map(normalize_phone, referred_phones) if p})


class Referral(BaseModel):
    """One row of ``referrals``. The credit, hold and expiry are frozen when
    the referral is recorded, so a later settings change applies going
    forward only."""

    model_config = ConfigDict(frozen=True)

    referral_id: str
    academy_id: str
    referral_code: str
    referrer_parent_id: str | None = None
    referred_parent_id: str
    source: ReferralSource
    source_id: str
    attributed_at: datetime
    status: ReferralStatus
    reason: IneligibleReason | None = None
    referrer_credit_cents: int | None = None
    referred_credit_cents: int | None = None
    hold_days: int | None = None
    credit_expiry_days: int | None = None
    #: The first paid invoice that qualified the referral, when it was paid,
    #: and when the hold ends.
    qualified_invoice_id: str | None = None
    qualified_at: datetime | None = None
    grant_due_at: datetime | None = None
    #: The referrer's yearly slot, claimed before any credit is written.
    reward_key: str | None = None
    referrer_credit_id: str | None = None
    referred_credit_id: str | None = None
    granted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
