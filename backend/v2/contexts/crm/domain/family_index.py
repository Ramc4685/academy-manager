"""The family index: one row per family record (People CRM spec §1, §3.2).

A family record is keyed by the parent's canonical id (there is no family
entity in the database). Each row carries its children with their lifecycle
chips and classes, the rolled-up stage, the parent's contact fields, and the
family's money when it could be read. Pure data plus the search matcher; no
I/O. Built once per request by ``infrastructure/family_index_read_model.py``
and queried by ``application/family_index.py``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime

from backend.v2.contexts.crm.domain.family_stage import FamilyStage
from backend.v2.shared.names import full_name_key

#: Fewest query digits that are treated as a phone number (spec §3.2:
#: "Phone (digits only, last 7 to 10 digits)").
PHONE_MIN_DIGITS = 7
PHONE_MATCH_DIGITS = 10

_NON_DIGIT = re.compile(r"\D+")
_PHONEISH = re.compile(r"^[\d\s()+.\-]+$")


def phone_digits(value: str | None) -> str:
    return _NON_DIGIT.sub("", value or "")


@dataclass(frozen=True)
class FamilyChild:
    student_id: str
    name: str
    #: The child's ``derive_lifecycle`` state and its date (resume, return,
    #: end or left-on date), exactly as ``/admin/students`` shows it.
    lifecycle: str
    lifecycle_as_of: date | None = None
    #: Sessions the child holds a seat in, and their titles (same order).
    session_ids: tuple[str, ...] = ()
    session_titles: tuple[str, ...] = ()


@dataclass(frozen=True)
class FamilyMoney:
    """The family's money, as the Billing tab header computes it."""

    balance_cents: int
    open_invoice_count: int
    overdue_invoice_count: int
    overdue_cents: int
    oldest_overdue_due_on: date | None
    last_failed_payment_at: datetime | None


@dataclass(frozen=True)
class FamilyRecord:
    #: The parent's canonical id: the id ``/admin/families/{id}`` opens.
    family_id: str
    parent_name: str | None
    email: str | None
    phone: str | None
    #: False when no users document answers to the stored parent reference
    #: (a roster-only parent); the name then comes from the student row.
    has_account: bool
    children: tuple[FamilyChild, ...]
    stage: FamilyStage
    #: Registration and card state are not amounts; they are shown to every
    #: admin. None when the billing source could not be read.
    card_on_file: bool | None = None
    registration: str | None = None
    #: None when the money source failed (the index then carries a warning).
    money: FamilyMoney | None = None
    #: Legacy parent fields on the student rows (``parent_name``,
    #: ``guardian_name``, ``parent_email``): searched, never displayed.
    legacy_contact_keys: tuple[str, ...] = ()
    #: Digits of the legacy ``parent_phone`` on the student rows (a roster
    #: family, such as one a CSV import created, has no users document to
    #: carry a phone). Matched by the duplicate check, never displayed.
    legacy_phones: tuple[str, ...] = ()

    @property
    def sort_key(self) -> tuple[str, str]:
        return (full_name_key(self.parent_name or self.email or ""), self.family_id)


@dataclass(frozen=True)
class FamilyIndex:
    academy_id: str
    generated_at: datetime
    families: tuple[FamilyRecord, ...]
    #: Secondary sources that failed: ``money_unavailable``,
    #: ``classes_unavailable``. The UI shows a warning, never a zero.
    warnings: tuple[str, ...] = ()
    #: Every stored parent reference and every alias of its resolved users
    #: document (``user_id``, ``firebase_uid``, ``auth_uid``, users ``_id``)
    #: -> the canonical family id. Built from this academy's own rows only,
    #: so an alias of another academy's parent is never here.
    family_by_alias: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SearchHit:
    """Why a family matched. A child match makes that child the result row
    (spec §3.2), so the matched children are named."""

    matched_student_ids: tuple[str, ...] = ()
    matched_parent: bool = False


@dataclass(frozen=True)
class _Needle:
    tokens: tuple[str, ...]
    key: str
    raw_lower: str
    digits: str = field(default="")


def _needle(query: str) -> _Needle | None:
    key = full_name_key(query)
    if not key:
        return None
    digits = phone_digits(query) if _PHONEISH.match(query.strip()) else ""
    return _Needle(
        tokens=tuple(key.split(" ")), key=key, raw_lower=query.strip().lower(), digits=digits
    )


def _name_matches(name: str | None, needle: _Needle) -> bool:
    """Every query word is a prefix of some word of the name (first-name
    prefix match, spec §3.2), compared on ``full_name_key``."""
    if not name:
        return False
    words = full_name_key(name).split(" ")
    return all(any(word.startswith(token) for word in words) for token in needle.tokens)


def search_family(record: FamilyRecord, query: str) -> SearchHit | None:
    """Match one family against a search box query, or None."""
    needle = _needle(query)
    if needle is None:
        return SearchHit()
    if len(needle.digits) >= PHONE_MIN_DIGITS:
        wanted = needle.digits[-PHONE_MATCH_DIGITS:]
        if phone_digits(record.phone).endswith(wanted):
            return SearchHit(matched_parent=True)
        return None
    children = tuple(
        child.student_id for child in record.children if _name_matches(child.name, needle)
    )
    parent = (
        _name_matches(record.parent_name, needle)
        or (record.email is not None and needle.raw_lower in record.email.lower())
        or any(
            _name_matches(key, needle) or needle.raw_lower in key
            for key in record.legacy_contact_keys
        )
    )
    if not children and not parent:
        return None
    return SearchHit(matched_student_ids=children, matched_parent=parent)
