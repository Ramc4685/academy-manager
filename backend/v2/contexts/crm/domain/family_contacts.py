"""Family contacts and family details (People CRM spec §4 "Details", §5, Phase 4b).

* ``FamilyContact``: a second parent, guardian or other adult on a family.
  Contacts are never users and never get a login. Two independent switches,
  both OFF by default and never switched on by the system:

  - ``gets_notices``: the contact's email joins the family's notice audience
    (the audience resolver's per-parent expansion);
  - ``gets_invoices``: the contact gets a copy of each invoice email, once
    per invoice and without the pay link
    (``composition/invoice_contact_copies.py``).

* ``FamilyDetails``: one document per family with the editable, non-money
  details (home address, preferred channel, how they heard about us, tags).

Pure: no I/O, no Mongo types. ``academy_id`` is carried for reads but is
always stamped by the repository from the tenant context on write.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import datetime
from typing import Final, Literal, get_args

from pydantic import BaseModel, ConfigDict

from backend.v2.contexts.crm.domain.errors import InvalidFamilyContact, InvalidFamilyDetails

MAX_CONTACT_NAME_LEN: Final = 120
MAX_EMAIL_LEN: Final = 254
MAX_PHONE_LEN: Final = 40
#: A family is one parent account plus a handful of adults, not a mailing list.
MAX_CONTACTS_PER_FAMILY: Final = 10

MAX_ADDRESS_LEN: Final = 300
MAX_HEARD_ABOUT_US_LEN: Final = 200
MAX_TAGS: Final = 20
MAX_TAG_LEN: Final = 40

ContactRelationship = Literal["parent", "guardian", "grandparent", "caregiver", "other"]
CONTACT_RELATIONSHIPS: frozenset[str] = frozenset(get_args(ContactRelationship))

PreferredChannel = Literal["email", "phone", "sms", "whatsapp"]
PREFERRED_CHANNELS: frozenset[str] = frozenset(get_args(PreferredChannel))

_WS = re.compile(r"\s+")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE_CHARS = re.compile(r"^[0-9+()\-. ]+$")
_NON_DIGIT = re.compile(r"\D")


class FamilyContact(BaseModel):
    model_config = ConfigDict(frozen=True)

    contact_id: str
    academy_id: str
    parent_id: str
    name: str
    relationship: ContactRelationship = "parent"
    #: Lowercased and trimmed; None when the contact has no email.
    email: str | None = None
    phone: str | None = None
    phone_digits: str | None = None
    gets_notices: bool = False
    gets_invoices: bool = False
    created_by: str
    created_at: datetime
    updated_at: datetime


class FamilyDetails(BaseModel):
    model_config = ConfigDict(frozen=True)

    academy_id: str
    parent_id: str
    address: str | None = None
    preferred_channel: PreferredChannel | None = None
    heard_about_us: str | None = None
    tags: tuple[str, ...] = ()
    updated_by: str | None = None
    updated_at: datetime | None = None


def _one_line(value: str) -> str:
    return _WS.sub(" ", _CONTROL.sub(" ", value)).strip()


def normalize_contact_name(value: str) -> str:
    name = _one_line(value or "")
    if not name:
        raise InvalidFamilyContact("Enter the contact's name.", field="name")
    if len(name) > MAX_CONTACT_NAME_LEN:
        raise InvalidFamilyContact(
            f"Keep the name to {MAX_CONTACT_NAME_LEN} characters.", field="name"
        )
    return name


def normalize_relationship(value: str) -> ContactRelationship:
    if value not in CONTACT_RELATIONSHIPS:
        raise InvalidFamilyContact("Choose a relationship from the list.", field="relationship")
    return value  # type: ignore[return-value]


def normalize_contact_email(value: str | None) -> str | None:
    """Trimmed and lowercased, or None for blank. The lowercase form is what
    the per-family unique index compares, so ``Ann@X`` and ``ann@x`` collide."""
    email = (value or "").strip().lower()
    if not email:
        return None
    if len(email) > MAX_EMAIL_LEN or not _EMAIL.match(email):
        raise InvalidFamilyContact("Enter a valid email address.", field="email")
    return email


def normalize_contact_phone(value: str | None) -> tuple[str | None, str | None]:
    """``(phone as typed, digits only)``, or ``(None, None)`` for blank."""
    phone = _one_line(value or "")
    if not phone:
        return None, None
    digits = _NON_DIGIT.sub("", phone)
    if len(phone) > MAX_PHONE_LEN or not _PHONE_CHARS.match(phone) or not 7 <= len(digits) <= 15:
        raise InvalidFamilyContact("Enter a valid phone number.", field="phone")
    return phone, digits


def check_contact_reachable(
    *, email: str | None, phone: str | None, gets_notices: bool, gets_invoices: bool
) -> None:
    """A contact needs a way to reach them, and a switch that sends email
    needs an email address to send to."""
    if email is None and phone is None:
        raise InvalidFamilyContact("Add an email or a phone number.", field="email")
    if email is None and gets_notices:
        raise InvalidFamilyContact(
            "Add an email before turning on Gets notices.", field="gets_notices"
        )
    if email is None and gets_invoices:
        raise InvalidFamilyContact(
            "Add an email before turning on Gets invoices.", field="gets_invoices"
        )


def _optional_text(value: str | None, *, field: str, cap: int, label: str) -> str | None:
    text = _one_line(value or "")
    if not text:
        return None
    if len(text) > cap:
        raise InvalidFamilyDetails(f"Keep the {label} to {cap} characters.", field=field)
    return text


def normalize_address(value: str | None) -> str | None:
    return _optional_text(value, field="address", cap=MAX_ADDRESS_LEN, label="address")


def normalize_heard_about_us(value: str | None) -> str | None:
    return _optional_text(value, field="heard_about_us", cap=MAX_HEARD_ABOUT_US_LEN, label="answer")


def normalize_preferred_channel(value: str | None) -> PreferredChannel | None:
    if value is None or value == "":
        return None
    if value not in PREFERRED_CHANNELS:
        raise InvalidFamilyDetails(
            "Choose a preferred channel from the list.", field="preferred_channel"
        )
    return value  # type: ignore[return-value]


def normalize_tags(values: Iterable[str]) -> tuple[str, ...]:
    """Trimmed, blank-free, de-duplicated ignoring case (first spelling wins)."""
    seen: set[str] = set()
    tags: list[str] = []
    for raw in values:
        tag = _one_line(raw or "")
        if not tag:
            continue
        if len(tag) > MAX_TAG_LEN:
            raise InvalidFamilyDetails(f"Keep each tag to {MAX_TAG_LEN} characters.", field="tags")
        if tag.lower() in seen:
            continue
        seen.add(tag.lower())
        tags.append(tag)
    if len(tags) > MAX_TAGS:
        raise InvalidFamilyDetails(f"Use at most {MAX_TAGS} tags.", field="tags")
    return tuple(tags)
