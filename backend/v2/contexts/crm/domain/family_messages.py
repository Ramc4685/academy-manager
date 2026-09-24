"""The family Messages tab (People CRM spec §4 "Messages", Phase 6; roadmap L4c).

One thread per family, newest first, mixing:

* the emails the app already sent and logged: campaign deliveries
  (``message_deliveries``), the parent digest (``parent_digest_sends``), the
  parent's absence-notice confirmation (``absence_notice_sends``) and invoice
  copies to the family's contacts (``invoice_contact_email_sends``, #956),
  each with its delivery status;
* contacts a staff member logged by hand (``family_contact_log``): a
  WhatsApp, SMS or email sent from their own phone or mail app (the
  ``wa.me`` / ``sms:`` / ``mailto:`` handoff), a call, or a talk in person.

The app never sends SMS or WhatsApp itself (owner decision 2026-09-20: a later
phase). A handoff the staff member did not confirm is stored ``not_logged``
so it can be completed later, never silently lost.

Pure: no I/O, no Mongo types.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Literal, get_args

from pydantic import BaseModel, ConfigDict

from backend.v2.contexts.crm.domain.errors import InvalidContactLog

#: How a message reached (or was meant to reach) the family.
MessageChannel = Literal["email", "whatsapp", "sms", "call", "in_person"]
MESSAGE_CHANNELS: frozenset[str] = frozenset(get_args(MessageChannel))

#: Where a thread entry came from.
MessageSource = Literal["campaign", "digest", "absence_notice", "invoice_copy", "staff_log"]

#: Delivery status of an app email, or the state of a staff-logged contact.
MessageStatus = Literal["queued", "sent", "opened", "failed", "logged", "not_logged"]

#: A logged contact's state: confirmed, or a handoff still to be confirmed.
ContactLogStatus = Literal["logged", "not_logged"]
CONTACT_LOG_STATUSES: frozenset[str] = frozenset(get_args(ContactLogStatus))

#: A logged contact's note (the pre-filled text, or a short call summary).
MAX_CONTACT_LOG_NOTE_LEN: Final = 2000
#: Newest entries shown in one thread (each source is read with this limit).
MESSAGES_CAP: Final = 200

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SPACES = re.compile(r"[ \t\f\v]+")


class FamilyContactLog(BaseModel):
    """One contact a staff member logged on a family."""

    model_config = ConfigDict(frozen=True)

    log_id: str
    academy_id: str
    parent_id: str
    channel: MessageChannel
    status: ContactLogStatus
    note: str | None = None
    author_user_id: str
    created_at: datetime
    updated_at: datetime
    logged_at: datetime | None = None


@dataclass(frozen=True)
class MessageEntry:
    """One row of the family's Messages thread."""

    entry_id: str
    at: datetime
    channel: MessageChannel
    source: MessageSource
    status: MessageStatus
    summary: str
    detail: str | None = None
    recipient: str | None = None
    author_user_id: str | None = None
    failed_reason: str | None = None
    #: Set on a staff-logged contact, so a ``not_logged`` one can be completed.
    log_id: str | None = None


def as_utc(value: datetime) -> datetime:
    """Aware UTC; a naive value is taken to be UTC (Mongo returns naive, #706)."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def merge_messages(
    batches: Iterable[Sequence[MessageEntry]], *, cap: int = MESSAGES_CAP
) -> list[MessageEntry]:
    """Every batch in one list, newest first (``entry_id`` breaks ties), one
    row per ``entry_id``, cut to ``cap``."""
    seen: dict[str, MessageEntry] = {}
    for batch in batches:
        for entry in batch:
            seen.setdefault(entry.entry_id, entry)
    ordered = sorted(seen.values(), key=lambda e: (-as_utc(e.at).timestamp(), e.entry_id))
    return ordered[:cap]


def parse_channel(raw: str | None) -> MessageChannel:
    if raw not in MESSAGE_CHANNELS:
        raise InvalidContactLog("Pick WhatsApp, SMS, email, a call or in person.", field="channel")
    return raw  # type: ignore[return-value]


def parse_contact_log_status(raw: str | None) -> ContactLogStatus:
    if raw not in CONTACT_LOG_STATUSES:
        raise InvalidContactLog("Status must be logged or not_logged.", field="status")
    return raw  # type: ignore[return-value]


def normalize_contact_log_note(raw: str | None) -> str | None:
    """Control characters dropped, runs of spaces collapsed, trimmed; ``None``
    when empty. Raises ``InvalidContactLog`` over the cap."""
    text = _CONTROL.sub("", (raw or "").replace("\r\n", "\n").replace("\r", "\n"))
    lines = [_SPACES.sub(" ", line).rstrip() for line in text.split("\n")]
    note = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    if len(note) > MAX_CONTACT_LOG_NOTE_LEN:
        raise InvalidContactLog(
            f"A note can be at most {MAX_CONTACT_LOG_NOTE_LEN} characters.", field="note"
        )
    return note or None


_CHANNEL_WORDS: Final[dict[str, str]] = {
    "email": "Email",
    "whatsapp": "WhatsApp",
    "sms": "SMS",
    "call": "Phone call",
    "in_person": "Spoke in person",
}


def contact_log_summary(log: FamilyContactLog) -> str:
    word = _CHANNEL_WORDS[log.channel]
    if log.channel in ("call", "in_person"):
        return word
    if log.status == "not_logged":
        return f"{word} opened, not confirmed as sent"
    return f"{word} sent from staff's own app"


def contact_log_entry(log: FamilyContactLog) -> MessageEntry:
    return MessageEntry(
        entry_id=f"log:{log.log_id}",
        at=log.logged_at or log.created_at,
        channel=log.channel,
        source="staff_log",
        status=log.status,
        summary=contact_log_summary(log),
        detail=log.note,
        author_user_id=log.author_user_id,
        log_id=log.log_id,
    )


def can_complete_contact_log(log: FamilyContactLog, *, user_id: str, roles: Iterable[str]) -> bool:
    """The staff member who logged it, or an academy owner."""
    return log.author_user_id == user_id or "owner" in set(roles)
