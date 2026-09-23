"""Pure rules for the anonymous public class listing (public tenant page, Lane B2).

Three things the public page needs that must never be decided twice:

* **Opaque class id.** The page never carries the Mongo ``session_id`` (brief
  section 5, "internal ids"). :func:`public_class_id` derives a short,
  stable, non-reversible id from ``(academy_id, session_id)``. It is a
  one-way digest, not a lookup key: anything that needs the class back (the
  B4 trial form's optional class choice) recomputes it over the academy's
  *published* classes and matches, which also guarantees a private class can
  never be addressed through it.
* **Seat band.** Exact capacity and enrolled counts let a stranger rebuild
  enrolment and revenue, so the public page shows a band only: ``open``,
  ``few`` (with the number only when :data:`FEW_SEATS_THRESHOLD` or fewer
  remain) or ``waitlist`` (full, join waitlist). The brief's fourth band,
  ``assessment``, has no backing field on a class yet and is not emitted.
* **Coach public name.** Per-class ``coach_display``: the display name in
  full, the first word only, or nothing. A stored name that looks like an
  email address (registration falls back to the email when no name was
  given) is never shown.
"""

from __future__ import annotations

import base64
import hashlib
from typing import Final, Literal

from backend.v2.contexts.enrollment.domain.programs import CoachDisplay

SeatBand = Literal["open", "few", "waitlist"]

#: At or below this many seats left the band is ``few`` and the number is shown.
FEW_SEATS_THRESHOLD: Final = 3

_CLASS_ID_PREFIX: Final = "c_"
_PROGRAM_ID_PREFIX: Final = "p_"
#: Bump only together with a plan for links already shared with the old ids.
_ID_DOMAIN: Final = "courtmastr.public-id.v1"
_ID_LENGTH: Final = 16  # base32 chars = 80 bits, ample for a few hundred classes


def _digest(kind: str, academy_id: str, internal_id: str) -> str:
    raw = f"{_ID_DOMAIN}\x1f{kind}\x1f{academy_id}\x1f{internal_id}".encode()
    digest = hashlib.sha256(raw).digest()
    return base64.b32encode(digest).decode("ascii").rstrip("=").lower()[:_ID_LENGTH]


def public_class_id(academy_id: str, session_id: str) -> str:
    """Stable opaque id for one class on one academy's public page."""
    return _CLASS_ID_PREFIX + _digest("class", academy_id, session_id)


def public_program_id(academy_id: str, program_id: str) -> str:
    """Stable opaque id for one program on one academy's public page."""
    return _PROGRAM_ID_PREFIX + _digest("program", academy_id, program_id)


def seats_left(capacity: int, occupied: int) -> int:
    return max(int(capacity) - max(int(occupied), 0), 0)


def seat_band(capacity: int, occupied: int) -> tuple[SeatBand, int | None]:
    """``(band, seats_left_to_show)``; the number only inside the ``few`` band."""
    left = seats_left(capacity, occupied)
    if left <= 0:
        return "waitlist", None
    if left <= FEW_SEATS_THRESHOLD:
        return "few", left
    return "open", None


def coach_public_name(name: str | None, display: CoachDisplay) -> str | None:
    """The coach name the public page may print for a class, or None."""
    if display == "hidden" or not name:
        return None
    text = " ".join(str(name).split())
    if not text or "@" in text:
        return None
    if display == "first_name":
        return text.split(" ", 1)[0]
    return text
