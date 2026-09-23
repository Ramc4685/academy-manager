"""The academy's own public identity for the public tenant page (Lane B2).

Identity's half of ``GET /api/v2/public/academy``: the name, logo, colour
tokens, venue and page switches a stranger may see. Read-only and
allow-listed: it never returns the contact email or phone, ids, plan or
status fields, and it never creates a record (an anonymous GET must not
``upsert_defaults`` an academy into existence).

* **Name.** ``display_name``; a stored value equal to the internal
  ``academy_id`` (what ``upsert_defaults`` writes) is not a name, so the
  public slug stands in, and failing that a neutral word.
* **Colour tokens.** ``brand_color`` only when it is a valid hex; the fill
  and on-fill text pair come from ``readable_button_colors`` (THE colour
  derivation, shared with the email theme), with the product's cobalt when
  the academy set no colour.
* **Logo.** Only an http(s) URL, re-checked on read so a hand-edited
  ``javascript:`` value never reaches an ``src``.
* **Venue.** The academy's ``address`` and ``hours_text`` ("Find us").
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol

from backend.v2.contexts.identity.domain.public_page import (
    PUBLIC_PAGE_FIELD,
    PublicPageSettings,
)
from backend.v2.shared.comms.colour import readable_button_colors
from backend.v2.shared.comms.email_theme import COBALT
from backend.v2.shared.security.external_url import InvalidExternalUrl, validate_external_url

_HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_MAX_TEXT = 500
_FALLBACK_NAME = "Academy"


class AcademyReadRepo(Protocol):
    async def find_by_id(self, academy_id: str) -> dict[str, Any] | None: ...


@dataclass(frozen=True)
class PublicAcademyProfile:
    name: str
    logo_url: str | None
    #: The academy's own colour (validated hex) or None when unset/invalid.
    brand_color: str | None
    #: Button/fill colour: ``brand_color`` (or cobalt), nudged only if needed
    #: so that ``brand_on_color`` text on it clears WCAG AA 4.5:1.
    brand_fill: str
    brand_on_color: str
    address: str | None
    hours_text: str | None
    timezone: str | None
    currency: str
    settings: PublicPageSettings


class GetPublicAcademyProfile:
    def __init__(self, academy_repo: AcademyReadRepo) -> None:
        self._repo = academy_repo

    async def execute(self, academy_id: str) -> PublicAcademyProfile | None:
        """None when this academy has no record (the page answers 404)."""
        doc = await self._repo.find_by_id(academy_id)
        if not doc:
            return None
        brand_color = _hex_or_none(doc.get("brand_color"))
        fill, on_color = readable_button_colors(brand_color or COBALT)
        return PublicAcademyProfile(
            name=_public_name(doc, academy_id),
            logo_url=_http_url_or_none(doc.get("logo_url")),
            brand_color=brand_color,
            brand_fill=fill,
            brand_on_color=on_color,
            address=_text(doc.get("address")),
            hours_text=_text(doc.get("hours_text")),
            timezone=_text(doc.get("timezone")),
            currency=(_text(doc.get("currency")) or "USD").upper()[:3],
            settings=PublicPageSettings.from_stored(doc.get(PUBLIC_PAGE_FIELD)),
        )


def _public_name(doc: dict[str, Any], academy_id: str) -> str:
    for candidate in (doc.get("display_name"), doc.get("name"), doc.get("slug")):
        text = _text(candidate)
        if text and text != academy_id and "@" not in text:
            return text[:120]
    return _FALLBACK_NAME


def _hex_or_none(value: object) -> str | None:
    text = str(value or "").strip()
    return text.lower() if _HEX.match(text) else None


def _http_url_or_none(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return validate_external_url(value.strip(), field_label="logo")
    except InvalidExternalUrl:
        return None


def _text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:_MAX_TEXT] or None
