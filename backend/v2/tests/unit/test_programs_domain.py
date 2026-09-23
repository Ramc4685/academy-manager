"""Program, age band, class public profile and public page settings rules (Lane B1)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from backend.v2.contexts.enrollment.domain.programs import (
    AgeBand,
    ClassPublicProfile,
    Program,
)
from backend.v2.contexts.identity.domain.public_page import PublicPageSettings

NOW = datetime(2026, 9, 23, tzinfo=UTC)


def _program(**overrides: object) -> Program:
    fields: dict[str, object] = {
        "program_id": "p-1",
        "academy_id": "acad-riverside",
        "name": "Juniors",
        "created_at": NOW,
        "updated_at": NOW,
    }
    fields.update(overrides)
    return Program(**fields)  # type: ignore[arg-type]


def test_program_name_is_stripped_and_required() -> None:
    assert _program(name="  Juniors  ").name == "Juniors"
    with pytest.raises(ValidationError):
        _program(name="   ")
    with pytest.raises(ValidationError):
        _program(name="x" * 81)


def test_program_blank_optional_text_reads_as_unset() -> None:
    program = _program(public_description="  ", level="")
    assert program.public_description is None
    assert program.level is None


def test_program_sort_order_is_non_negative() -> None:
    with pytest.raises(ValidationError):
        _program(sort_order=-1)


def test_age_band_rules() -> None:
    assert AgeBand(min_age=6, max_age=9).max_age == 9
    assert AgeBand(min_age=18).max_age is None  # adults: "18 and up"
    with pytest.raises(ValidationError):
        AgeBand(min_age=10, max_age=6)
    with pytest.raises(ValidationError):
        AgeBand()
    with pytest.raises(ValidationError):
        AgeBand(min_age=120)


def test_class_profile_defaults_are_private_full_name_academy_period() -> None:
    profile = ClassPublicProfile(session_id="s-1")
    assert profile.published is False
    assert profile.coach_display == "full_name"
    assert profile.price_period is None
    assert profile.effective_price_period() == "month"
    assert profile.effective_price_period("term") == "term"
    assert (
        ClassPublicProfile(session_id="s", price_period="class").effective_price_period("term")
        == "class"
    )


@pytest.mark.parametrize("field,value", [("price_period", "week"), ("coach_display", "initials")])
def test_class_profile_rejects_unknown_options(field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        ClassPublicProfile(session_id="s-1", **{field: value})  # type: ignore[arg-type]


def test_public_page_defaults_when_nothing_is_stored() -> None:
    expected = {
        "published": False,
        "show_price": True,
        "show_availability": True,
        "price_period_default": "month",
        "trials_open": True,
        "privacy_notice_url": None,
    }
    assert PublicPageSettings.from_stored(None).model_dump() == expected
    assert PublicPageSettings.from_stored({}).model_dump() == expected
    assert PublicPageSettings.from_stored("garbage").model_dump() == expected


def test_public_page_partial_subdocument_keeps_other_defaults() -> None:
    settings = PublicPageSettings.from_stored({"published": True, "show_price": False})
    assert settings.published is True
    assert settings.show_price is False
    assert settings.show_availability is True
    assert settings.trials_open is True
    assert settings.price_period_default == "month"


def test_public_page_one_bad_stored_key_falls_back_alone() -> None:
    settings = PublicPageSettings.from_stored(
        {
            "published": True,
            "price_period_default": "fortnight",
            "privacy_notice_url": "javascript:x",
        }
    )
    assert settings.published is True
    assert settings.price_period_default == "month"
    assert settings.privacy_notice_url is None


def test_public_page_privacy_link_must_be_http() -> None:
    ok = PublicPageSettings(privacy_notice_url=" https://riverside.example/privacy ")
    assert ok.privacy_notice_url == "https://riverside.example/privacy"
    with pytest.raises(ValidationError):
        PublicPageSettings(privacy_notice_url="javascript:alert(1)")
