"""Possible-duplicate matching for the People CRM warning (spec §4 "Real forms", Phase 4c).

When staff add a family, an inquiry or a user, the form asks whether the
email or phone (or the exact name) already belongs to someone in THIS
academy, and shows "Possible match: <name> - open". It is a warning only:
nothing is merged and nothing is refused.

Pure: normalisation, the phone spellings to look up, the in-memory matcher
for family index rows, and the masking of what is sent back. No I/O.

Normalisation:

* email: trimmed, whitespace-collapsed, lower-cased (``normalize_email``, the
  same rule ``crm_contacts`` and ``family_contacts`` store with). Needs an
  ``@``; anything else is ignored rather than looked up.
* phone: digits only. Stored rows keep the digits as typed, so
  ``+1 (555) 010-2030`` is stored ``15550102030`` and ``555-010-2030`` is
  ``5550102030``. For a North American number (10 digits, or 11 starting
  with the country code 1, the academy's country today) both spellings are
  looked up, one equality lookup each. Fewer than 7 digits is not a phone.
* name: ``full_name_key`` equality (accents and case folded). Exact, never
  a prefix, so "Sam" does not match "Samantha".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

from backend.v2.contexts.crm.domain.family_index import FamilyRecord, phone_digits
from backend.v2.contexts.crm.domain.models import normalize_email
from backend.v2.shared.names import full_name_key

#: The endpoint returns at most this many matches (the notice names the first).
MAX_DUPLICATE_MATCHES: Final = 5
MIN_PHONE_DIGITS: Final = 7
MAX_PHONE_DIGITS: Final = 15
#: The North American country code: the only country the academy runs in
#: today, so the only one whose E.164 prefix is folded.
_NANP_COUNTRY_CODE: Final = "1"
_NANP_NATIONAL_DIGITS: Final = 10

DuplicateKind = Literal["family", "family_contact", "user", "inquiry"]
MatchedOn = Literal["email", "phone", "name"]


@dataclass(frozen=True)
class DuplicateProbe:
    """The normalised question. Every field None means "nothing to check"."""

    email: str | None = None
    phone_variants: tuple[str, ...] = ()
    name_key: str | None = None

    @property
    def is_empty(self) -> bool:
        return self.email is None and not self.phone_variants and self.name_key is None


@dataclass(frozen=True)
class DuplicateMatch:
    kind: DuplicateKind
    #: Stable id of the matched record (family id, contact id, user id).
    record_id: str
    display_name: str
    email_masked: str | None
    phone_masked: str | None
    #: The admin page that opens the record, or None when there is none yet
    #: (an inquiry that is not linked to a family).
    link: str | None
    matched_on: tuple[MatchedOn, ...]


def probe_email(value: str | None) -> str | None:
    email = normalize_email(value)
    if email is None or email.count("@") != 1 or " " in email:
        return None
    local, _, domain = email.partition("@")
    return email if local and domain else None


def probe_phone_variants(value: str | None) -> tuple[str, ...]:
    """Every stored spelling of this phone number, most likely first."""
    digits = phone_digits(value)
    if not MIN_PHONE_DIGITS <= len(digits) <= MAX_PHONE_DIGITS:
        return ()
    if len(digits) == _NANP_NATIONAL_DIGITS:
        return (digits, _NANP_COUNTRY_CODE + digits)
    if len(digits) == _NANP_NATIONAL_DIGITS + 1 and digits.startswith(_NANP_COUNTRY_CODE):
        return (digits[1:], digits)
    return (digits,)


def probe_name(value: str | None) -> str | None:
    key = full_name_key(value or "")
    return key or None


def build_probe(
    *, email: str | None = None, phone: str | None = None, name: str | None = None
) -> DuplicateProbe:
    return DuplicateProbe(
        email=probe_email(email),
        phone_variants=probe_phone_variants(phone),
        name_key=probe_name(name),
    )


def phone_matches(stored: str | None, probe: DuplicateProbe) -> bool:
    """True when a stored phone, in any punctuation, is one of the probe's spellings."""
    if not probe.phone_variants:
        return False
    return bool(set(probe_phone_variants(stored)) & set(probe.phone_variants))


def family_record_matches(record: FamilyRecord, probe: DuplicateProbe) -> tuple[MatchedOn, ...]:
    """Why a family index row matches the probe (empty when it does not)."""
    matched: list[MatchedOn] = []
    if probe.email is not None and (
        (record.email or "").strip().lower() == probe.email
        # A roster family (no users document) is known by the students'
        # ``parent_email``, kept lower-cased among the legacy keys.
        or probe.email in record.legacy_contact_keys
    ):
        matched.append("email")
    if phone_matches(record.phone, probe) or any(
        phone_matches(stored, probe) for stored in record.legacy_phones
    ):
        matched.append("phone")
    if probe.name_key is not None and record.parent_name:
        if full_name_key(record.parent_name) == probe.name_key:
            matched.append("name")
    return tuple(matched)


def mask_email(value: str | None) -> str | None:
    """``jo***@example.test``: enough to recognise, not enough to harvest."""
    email = (value or "").strip().lower()
    local, sep, domain = email.partition("@")
    if not sep or not local or not domain:
        return None
    keep = local[:2] if len(local) > 3 else local[:1]
    return f"{keep}***@{domain}"


def mask_phone(value: str | None) -> str | None:
    """``•••-2030``: the last four digits only."""
    digits = phone_digits(value)
    if len(digits) < 4:
        return None
    return f"•••-{digits[-4:]}"
