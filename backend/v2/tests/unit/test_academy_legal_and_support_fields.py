"""Support email + legal links on the academy record (Settings overhaul Phase 4 PR 13).

The privacy link has ONE stored copy: ``academies.public_page.privacy_notice_url``,
the key the public page, the trial form and CRM consent stamping read. The
Academy profile card writes that same key.
"""

from __future__ import annotations

import pytest

from backend.v2.contexts.identity.application.get_academy_use_case import GetAcademyUseCase
from backend.v2.contexts.identity.application.public_academy_profile import (
    GetPublicAcademyProfile,
)
from backend.v2.contexts.identity.application.public_page_settings import GetPublicPageSettings
from backend.v2.contexts.identity.application.update_academy_use_case import UpdateAcademyUseCase
from backend.v2.contexts.identity.domain.legal_links import https_url_or_none, validate_https_url
from backend.v2.contexts.identity.infrastructure.mongo_academy_repo import MongoAcademyRepository

ACADEMY = "acad-legal"
PRIVACY = "https://legal.example.test/privacy"


async def _repo() -> MongoAcademyRepository:
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["legal"]
    await db["academies"].insert_one(
        {
            "academy_id": ACADEMY,
            "display_name": "Legal Club",
            "contact_email": "owner@legal.example.test",
        }
    )
    return MongoAcademyRepository(db)


@pytest.mark.parametrize(
    "bad",
    [
        "javascript:alert(1)",
        "http://legal.example.test/terms",
        "ftp://legal.example.test/terms",
        "data:text/html,hi",
        "//legal.example.test/terms",
        "legal.example.test/terms",
        "https://",
        "https://legal.example.test/a b",
        "https://legal.example.test/\nx",
    ],
)
def test_terms_and_refund_links_are_https_only(bad: str) -> None:
    with pytest.raises(ValueError):
        validate_https_url(bad, field_label="terms of service link")
    assert https_url_or_none(bad) is None


def test_https_link_is_trimmed_and_blank_clears() -> None:
    assert validate_https_url(" https://legal.example.test/t ", field_label="x") == (
        "https://legal.example.test/t"
    )
    assert validate_https_url("  ", field_label="x") is None
    assert validate_https_url(None, field_label="x") is None


async def test_academy_with_none_of_the_new_fields_reads_as_unset() -> None:
    """BLNO today: nothing stored, nothing changes."""
    out = await GetAcademyUseCase(await _repo()).execute(ACADEMY)
    assert (out.support_email, out.terms_url, out.refund_policy_url, out.privacy_notice_url) == (
        None,
        None,
        None,
        None,
    )


async def test_privacy_link_is_written_to_the_public_page_key_only() -> None:
    repo = await _repo()
    out = await UpdateAcademyUseCase(repo).execute(
        ACADEMY,
        {
            "privacy_notice_url": PRIVACY,
            "support_email": "help@legal.example.test",
            "terms_url": "https://legal.example.test/terms",
        },
    )
    assert out.privacy_notice_url == PRIVACY
    assert out.support_email == "help@legal.example.test"
    assert out.terms_url == "https://legal.example.test/terms"

    stored = await repo.find_by_id(ACADEMY)
    assert stored is not None
    assert stored["public_page"]["privacy_notice_url"] == PRIVACY
    assert "privacy_notice_url" not in stored  # never a second copy

    # The consumers (public page, trial form, CRM consent stamp) read this key.
    settings = await GetPublicPageSettings(repo).execute(ACADEMY)
    assert settings.privacy_notice_url == PRIVACY
    profile = await GetPublicAcademyProfile(repo).execute(ACADEMY)
    assert profile is not None
    assert profile.settings.privacy_notice_url == PRIVACY
    assert profile.support_email == "help@legal.example.test"
    assert profile.terms_url == "https://legal.example.test/terms"


async def test_clearing_the_privacy_link_clears_the_public_page_key() -> None:
    repo = await _repo()
    use_case = UpdateAcademyUseCase(repo)
    await use_case.execute(ACADEMY, {"privacy_notice_url": PRIVACY})
    out = await use_case.execute(ACADEMY, {"privacy_notice_url": None})
    assert out.privacy_notice_url is None
    assert (await GetPublicPageSettings(repo).execute(ACADEMY)).privacy_notice_url is None


async def test_saving_the_privacy_link_keeps_the_other_public_page_switches() -> None:
    repo = await _repo()
    await repo.update_by_id(
        ACADEMY, {"public_page.published": True, "public_page.show_price": False}
    )
    await UpdateAcademyUseCase(repo).execute(ACADEMY, {"privacy_notice_url": PRIVACY})
    settings = await GetPublicPageSettings(repo).execute(ACADEMY)
    assert settings.published is True and settings.show_price is False
    assert settings.privacy_notice_url == PRIVACY


async def test_public_profile_footer_email_prefers_support_email_then_contact_email() -> None:
    repo = await _repo()
    profile = await GetPublicAcademyProfile(repo).execute(ACADEMY)
    assert profile is not None and profile.support_email == "owner@legal.example.test"
    await repo.update_by_id(ACADEMY, {"support_email": "help@legal.example.test"})
    profile = await GetPublicAcademyProfile(repo).execute(ACADEMY)
    assert profile is not None and profile.support_email == "help@legal.example.test"
