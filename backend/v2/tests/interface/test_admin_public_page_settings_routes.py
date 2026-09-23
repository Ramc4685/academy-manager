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
    app.state.admin_public_page = compose_admin_public_page(db)
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
        ({"primary_domain": "javascript:alert(1)"}, None),
        ({"primary_domain": "riverside.example/path"}, None),
        ({"primary_domain": "user@riverside.example"}, None),
        ({"primary_domain": "localhost"}, None),
    ],
)
def test_view_page_address_is_a_bare_host_or_nothing(
    db: Any, stored: dict[str, Any], expected: str | None
) -> None:
    asyncio.run(db["academies"].update_one({"academy_id": ACADEMY}, {"$set": stored}))
    with _client(db) as client:
        assert client.get(URL).json()["public_url"] == expected
