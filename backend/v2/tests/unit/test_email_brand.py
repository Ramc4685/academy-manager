"""``shared.comms.email_brand``: the full academy brand for money/account email."""

from __future__ import annotations

from typing import Any

import pytest

from backend.v2.shared.comms.email_brand import (
    AcademyEmailBrands,
    brand_from_academy_doc,
    branded_as,
    lookup_academy_brand,
)
from backend.v2.shared.comms.email_theme import EmailBrand


def test_name_only_doc_is_a_name_only_brand() -> None:
    brand = brand_from_academy_doc({"display_name": "BLNO Badminton"}, fallback_name="x")
    assert brand.academy_name == "BLNO Badminton"
    assert (brand.logo_url, brand.brand_color, brand.contact_email, brand.contact_phone) == (
        None,
        None,
        None,
        None,
    )


def test_name_follows_the_repository_name_rule() -> None:
    assert brand_from_academy_doc({"name": "Legacy"}, fallback_name="x").academy_name == "Legacy"
    assert brand_from_academy_doc({}, fallback_name="Your academy").academy_name == "Your academy"
    assert brand_from_academy_doc(None, fallback_name="Fallback").academy_name == "Fallback"


def test_full_doc_carries_logo_colour_contact_and_sender() -> None:
    brand = brand_from_academy_doc(
        {
            "display_name": "Riverside",
            "logo_url": " https://cdn.test/logo.png ",
            "brand_color": "#0f766e",
            "contact_email": "desk@riverside.test",
            "contact_phone": "+1 555 0100",
            "email_sender_name": "Riverside Desk",
            "email_reply_to": "desk@riverside.example.com",
        },
        fallback_name="x",
    )
    assert brand == EmailBrand(
        academy_name="Riverside",
        brand_color="#0f766e",
        logo_url="https://cdn.test/logo.png",
        contact_email="desk@riverside.test",
        contact_phone="+1 555 0100",
        sender_name="Riverside Desk",
        reply_to="desk@riverside.example.com",
    )


@pytest.mark.parametrize(
    "logo",
    [
        "http://cdn.test/logo.png",
        "javascript:alert(1)",
        "//cdn.test/logo.png",
        "https://",
        "data:image/png;base64,AAAA",
        "https://cdn.test/a\nb.png",
        42,
        "",
    ],
)
def test_only_https_logos_are_kept(logo: Any) -> None:
    assert brand_from_academy_doc({"logo_url": logo}, fallback_name="x").logo_url is None


def test_non_string_contact_values_are_dropped() -> None:
    brand = brand_from_academy_doc(
        {"contact_email": ["a@b.test"], "contact_phone": 5550100, "brand_color": 7},
        fallback_name="x",
    )
    assert (brand.contact_email, brand.contact_phone, brand.brand_color) == (None, None, None)


def test_branded_as_pins_the_subject_name() -> None:
    assert branded_as(None, "A") == EmailBrand(academy_name="A")
    pinned = branded_as(EmailBrand(academy_name="B", logo_url="https://x.test/l.png"), "A")
    assert pinned.academy_name == "A"
    assert pinned.logo_url == "https://x.test/l.png"


class _Repo:
    def __init__(self, docs: dict[str, Any]) -> None:
        self._docs = docs

    async def find_by_id(self, academy_id: str) -> Any:
        return self._docs.get(academy_id)


@pytest.mark.asyncio
async def test_lookup_reads_only_the_asked_academy_and_never_raises() -> None:
    repo = _Repo(
        {
            "a": {"display_name": "A", "logo_url": "https://a.test/l.png"},
            "b": {"display_name": "B", "logo_url": "https://b.test/l.png"},
        }
    )
    brand = await AcademyEmailBrands(repo).get_academy_brand("a")
    assert brand is not None and brand.logo_url == "https://a.test/l.png"
    assert await AcademyEmailBrands(repo).get_academy_brand("missing") is None
    assert await lookup_academy_brand(None, "a") is None
    assert await lookup_academy_brand(object(), "a") is None

    class _Broken:
        async def find_by_id(self, academy_id: str) -> Any:
            raise RuntimeError("down")

    assert await lookup_academy_brand(_Broken(), "a") is None
