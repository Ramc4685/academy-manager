"""Admin academy public-page settings over HTTP (public tenant page, Lane B5).

Real routes, real composition, real Mongo academy repository on mongomock.
The academy is the caller's claim, never the body; another academy's
``public_page`` is never read or written.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.v2.composition.public_page_admin import compose_admin_public_page
from backend.v2.interfaces.admin.router import router as admin_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers
from backend.v2.shared.tenancy.context import _current as _tenant_var
from backend.v2.shared.tenancy.context import set_academy_id

ACADEMY = "acad-riverside"
OTHER = "acad-lakeside"
URL = "/api/v2/admin/academy/public-page"

DEFAULTS = {
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
    "public_url": None,
}


@pytest.fixture
def db() -> Any:
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["admin-public-page-settings"]

    async def seed() -> None:
        await db["academies"].insert_many(
            [
                {"academy_id": ACADEMY, "name": "Riverside Shuttle Club"},
                {
                    "academy_id": OTHER,
                    "name": "Lakeside Racquet Club",
                    "primary_domain": "Lakeside.Example.",
                    "public_page": {"published": True, "price_period_default": "term"},
                },
            ]
        )

    asyncio.run(seed())
    return db


def _client(db: Any, roles: tuple[str, ...] = ("admin",), academy: str = ACADEMY) -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)

    @app.middleware("http")
    async def _tenant(request: Request, call_next: Any) -> Any:
        token = set_academy_id(academy)
        try:
            return await call_next(request)
        finally:
            _tenant_var.reset(token)  # type: ignore[arg-type]

    app.include_router(admin_router, prefix="/api/v2")
    app.dependency_overrides[get_auth_claims] = lambda: AuthClaims(
        user_id="u-admin",
        email="admin@example.test",
        academy_id=academy,
        roles=roles,  # type: ignore[arg-type]
    )
    app.state.admin_public_page = compose_admin_public_page(
        db, media_url_base="https://cdn.example.test/"
    )
    return TestClient(app)


def _stored(db: Any, academy: str) -> dict[str, Any] | None:
    row = asyncio.run(db["academies"].find_one({"academy_id": academy}))
    return None if row is None else row.get("public_page")


def test_a_fresh_academy_reads_the_domain_defaults(db: Any) -> None:
    with _client(db) as client:
        res = client.get(URL)
    assert res.status_code == 200, res.text
    assert res.json() == DEFAULTS
    # Reading never writes: no backfill for the live academy.
    assert _stored(db, ACADEMY) is None


def test_patch_changes_only_the_keys_sent(db: Any) -> None:
    with _client(db) as client:
        res = client.patch(URL, json={"published": True})
        assert res.status_code == 200, res.text
        assert res.json() == {**DEFAULTS, "published": True}

        res = client.patch(
            URL,
            json={
                "price_period_default": "class",
                "privacy_notice_url": "https://riverside.example/privacy",
            },
        )
        assert res.status_code == 200, res.text
        assert res.json() == {
            **DEFAULTS,
            "published": True,
            "price_period_default": "class",
            "privacy_notice_url": "https://riverside.example/privacy",
        }
        assert client.get(URL).json() == res.json()

        res = client.patch(URL, json={"privacy_notice_url": None})
        assert res.status_code == 200 and res.json()["privacy_notice_url"] is None
    stored = _stored(db, ACADEMY)
    assert stored is not None and stored["published"] is True
    # Only the dotted keys sent were written; nothing else was materialised.
    assert "show_price" not in stored and "trials_open" not in stored


@pytest.mark.parametrize(
    "body",
    [
        {"published": "true"},
        {"published": 1},
        {"published": None},
        {"trials_open": "no"},
        {"price_period_default": "week"},
        {"price_period_default": None},
        {"privacy_notice_url": "javascript:alert(1)"},
        {"privacy_notice_url": "data:text/html,hi"},
        {"academy_id": OTHER},
        {"theme": "dark"},
        {"public_url": "https://evil.example/"},
    ],
)
def test_bad_settings_are_422_and_nothing_is_written(db: Any, body: dict[str, Any]) -> None:
    with _client(db) as client:
        res = client.patch(URL, json=body)
    assert res.status_code == 422, res.text
    assert _stored(db, ACADEMY) is None
    assert _stored(db, OTHER) == {"published": True, "price_period_default": "term"}


def test_one_academy_never_reads_or_writes_another(db: Any) -> None:
    with _client(db) as client:
        assert client.get(URL).json() == DEFAULTS
        assert client.patch(URL, json={"trials_open": False}).status_code == 200
    assert _stored(db, OTHER) == {"published": True, "price_period_default": "term"}
    with _client(db, academy=OTHER) as client:
        body = client.get(URL).json()
    assert body == {
        **DEFAULTS,
        "published": True,
        "price_period_default": "term",
        "public_url": "https://lakeside.example/",
    }


@pytest.mark.parametrize("roles", [("coach",), ("parent",)])
def test_non_admin_personas_are_refused(db: Any, roles: tuple[str, ...]) -> None:
    with _client(db, roles) as client:
        assert client.get(URL).status_code == 404
        assert client.patch(URL, json={"published": True}).status_code == 404
    assert _stored(db, ACADEMY) is None


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        ({"primary_domain": "riverside.example"}, "https://riverside.example/"),
        ({"custom_domain": "www.riverside.example"}, "https://www.riverside.example/"),
        ({"primary_domain": "https://riverside.example/"}, "https://riverside.example/"),
        ({"primary_domain": "HTTPS://Riverside.Example"}, "https://riverside.example/"),
        ({"primary_domain": "http://riverside.example/"}, "https://riverside.example/"),
        ({"primary_domain": "https://riverside.example/privacy"}, None),
        ({"primary_domain": "https://riverside.example:8443/"}, None),
        ({"primary_domain": "ftp://riverside.example/"}, None),
        ({"primary_domain": "javascript:alert(1)"}, None),
        ({"primary_domain": "riverside.example/path"}, None),
        ({"primary_domain": "user@riverside.example"}, None),
        ({"primary_domain": "localhost"}, None),
    ],
)
def test_view_page_address_is_a_host_or_site_root_url_or_nothing(
    db: Any, stored: dict[str, Any], expected: str | None
) -> None:
    asyncio.run(db["academies"].update_one({"academy_id": ACADEMY}, {"$set": stored}))
    with _client(db) as client:
        assert client.get(URL).json()["public_url"] == expected


# --- landing-page content (content lane) -----------------------------------


def _seed_staff(db: Any) -> None:
    async def go() -> None:
        await db["users"].insert_many(
            [
                {"user_id": "coach-1", "display_name": "Alex Morgan"},
                {"user_id": "coach-away", "display_name": "Other Academy Coach"},
                {"user_id": "parent-1", "display_name": "A Parent"},
                {"user_id": "coach-gone", "display_name": "Left Coach"},
            ]
        )
        await db["academy_memberships"].insert_many(
            [
                {
                    "academy_id": ACADEMY,
                    "user_id": "coach-1",
                    "roles": ["coach"],
                    "status": "active",
                },
                {"academy_id": OTHER, "user_id": "coach-away", "roles": ["coach"]},
                {"academy_id": ACADEMY, "user_id": "parent-1", "roles": ["parent"]},
                {
                    "academy_id": ACADEMY,
                    "user_id": "coach-gone",
                    "roles": ["coach"],
                    "status": "removed",
                },
            ]
        )

    asyncio.run(go())


@pytest.mark.parametrize("roles", [("admin",), ("owner", "admin")])
def test_owner_and_plain_admin_can_save_page_content(db: Any, roles: tuple[str, ...]) -> None:
    _seed_staff(db)
    with _client(db, roles=roles) as client:
        res = client.patch(
            URL,
            json={
                "hero_photo_url": "https://cdn.example.test/academies/acad-riverside/hero/h.jpg",
                "about_text": "Est. 2019",
                "highlights": ["Small groups"],
                "faqs": [{"question": "Cost?", "answer": "See classes."}],
                "gallery": [
                    {
                        "url": "https://cdn.example.test/academies/acad-riverside/gallery/g1.jpg",
                        "caption": "Sat",
                        "consent_confirmed": True,
                    }
                ],
                "coach_profiles": [{"coach_id": "coach-1", "bio": "L2 BWF"}],
            },
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["about_text"] == "Est. 2019"
        # Admin view shows consent as a flag, never who confirmed or when.
        assert body["gallery"] == [
            {
                "url": "https://cdn.example.test/academies/acad-riverside/gallery/g1.jpg",
                "caption": "Sat",
                "consent_confirmed": True,
            }
        ]
        assert body["coach_profiles"] == [
            {"coach_id": "coach-1", "photo_url": None, "bio": "L2 BWF", "shown": True}
        ]
    stored = _stored(db, ACADEMY)
    assert stored is not None
    assert stored["gallery"][0]["consent_confirmed_by"] == "u-admin"
    assert stored["gallery"][0]["consent_confirmed_at"] is not None


def test_gallery_item_without_consent_is_422(db: Any) -> None:
    with _client(db) as client:
        for item in (
            {"url": "https://cdn.example.test/academies/acad-riverside/gallery/g.jpg"},
            {
                "url": "https://cdn.example.test/academies/acad-riverside/gallery/g.jpg",
                "consent_confirmed": False,
            },
        ):
            res = client.patch(URL, json={"gallery": [item]})
            assert res.status_code == 422, res.text
    assert _stored(db, ACADEMY) is None


def test_gallery_rejects_client_supplied_consent_stamps(db: Any) -> None:
    with _client(db) as client:
        res = client.patch(
            URL,
            json={
                "gallery": [
                    {
                        "url": "https://cdn.example.test/academies/acad-riverside/gallery/g.jpg",
                        "consent_confirmed": True,
                        "consent_confirmed_by": "someone-else",
                    }
                ]
            },
        )
    assert res.status_code == 422


def test_coach_profile_for_a_non_coach_or_another_academys_coach_is_422(db: Any) -> None:
    _seed_staff(db)
    with _client(db) as client:
        for coach_id in ("parent-1", "coach-away", "coach-gone", "nobody"):
            res = client.patch(URL, json={"coach_profiles": [{"coach_id": coach_id, "bio": "x"}]})
            assert res.status_code == 422, (coach_id, res.text)
    assert _stored(db, ACADEMY) is None


def test_content_limits_are_422(db: Any) -> None:
    with _client(db) as client:
        for body in (
            {"about_text": "x" * 1201},
            {"highlights": ["a"] * 7},
            {"faqs": [{"question": "q", "answer": "a"}] * 13},
            {"hero_photo_url": "javascript:alert(1)"},
            {"coach_profiles": [{"coach_id": "coach-1", "bio": "b" * 281}]},
        ):
            assert client.patch(URL, json=body).status_code == 422, body


def test_forged_photo_links_are_422_over_http(db: Any) -> None:
    with _client(db) as client:
        for url in (
            "https://evil.example/x/academies/acad-riverside/hero/h.jpg",
            "https://cdn.example.test/x/academies/acad-riverside/hero/h.jpg",
            "https://cdn.example.test/academies/acad-riverside/hero/../../other/hero/h.jpg",
        ):
            res = client.patch(URL, json={"hero_photo_url": url})
            assert res.status_code == 422, (url, res.text)
    assert _stored(db, ACADEMY) is None
