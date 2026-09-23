"""Per-academy sender identity for outbound email (roadmap L9a).

The From *address* is platform-owned: it is the single verified
``SENDER_EMAIL`` configured on the Resend adapter, because sending-domain
verification is an owner-side DNS task. What an academy controls is:

* ``email_sender_name`` — the display name in ``From: "<name>" <SENDER_EMAIL>``.
  Falls back to the academy's ``display_name`` (then ``name``); with neither,
  the From header stays the bare address, exactly as before.
* ``email_reply_to`` — where replies go. Absent ⇒ ``None`` and each call site
  keeps its previous reply-to behaviour (no migration, no backfill).

Only the display name ever reaches the send port (``sender_name``); the
adapter composes the header with its own configured address via
:func:`format_from_header`, so an academy value can never change the From
address. Both values are re-validated here at read time, so a document that
predates the settings validation (or was edited by hand) cannot inject a
header.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from email.utils import formataddr, parseaddr
from typing import Any

from pydantic import EmailStr, TypeAdapter, ValidationError

from backend.v2.shared.tenancy.context import current_academy_id

log = logging.getLogger(__name__)

SENDER_NAME_MAX_LENGTH = 80

# CR/LF (and every other control character) would let a value start a new
# header; angle brackets would let it smuggle a second address into From.
_FORBIDDEN_NAME_CHARS = re.compile(r"[\x00-\x1f\x7f<>]")

_EMAIL_ADAPTER: TypeAdapter[str] = TypeAdapter(EmailStr)


class InvalidSenderValue(ValueError):
    """An academy sender name or reply-to failed validation."""


def validate_sender_name(value: str | None) -> str | None:
    """Normalise an ``email_sender_name`` for storage.

    Blank ⇒ ``None`` (clears the override). Raises :class:`InvalidSenderValue`
    for control characters, angle brackets or more than 80 characters.
    """
    if value is None:
        return None
    if _FORBIDDEN_NAME_CHARS.search(value):
        raise InvalidSenderValue("Sender name cannot contain line breaks or angle brackets.")
    cleaned = value.strip()
    if not cleaned:
        return None
    if len(cleaned) > SENDER_NAME_MAX_LENGTH:
        raise InvalidSenderValue(
            f"Sender name must be {SENDER_NAME_MAX_LENGTH} characters or fewer."
        )
    return cleaned


def validate_reply_to(value: str | None) -> str | None:
    """Normalise an ``email_reply_to`` for storage. Blank ⇒ ``None``."""
    if value is None:
        return None
    if re.search(r"[\x00-\x1f\x7f]", value):
        raise InvalidSenderValue("Reply-to address cannot contain line breaks.")
    cleaned = value.strip()
    if not cleaned:
        return None
    try:
        return str(_EMAIL_ADAPTER.validate_python(cleaned))
    except ValidationError as exc:
        raise InvalidSenderValue("Reply-to must be a valid email address.") from exc


def _safe(validator: Any, value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        result: str | None = validator(value)
    except InvalidSenderValue:
        return None
    return result


@dataclass(frozen=True, slots=True)
class SenderIdentity:
    """What a send path passes to the port: display name + reply-to."""

    sender_name: str | None = None
    reply_to: str | None = None


def resolve_sender(academy_doc: dict[str, Any] | None) -> SenderIdentity:
    """The sender identity for one academy document.

    ``academy_doc`` must be the document of the academy the email is *for*
    (the current tenant); nothing here looks anything up, so there is no way
    for another academy's name to leak in.
    """
    if not academy_doc:
        return SenderIdentity()
    name = (
        _safe(validate_sender_name, academy_doc.get("email_sender_name"))
        or _safe(validate_sender_name, academy_doc.get("display_name"))
        or _safe(validate_sender_name, academy_doc.get("name"))
    )
    reply_to = _safe(validate_reply_to, academy_doc.get("email_reply_to"))
    return SenderIdentity(sender_name=name, reply_to=reply_to)


def format_from_header(sender_name: str | None, address: str) -> str:
    """``"Name" <address>`` with RFC 2047 encoding for non-ASCII names.

    An invalid or empty name yields ``address`` unchanged — a bad display name
    must never cost a send. ``address`` may itself already carry a display name
    (``SENDER_EMAIL="Platform <noreply@x>"``); only its address part is kept
    when an academy name replaces it.
    """
    name = _safe(validate_sender_name, sender_name)
    _, bare = parseaddr(address)
    if not name or not bare:
        return address
    return formataddr((name, bare))


async def sender_identity_for_current_academy(academies: Any | None) -> SenderIdentity:
    """:func:`resolve_sender` for the academy in the current tenant context.

    ``academies`` is anything with ``async find_by_id(academy_id)`` (the
    academy repository). Never raises: an unset tenant or a failed lookup
    yields the empty identity, i.e. the pre-L9a From header and no reply-to,
    because a missing display name must never cost a send. ``academies=None``
    (a notifier composed without a lookup) is the same empty identity.
    """
    if academies is None:
        return SenderIdentity()
    try:
        doc = await academies.find_by_id(current_academy_id())
    except Exception:
        log.warning("sender_identity_lookup_failed", exc_info=True)
        return SenderIdentity()
    return resolve_sender(doc if isinstance(doc, dict) else None)
