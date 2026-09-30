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
        "hero_photo_url": None,
        "about_text": "",
        "highlights": [],
        "gallery": [],
        "coach_profiles": [],
        "faqs": [],
        "theme": "floodlit",
        "seats_left_threshold": 3,
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


# --- landing-page content (Settings overhaul Phase 6, content lane) --------

from datetime import UTC, datetime

NOW = datetime(2026, 9, 30, 9, 0, tzinfo=UTC)
BASE = "https://cdn.example.test/"
FIREBASE_BASE = "https://firebasestorage.googleapis.com/v0/b/bkt/o/"


def _update(repo: Any, *args: Any, **kwargs: Any) -> UpdatePublicPageSettings:
    return UpdatePublicPageSettings(repo, *args, upload_url_base=BASE, **kwargs)


class _Roster:
    def __init__(self, *coach_ids: str) -> None:
        self.coach_ids_ = set(coach_ids)

    async def coach_ids(self, academy_id: str, candidate_ids: list[str]) -> set[str]:
        return {c for c in candidate_ids if c in self.coach_ids_}


def _photo(
    url: str = "https://cdn.example.test/academies/acad-riverside/gallery/a.jpg", **extra: Any
) -> dict[str, Any]:
    return {"url": url, "caption": "Saturday juniors", "consent_confirmed": True, **extra}


async def test_content_saves_and_defaults_are_todays_page() -> None:
    db, repo = await _repo()
    update = _update(repo, _Roster())
    saved = await update.execute(
        ACADEMY,
        {
            "hero_photo_url": "https://cdn.example.test/academies/acad-riverside/hero/h.jpg",
            "about_text": "  Est. 2019.  ",
            "highlights": ["Small groups", " All levels "],
            "faqs": [{"question": " Do I need a racket? ", "answer": "We lend one."}],
        },
    )
    assert saved.about_text == "Est. 2019."
    assert saved.highlights == ["Small groups", "All levels"]
    assert saved.faqs[0].question == "Do I need a racket?"
    row = await db["academies"].find_one({"academy_id": ACADEMY})
    assert row["public_page"]["faqs"] == [
        {"question": "Do I need a racket?", "answer": "We lend one."}
    ]
    cleared = await update.execute(ACADEMY, {"hero_photo_url": None, "faqs": []})
    assert cleared.hero_photo_url is None and cleared.faqs == []


@pytest.mark.parametrize(
    "fields",
    [
        {"hero_photo_url": "javascript:alert(1)"},
        {"hero_photo_url": "ftp://x.test/a.jpg"},
        {"about_text": "x" * 1201},
        {"highlights": ["a"] * 7},
        {"highlights": ["x" * 61]},
        {"highlights": [""]},
        {"faqs": [{"question": "q", "answer": "a"}] * 13},
        {"faqs": [{"question": "q" * 161, "answer": "a"}]},
        {"faqs": [{"question": "q", "answer": "a" * 801}]},
        {"faqs": [{"question": "", "answer": "a"}]},
        {"about_text": None},
    ],
)
async def test_content_validation_limits(fields: dict[str, Any]) -> None:
    _db, repo = await _repo()
    with pytest.raises(InvalidPublicPageSettings):
        await _update(repo, _Roster()).execute(ACADEMY, fields)


async def test_gallery_needs_consent_and_is_stamped_by_the_server() -> None:
    db, repo = await _repo()
    update = _update(repo, _Roster(), now=lambda: NOW)
    saved = await update.execute(
        ACADEMY,
        # A client-supplied stamp is ignored.
        {"gallery": [_photo(consent_confirmed_by="someone-else")]},
        actor_id="u-admin",
    )
    (photo,) = saved.gallery
    assert photo.consent_confirmed_by == "u-admin"
    assert photo.consent_confirmed_at == NOW
    stored = (await db["academies"].find_one({"academy_id": ACADEMY}))["public_page"]["gallery"]
    assert stored[0]["consent_confirmed_by"] == "u-admin"
    assert stored[0]["consent_confirmed"] is True

    for bad in (
        {"url": "https://cdn.example.test/academies/acad-riverside/gallery/b.jpg"},
        _photo(consent_confirmed=False),
    ):
        bad = {k: v for k, v in bad.items()}
        with pytest.raises(InvalidPublicPageSettings, match="parents or guardians"):
            await update.execute(ACADEMY, {"gallery": [photo.model_dump(), bad]}, actor_id="u2")
    with pytest.raises(InvalidPublicPageSettings):
        await update.execute(ACADEMY, {"gallery": [_photo(consent_confirmed="yes")]}, actor_id="u2")
    with pytest.raises(InvalidPublicPageSettings):
        await update.execute(ACADEMY, {"gallery": [_photo()] * 13}, actor_id="u2")
    with pytest.raises(InvalidPublicPageSettings):
        await update.execute(ACADEMY, {"gallery": [_photo(caption="c" * 121)]}, actor_id="u2")


