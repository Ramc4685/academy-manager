"""The full academy brand for transactional email (hardcoded-values row 6).

Money and account emails (invoice, receipt, reminders, autopay notice,
add-card, login invite, verification, dispute notice) used to render with the
academy *name* only, while the digests already carried the logo, the brand
colour and the contact footer. This module builds the whole
:class:`~backend.v2.shared.comms.email_theme.EmailBrand` from the academy
document in one place so every send path gets the same thing.

Academy-controlled values are re-validated at read time, because the document
may predate settings validation or have been edited by hand:

* ``logo_url`` is used only when it is an absolute ``https`` URL;
* ``brand_color`` is passed through, and ``EmailBrand.accent()`` drops
  anything that is not a hex colour;
* contact values must be non-empty strings; the shell escapes them.

An academy with none of these set renders exactly as before (name only,
cobalt rule, no contact line). The lookup never raises: a failed read costs
the email its logo, never its delivery.

Lives in ``shared`` so both context use cases and composition adapters can
use it without importing each other (ADR-0005).
"""

from __future__ import annotations

import dataclasses
import logging
import re
from typing import Any
from urllib.parse import urlsplit

from backend.v2.shared.comms.email_theme import EmailBrand
from backend.v2.shared.comms.sender_identity import resolve_sender

log = logging.getLogger(__name__)

_LOGO_URL_MAX_LENGTH = 2048
_CONTACT_MAX_LENGTH = 254
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def _text(value: Any, *, max_length: int) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned or len(cleaned) > max_length or _CONTROL_CHARS.search(cleaned):
        return None
    return cleaned


def _https_url(value: Any) -> str | None:
    url = _text(value, max_length=_LOGO_URL_MAX_LENGTH)
    if url is None:
        return None
    parts = urlsplit(url)
    if parts.scheme.lower() != "https" or not parts.netloc:
        return None
    return url


def brand_from_academy_doc(doc: dict[str, Any] | None, *, fallback_name: str) -> EmailBrand:
    """The email brand for one academy document.

    ``doc`` must be the document of the academy the email is *for*; nothing
    here looks anything up. The name follows ``MongoAcademyRepository
    .get_academy_name`` (``display_name``, then ``name``) so the shell and the
    subject line always agree.
    """
    if not doc:
        return EmailBrand(academy_name=fallback_name)
    name = doc.get("display_name") or doc.get("name")
    identity = resolve_sender(doc)
    brand_color = doc.get("brand_color")
    return EmailBrand(
        academy_name=str(name) if name else fallback_name,
        brand_color=brand_color if isinstance(brand_color, str) and brand_color else None,
        logo_url=_https_url(doc.get("logo_url")),
        contact_email=_text(doc.get("contact_email"), max_length=_CONTACT_MAX_LENGTH),
        contact_phone=_text(doc.get("contact_phone"), max_length=_CONTACT_MAX_LENGTH),
        sender_name=identity.sender_name,
        reply_to=identity.reply_to,
    )


def branded_as(brand: EmailBrand | None, academy_name: str) -> EmailBrand:
    """``brand`` with its name pinned to ``academy_name`` (the name the send
    path already resolved for the subject), or a name-only brand when no
    academy brand was found."""
    if brand is None:
        return EmailBrand(academy_name=academy_name)
    return dataclasses.replace(brand, academy_name=academy_name)


async def lookup_academy_brand(academies: Any | None, academy_id: str) -> EmailBrand | None:
    """:func:`brand_from_academy_doc` for ``academy_id``, read through
    ``academies.find_by_id``. ``None`` when there is no repository, no such
    method, no document, or the read fails."""
    finder = getattr(academies, "find_by_id", None)
    if finder is None or not academy_id:
        return None
    try:
        doc = await finder(academy_id)
    except Exception:
        log.warning("email_brand_lookup_failed", extra={"academy_id": academy_id}, exc_info=True)
        return None
    if not isinstance(doc, dict) or not doc:
        return None
    return brand_from_academy_doc(doc, fallback_name=academy_id)


class AcademyEmailBrands:
    """``AcademyBrandLookup`` port implementation over the academy repository,
    for the context use cases that render their own HTML (login invite,
    verification, add-card reminder)."""

    def __init__(self, academies: Any) -> None:
        self._academies = academies

    async def get_academy_brand(self, academy_id: str) -> EmailBrand | None:
        return await lookup_academy_brand(self._academies, academy_id)
