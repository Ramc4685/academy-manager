"""Academy ``public_page`` settings: defaults with no backfill, partial writes (Lane B1)."""

from __future__ import annotations

from typing import Any

import mongomock_motor
import pytest

from backend.v2.contexts.identity.application.public_page_settings import (
    GetPublicPageSettings,
    UpdatePublicPageSettings,
)
from backend.v2.contexts.identity.domain.errors import InvalidPublicPageSettings
from backend.v2.contexts.identity.infrastructure.mongo_academy_repo import MongoAcademyRepository

ACADEMY = "acad-riverside"


async def _repo() -> tuple[Any, MongoAcademyRepository]:
    db = mongomock_motor.AsyncMongoMockClient()["public_page_settings"]
    # The production academy today: a profile with no public_page key at all.
    await db["academies"].insert_one(
        {"academy_id": ACADEMY, "display_name": "Riverside Shuttle Club"}
    )
    return db, MongoAcademyRepository(db)


async def test_an_academy_with_no_public_page_key_reads_the_defaults() -> None:
    _db, repo = await _repo()
    settings = await GetPublicPageSettings(repo).execute(ACADEMY)
    assert settings.model_dump() == {
        "published": False,
        "show_price": True,
        "show_availability": True,
        "price_period_default": "month",
        "trials_open": True,
        "privacy_notice_url": None,
    }


async def test_saving_one_switch_keeps_every_other_value() -> None:
    db, repo = await _repo()
    update = UpdatePublicPageSettings(repo)
    await update.execute(ACADEMY, {"show_price": False, "price_period_default": "term"})
    after = await update.execute(ACADEMY, {"published": True})
    assert after.published is True
    assert after.show_price is False
    assert after.price_period_default == "term"
    assert after.trials_open is True

    row = await db["academies"].find_one({"academy_id": ACADEMY})
    # Only the keys ever sent are stored; the rest stay defaults-on-read.
    assert row["public_page"] == {
        "show_price": False,
        "price_period_default": "term",
        "published": True,
    }
    assert row["display_name"] == "Riverside Shuttle Club"


async def test_privacy_link_is_stored_trimmed_and_can_be_cleared() -> None:
    _db, repo = await _repo()
    update = UpdatePublicPageSettings(repo)
    saved = await update.execute(
        ACADEMY, {"privacy_notice_url": " https://riverside.example/privacy "}
    )
    assert saved.privacy_notice_url == "https://riverside.example/privacy"
    cleared = await update.execute(ACADEMY, {"privacy_notice_url": None})
    assert cleared.privacy_notice_url is None


@pytest.mark.parametrize(
    "fields",
    [
        {"published": "yes"},
        {"published": 1},
        {"price_period_default": "week"},
        {"privacy_notice_url": "javascript:alert(1)"},
        {"hero_text": "unknown key"},
    ],
)
async def test_invalid_updates_are_refused_and_write_nothing(fields: dict[str, Any]) -> None:
    db, repo = await _repo()
    with pytest.raises(InvalidPublicPageSettings):
        await UpdatePublicPageSettings(repo).execute(ACADEMY, fields)
    row = await db["academies"].find_one({"academy_id": ACADEMY})
    assert "public_page" not in row


async def test_a_missing_academy_row_is_created_then_patched() -> None:
    db = mongomock_motor.AsyncMongoMockClient()["public_page_settings_fresh"]
    repo = MongoAcademyRepository(db)
    saved = await UpdatePublicPageSettings(repo).execute("acad-new", {"trials_open": False})
    assert saved.trials_open is False
    assert (await GetPublicPageSettings(repo).execute("acad-new")).trials_open is False
