"""A parent's class calendar as a live iCalendar subscription (pure, no I/O).

Two halves:

* **The link.** ``<parent_id>.<signature>``: an HMAC over the academy, the
  parent and the parent's link version. Nothing secret is stored — the
  version is a counter, so "Reset link" bumps it and every older link stops
  verifying. The academy is not in the token: it comes from the request host,
  so a link opened on another academy's host never verifies there.
* **The file.** RFC 5545 text a phone calendar subscribes to. A called-off
  class stays in the feed as ``STATUS:CANCELLED`` with "No class" in the
  title, so a subscribed calendar strikes it through instead of the class
  silently vanishing.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
from dataclasses import dataclass
from datetime import UTC, datetime

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_SIG_LEN = 32


def _signature(*, secret: str, academy_id: str, parent_id: str, version: int) -> str:
    message = f"calendar-feed:v1:{academy_id}:{parent_id}:{version}".encode()
    digest = hmac.new(secret.encode(), message, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")[:_SIG_LEN]


def mint_feed_token(*, secret: str, academy_id: str, parent_id: str, version: int) -> str:
    if not _ID_RE.fullmatch(parent_id):
        raise ValueError("parent id is not token-safe")
    sig = _signature(secret=secret, academy_id=academy_id, parent_id=parent_id, version=version)
    return f"{parent_id}.{sig}"


def parse_feed_token(token: str) -> tuple[str, str] | None:
    """``(parent_id, signature)`` for a well-formed token, else ``None``."""
    parent_id, sep, sig = token.partition(".")
    if not sep or not _ID_RE.fullmatch(parent_id) or len(sig) != _SIG_LEN:
        return None
    return parent_id, sig


def feed_signature_matches(
    *, secret: str, academy_id: str, parent_id: str, version: int, signature: str
) -> bool:
    expected = _signature(
        secret=secret, academy_id=academy_id, parent_id=parent_id, version=version
    )
    return hmac.compare_digest(expected, signature)


@dataclass(frozen=True)
class FeedEvent:
    uid: str
    title: str
    start_at: datetime
    end_at: datetime
    cancelled: bool
    location: str | None = None
    description: str | None = None


def _escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def _stamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)  # stored datetimes are naive UTC
    return value.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def _fold(line: str) -> str:
    """Fold at 75 octets (RFC 5545 §3.1), never splitting a UTF-8 character."""
    out: list[str] = []
    current = ""
    for char in line:
        limit = 75 if not out else 74  # continuation lines start with a space
        if len((current + char).encode()) > limit:
            out.append(current)
            current = char
        else:
            current += char
    out.append(current)
    return "\r\n ".join(out)


def render_feed(*, calendar_name: str, events: list[FeedEvent], now: datetime) -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Academy Manager//Class calendar//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escape(calendar_name)}",
        "REFRESH-INTERVAL;VALUE=DURATION:PT1H",
        "X-PUBLISHED-TTL:PT1H",
    ]
    stamp = _stamp(now)
    for event in events:
        lines += [
            "BEGIN:VEVENT",
            f"UID:{_escape(event.uid)}",
            f"DTSTAMP:{stamp}",
            f"DTSTART:{_stamp(event.start_at)}",
            f"DTEND:{_stamp(event.end_at)}",
            f"SUMMARY:{_escape(event.title)}",
            f"STATUS:{'CANCELLED' if event.cancelled else 'CONFIRMED'}",
            # A cancellation is a later revision of the same event; clients
            # that compare SEQUENCE then replace the class they already hold.
            f"SEQUENCE:{1 if event.cancelled else 0}",
        ]
        if event.location:
            lines.append(f"LOCATION:{_escape(event.location)}")
        if event.description:
            lines.append(f"DESCRIPTION:{_escape(event.description)}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"