async def test_resaving_a_gallery_keeps_the_original_consent_stamp() -> None:
    _db, repo = await _repo()
    first = _update(repo, _Roster(), now=lambda: NOW)
    await first.execute(ACADEMY, {"gallery": [_photo()]}, actor_id="u-owner")
    later = _update(repo, _Roster(), now=lambda: datetime(2027, 1, 1, tzinfo=UTC))
    saved = await later.execute(
        ACADEMY,
        {
            "gallery": [
                _photo(caption="New caption"),
                _photo("https://cdn.example.test/academies/acad-riverside/gallery/b.jpg"),
            ]
        },
        actor_id="u-admin",
    )
    old, new = saved.gallery
    assert (old.consent_confirmed_by, old.consent_confirmed_at) == ("u-owner", NOW)
    assert old.caption == "New caption"
    assert new.consent_confirmed_by == "u-admin"


async def test_coach_profiles_only_for_coaches_of_this_academy() -> None:
    _db, repo = await _repo()
    update = _update(repo, _Roster("coach-1", "coach-2"))
    saved = await update.execute(
        ACADEMY,
        {
            "coach_profiles": [
                {"coach_id": "coach-1", "bio": "Level 2 BWF", "photo_url": None},
                {"coach_id": "coach-2", "bio": "b" * 280, "shown": False},
            ]
        },
    )
    assert [p.shown for p in saved.coach_profiles] == [True, False]

    for bad in (
        [{"coach_id": "parent-9", "bio": ""}],
        [{"coach_id": "coach-1", "bio": ""}, {"coach_id": "coach-1", "bio": ""}],
        [{"coach_id": "coach-1", "bio": "b" * 281}],
        [{"coach_id": "coach-1", "bio": "", "shown": "no"}],
    ):
        with pytest.raises(InvalidPublicPageSettings):
            await update.execute(ACADEMY, {"coach_profiles": bad})
    with pytest.raises(InvalidPublicPageSettings):
        await _update(repo).execute(
            ACADEMY, {"coach_profiles": [{"coach_id": "coach-1", "bio": ""}]}
        )


async def test_a_bad_stored_content_key_falls_back_without_breaking_the_read() -> None:
    db, repo = await _repo()
    await db["academies"].update_one(
        {"academy_id": ACADEMY},
        {
            "$set": {
                "public_page": {"published": True, "gallery": [{"url": "x"}], "about_text": "Hi"}
            }
        },
    )
    settings = await GetPublicPageSettings(repo).execute(ACADEMY)
    assert settings.published is True and settings.about_text == "Hi"
    assert settings.gallery == []


@pytest.mark.parametrize(
    "fields",
    [
        {"hero_photo_url": "https://tracker.example.test/pixel.jpg"},
        # Another academy's object, and the wrong purpose folder.
        {"hero_photo_url": "https://cdn.example.test/academies/acad-other/hero/h.jpg"},
        {"hero_photo_url": "https://cdn.example.test/academies/acad-riverside/gallery/h.jpg"},
        {"gallery": [_photo("https://cdn.example.test/academies/acad-riverside/hero/h.jpg")]},
        {"gallery": [_photo("https://tracker.example.test/pixel.jpg")]},
        {
            "coach_profiles": [
                {
                    "coach_id": "coach-1",
                    "photo_url": "https://cdn.example.test/academies/acad-riverside/gallery/x.jpg",
                }
            ]
        },
    ],
)
async def test_photo_links_must_be_this_academys_own_uploads(fields: dict[str, Any]) -> None:
    _db, repo = await _repo()
    with pytest.raises(InvalidPublicPageSettings):
        await _update(repo, _Roster("coach-1")).execute(ACADEMY, fields, actor_id="u-admin")


async def test_owned_photo_links_are_accepted_including_firebase_encoded_paths() -> None:
    _db, repo = await _repo()
    encoded = f"{FIREBASE_BASE}academies%2Facad-riverside%2Fcoach%2Fc.jpg?alt=media&token=abc-123"
    saved = await UpdatePublicPageSettings(
        repo, _Roster("coach-1"), upload_url_base=FIREBASE_BASE
    ).execute(ACADEMY, {"coach_profiles": [{"coach_id": "coach-1", "photo_url": encoded}]})
    assert saved.coach_profiles[0].photo_url == encoded


_G = "academies/acad-riverside/gallery"


