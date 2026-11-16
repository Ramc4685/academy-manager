"""The ``crm_contacts`` lead record (People CRM spec §5; public tenant page brief, piece F).

A contact is a person the academy may hear from before any account exists: a
website trial request, a phone or WhatsApp inquiry, a referral. It is ONE
store shared by the public tenant page (first writer, source ``website``) and
the People CRM (adds ``referrer_parent_id``, ``pipeline_override`` and the
links to a family / user when the lead converts). See ``../README.md`` for the
consumer contract.

Pure: no I/O, no Mongo types. ``academy_id`` is carried for reads but is
always stamped by the repository from the tenant context on write.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Literal, get_args

from pydantic import BaseModel

#: Where the lead came from. ``website`` is written only by the anonymous
#: public trial-request endpoint; the other three are staff quick-add sources
#: (People CRM spec §3.4 "Sources").
ContactSource = Literal["website", "whatsapp_or_phone", "referral", "other"]
CONTACT_SOURCES: frozenset[str] = frozenset(get_args(ContactSource))

#: Lifecycle stage of the lead (People CRM spec §6 "Pipeline status"). This is
#: the stage field: ``lead`` (inquiry, no trial yet), ``trial`` (a trial was
#: asked for or booked), ``enrolled`` (converted; set by the conversion flow,
#: never by ``CreateContact``).
PipelineStatus = Literal["lead", "trial", "enrolled"]
PIPELINE_STATUSES: frozenset[str] = frozenset(get_args(PipelineStatus))

#: Stages a new contact may be created in. ``enrolled`` is reached only by
#: converting an existing contact.
CREATABLE_PIPELINE_STATUSES: frozenset[str] = frozenset({"lead", "trial"})

# Size caps (server-side validation for an anonymous public write).
MAX_NAME_LEN = 120
MAX_EMAIL_LEN = 254
MAX_CHILD_AGE_LEN = 20
MAX_ID_LEN = 64
MAX_URL_LEN = 500
#: Free-text note the person left with the inquiry (the public form's
#: optional message). Plain text; never rendered as HTML.
MAX_MESSAGE_LEN = 1000
MIN_PHONE_DIGITS = 7
MAX_PHONE_DIGITS = 15

_WS = re.compile(r"\s+")
_NON_DIGIT = re.compile(r"\D")


class ContactConsent(BaseModel):
    """What the person agreed to when the contact was captured.

    ``contact_about_request``: may the academy contact them about this inquiry
    (the reason the form exists; the public form states it and links the
    privacy page). ``marketing``: opted in to general news or offers; defaults
    to False, and nothing may send marketing to a contact without it.
    ``captured_at``: when the flags were recorded (stamped by ``CreateContact``
    when not given). ``privacy_notice_url``: the notice shown at capture.
    """

    model_config = {"frozen": True}

    contact_about_request: bool = False
    marketing: bool = False
    captured_at: datetime | None = None
    privacy_notice_url: str | None = None


class PipelineOverride(BaseModel):
    """A staff move on the Pipeline board with no underlying system write
    (People CRM spec §3.4). CRM-only; never written by ``CreateContact``."""

    model_config = {"frozen": True}

    column: str
    set_by: str
    set_at: datetime


#: Attribution values (UTM tags from the landing URL, the "how did you hear
#: about us" choice, a referral code): at most this long, from this charset.
#: Anything else is dropped, never stored, never an error for the family.
MAX_ATTRIBUTION_LEN = 80
_ATTRIBUTION_VALUE = re.compile(rf"^[A-Za-z0-9_.-]{{1,{MAX_ATTRIBUTION_LEN}}}$")
ATTRIBUTION_FIELDS = ("heard_from", "utm_source", "utm_medium", "utm_campaign", "referral_code")


class RepeatMessage(BaseModel):
    """A note sent with a repeat website inquiry (A6-4). UNVERIFIED: anyone who
    types this family's details into the public form lands here, so it never
    replaces ``message`` and is shown to staff only with that warning."""

    model_config = {"frozen": True}

    at: datetime
    text: str


#: Newest repeat notes kept on a contact; older ones drop off.
MAX_REPEAT_MESSAGES = 5


class ContactAttribution(BaseModel):
    """Where a website lead came from (L9 A6-10). First touch: a repeat
    inquiry keeps the attribution already on file. No cookies, no referrer."""

    model_config = {"frozen": True}

    heard_from: str | None = None
    utm_source: str | None = None
    utm_medium: str | None = None
    utm_campaign: str | None = None
    referral_code: str | None = None


def clean_attribution(raw: Mapping[str, object] | None) -> ContactAttribution | None:
    """Keep only well-formed values; None when nothing usable was sent."""
    if not raw:
        return None
    kept: dict[str, str] = {}
    for field in ATTRIBUTION_FIELDS:
        value = raw.get(field)
        if isinstance(value, str) and _ATTRIBUTION_VALUE.match(value.strip()):
            kept[field] = value.strip()
    return ContactAttribution(**kept) if kept else None


class CrmContact(BaseModel):
    contact_id: str
    academy_id: str
    name: str
    email: str | None = None
    phone_digits: str | None = None
    source: ContactSource
    # The public form deliberately does NOT collect the child's name
    # (brief §5); staff quick-add may.
    child_name: str | None = None
    child_age: str | None = None
    requested_session_id: str | None = None
    #: Optional free-text note from the person (<= MAX_MESSAGE_LEN). Not part
    #: of the dedupe key: a repeat with a reworded note is still a repeat.
    message: str | None = None
    pipeline_status: PipelineStatus = "lead"
    pipeline_override: PipelineOverride | None = None
    referrer_parent_id: str | None = None
    converted_parent_id: str | None = None
    linked_family_id: str | None = None
    linked_user_id: str | None = None
    consent: ContactConsent = ContactConsent()
    created_by: str | None = None
    #: Idempotency key, set ONLY for ``website`` rows (the anonymous
    #: double-submit case). Staff quick-add sources leave it None: the key
    #: ignores the person's own name, so two different people sharing a
    #: household phone or email would otherwise collapse into one row.
    dedupe_key: str | None = None
    created_at: datetime
    updated_at: datetime
    attribution: ContactAttribution | None = None
    #: A website lead the owners must hear about (new, or asked again after
    #: ``REPEAT_INQUIRY_AFTER``). Cleared, and ``owner_alert_sent_at`` set,
    #: once the alert went out; the daily sweep re-sends what is still due
    #: (L9 A6-11). Rows from before the field never become due.
    owner_alert_due_at: datetime | None = None
    owner_alert_sent_at: datetime | None = None
    #: Notes from repeat inquiries, newest last, at most ``MAX_REPEAT_MESSAGES``.
    repeat_messages: list[RepeatMessage] = []


#: A website inquiry repeated after this long is a family asking again: the
#: row is bumped, the new note kept in ``repeat_messages`` and the owners
#: alerted again (A6-4).
#: Inside it, a repeat is a double tap and changes nothing.
REPEAT_INQUIRY_AFTER = timedelta(hours=24)


# --- normalisation (shared by validation and the dedupe key) ---


def normalize_text(value: str | None) -> str | None:
    """Trim and collapse internal whitespace; blank becomes None."""
    if value is None:
        return None
    collapsed = _WS.sub(" ", value).strip()
    return collapsed or None


def normalize_email(value: str | None) -> str | None:
    text = normalize_text(value)
    return text.lower() if text else None


def normalize_phone_digits(value: str | None) -> str | None:
    """Digits only (spec §3.2 phone search matches on digits); blank becomes None."""
    if value is None:
        return None
    digits = _NON_DIGIT.sub("", value)
    return digits or None


#: Sources whose rows carry a ``dedupe_key``. Only the anonymous public form:
#: staff quick-add rows are always new rows (see ``CrmContact.dedupe_key``).
DEDUPED_SOURCES: frozenset[str] = frozenset({"website"})


def compute_dedupe_key(
    *,
    source: str,
    email: str | None,
    phone_digits: str | None,
    child_name: str | None,
    child_age: str | None,
    requested_session_id: str | None,
) -> str:
    """The idempotency key for one inquiry.

    sha256 hex over the NORMALISED ``source``, ``email`` (lower-cased),
    ``phone_digits``, ``child_name`` (case-folded), ``child_age`` (case-folded)
    and ``requested_session_id``, joined by U+001F, a missing value as ``""``.
    Two submissions with the same values are the same inquiry (a double tap,
    a flaky-network retry) and resolve to one row; a different class, child,
    age or source is a new lead. The person's own ``name`` is excluded on
    purpose so a retry with a corrected spelling still dedupes.
    """
    parts = [
        source,
        normalize_email(email) or "",
        normalize_phone_digits(phone_digits) or "",
        (normalize_text(child_name) or "").casefold(),
        (normalize_text(child_age) or "").casefold(),
        normalize_text(requested_session_id) or "",
    ]
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
