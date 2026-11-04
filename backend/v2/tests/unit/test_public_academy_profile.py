"""The academy's public identity read (public tenant page, Lane B2)."""

from __future__ import annotations

import asyncio
from typing import Any

from backend.v2.contexts.identity.application.public_academy_profile import (
    GetPublicAcademyProfile,
)
from backend.v2.shared.comms.colour import readable_button_colors
from backend.v2.shared.comms.email_theme import COBALT

ACADEMY = "acad-riverside"


class _Repo:
    def __init__(self, doc: dict[str, Any] | None) -> None:
        self.doc = doc
        self.upserts = 0

    async def find_by_id(self, academy_id: str) -> dict[str, Any] | None:
        return self.doc if self.doc and self.doc.get("academy_id") == academy_id else None

    async def upsert_defaults(self, academy_id: str) -> dict[str, Any]:  # pragma: no cover
        self.upserts += 1
        raise AssertionError("an anonymous read must never create an academy")


def _get(doc: dict[str, Any] | None):  # type: ignore[no-untyped-def]
    return asyncio.run(GetPublicAcademyProfile(_Repo(doc)).execute(ACADEMY))


def test_missing_academy_is_none_and_never_upserted() -> None:
    assert _get(None) is None


def test_profile_derives_colour_tokens_with_the_shared_function() -> None:
    profile = _get(
        {
            "academy_id": ACADEMY,
            "display_name": "Riverside Shuttle Club",
            "brand_color": "#BFD730",
            "logo_url": "https://cdn.example.test/logo.png",
            "address": "1 River Road",
            "hours_text": "Sat 9-12",
            "contact_email": "owner@example.test",
            "contact_phone": "+1 555 0100",
            "currency": "usd",
            "public_page": {"published": True, "show_price": False},
        }
    )
    assert profile is not None
    assert profile.name == "Riverside Shuttle Club"
    assert profile.brand_color == "#bfd730"
    assert (profile.brand_fill, profile.brand_on_color) == readable_button_colors("#bfd730")
    assert profile.brand_on_color == "#0f172a"  # ink on a light yellow-green
    assert profile.address == "1 River Road" and profile.hours_text == "Sat 9-12"
    assert profile.currency == "USD"
    assert profile.settings.published is True and profile.settings.show_price is False
    assert not any(hasattr(profile, f) for f in ("contact_email", "contact_phone", "academy_id"))


def test_invalid_colour_and_hostile_logo_fall_back_safely() -> None:
    profile = _get(
        {
            "academy_id": ACADEMY,
            "display_name": "Riverside Shuttle Club",
            "brand_color": "teal; background:url(x)",
            "logo_url": "javascript:alert(1)",
        }
    )
    assert profile is not None
    assert profile.brand_color is None
    assert (profile.brand_fill, profile.brand_on_color) == readable_button_colors(COBALT)
    assert profile.logo_url is None
    assert profile.settings.published is False  # default, no backfill needed


def test_default_display_name_equal_to_the_internal_id_is_not_shown() -> None:
    profile = _get({"academy_id": ACADEMY, "display_name": ACADEMY, "slug": "riverside-academy"})
    assert profile is not None and profile.name == "riverside-academy"
    bare = _get({"academy_id": ACADEMY, "display_name": ACADEMY})
    assert bare is not None and bare.name == "Academy"