@pytest.mark.parametrize(
    "url",
    [
        # Other host carrying the marker in its path (the original forgery).
        f"https://evil.example/x/{_G}/a.jpg",
        f"https://evil.example/{_G}/a.jpg",
        # Right host, marker behind a prefix.
        f"{BASE}x/{_G}/a.jpg",
        # Plain and encoded traversal.
        f"{BASE}{_G}/../../other/gallery/a.jpg",
        f"{BASE}{_G}/%2e%2e/%2e%2e/other/gallery/a.jpg",
        f"{BASE}academies%2Facad-riverside%2Fgallery%2F..%2F..%2Fother%2Fgallery%2Fa.jpg",
        f"{BASE}{_G}/..",
        # Extra segments, encoded slash inside the file name, backslash.
        f"{BASE}{_G}/sub/a.jpg",
        f"{BASE}{_G}/sub%2Fa.jpg",
        f"{BASE}{_G}/a%5Cb.jpg",
        f"{BASE}{_G}/a\\b.jpg",
        # Wrong scheme, credentials trick, wrong academy, wrong purpose.
        f"http://cdn.example.test/{_G}/a.jpg",
        f"https://cdn.example.test@evil.example/{_G}/a.jpg",
        f"{BASE}academies/acad-other/gallery/a.jpg",
        f"{BASE}academies/acad-riverside/hero/a.jpg",
        # Marker only in the query or fragment.
        f"{BASE}other/a.jpg?x=/{_G}/a.jpg",
        f"{BASE}other/a.jpg#/{_G}/a.jpg",
    ],
)
async def test_forged_or_traversing_photo_links_are_refused(url: str) -> None:
    _db, repo = await _repo()
    with pytest.raises(InvalidPublicPageSettings):
        await _update(repo).execute(ACADEMY, {"gallery": [_photo(url)]}, actor_id="u-admin")


async def test_a_genuine_store_url_with_query_is_accepted() -> None:
    _db, repo = await _repo()
    url = f"{FIREBASE_BASE}academies%2Facad-riverside%2Fgallery%2Fa.jpg?alt=media&token=t"
    saved = await UpdatePublicPageSettings(repo, upload_url_base=FIREBASE_BASE).execute(
        ACADEMY, {"gallery": [_photo(url)]}, actor_id="u-admin"
    )
    assert saved.gallery[0].url == url


async def test_another_bucket_on_the_same_firebase_host_is_refused() -> None:
    _db, repo = await _repo()
    url = "https://firebasestorage.googleapis.com/v0/b/other/o/academies%2Facad-riverside%2Fgallery%2Fa.jpg"
    with pytest.raises(InvalidPublicPageSettings):
        await UpdatePublicPageSettings(repo, upload_url_base=FIREBASE_BASE).execute(
            ACADEMY, {"gallery": [_photo(url)]}, actor_id="u-admin"
        )


async def test_without_a_media_store_new_photo_urls_are_refused() -> None:
    _db, repo = await _repo()
    with pytest.raises(InvalidPublicPageSettings):
        await UpdatePublicPageSettings(repo).execute(
            ACADEMY, {"hero_photo_url": f"{BASE}academies/acad-riverside/hero/h.jpg"}
        )


async def test_an_already_saved_url_is_still_accepted_without_a_store() -> None:
    db, repo = await _repo()
    legacy = "https://legacy.example/old.jpg"
    await db["academies"].update_one(
        {"academy_id": ACADEMY}, {"$set": {"public_page": {"hero_photo_url": legacy}}}, upsert=True
    )
    saved = await UpdatePublicPageSettings(repo).execute(
        ACADEMY, {"hero_photo_url": legacy, "about_text": "Hi"}
    )
    assert saved.hero_photo_url == legacy


async def test_gallery_write_without_an_actor_is_refused() -> None:
    _db, repo = await _repo()
    with pytest.raises(ValueError, match="actor_id"):
        await _update(repo, _Roster()).execute(ACADEMY, {"gallery": [_photo()]})


def test_default_seat_threshold_matches_the_catalog_band() -> None:
    from backend.v2.contexts.enrollment.domain.public_catalog import FEW_SEATS_THRESHOLD
    from backend.v2.contexts.identity.domain.public_page import (
        DEFAULT_SEATS_LEFT_THRESHOLD,
        PublicPageSettings,
    )

    assert DEFAULT_SEATS_LEFT_THRESHOLD == FEW_SEATS_THRESHOLD
    assert PublicPageSettings().seats_left_threshold == FEW_SEATS_THRESHOLD


def test_a_bad_stored_theme_or_threshold_falls_back_to_the_default() -> None:
    from backend.v2.contexts.identity.domain.public_page import PublicPageSettings

    settings = PublicPageSettings.from_stored(
        {"theme": "neon", "seats_left_threshold": 99, "published": True}
    )
    assert settings.theme == "floodlit"
    assert settings.seats_left_threshold == 3
    assert settings.published is True


def test_seat_band_honours_the_academy_threshold() -> None:
    from backend.v2.contexts.enrollment.domain.public_catalog import seat_band

    assert seat_band(10, 8) == ("few", 2)  # default 3: today
    assert seat_band(10, 6) == ("open", None)
    assert seat_band(10, 6, 5) == ("few", 4)
    assert seat_band(10, 8, 0) == ("open", None)  # 0 hides "only N left"
    assert seat_band(10, 10, 0) == ("waitlist", None)  # full is never hidden
