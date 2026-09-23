"""Admin programs + per-class public fields over HTTP (public tenant page, Lane B1).

Real routes, real composition, real Mongo repositories on mongomock; the
tenant comes from a request middleware exactly as in production, never from
the body.
"""

from __future__ import annotations

import asyncio
import importlib
from datetime import UTC, datetime
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

_M0194 = importlib.import_module("backend.v2.migrations.0194_programs")

ACADEMY = "acad-riverside"
OTHER = "acad-lakeside"


@pytest.fixture
def db() -> Any:
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["admin-public-page"]

    async def seed() -> None:
        await _M0194.up(db)
        await db["sessions"].insert_many(
            [
                {"academy_id": ACADEMY, "session_id": "sess-juniors", "title": "Juniors"},
                {"academy_id": OTHER, "session_id": "sess-other", "title": "Adults"},
            ]
        )
        await db["programs"].insert_one(
            {
                "academy_id": OTHER,
                "program_id": "prog-other",
                "name": "Lakeside Squad",
                "sort_order": 0,
                "archived": False,
                "created_at": datetime(2026, 9, 1, tzinfo=UTC),
                "updated_at": datetime(2026, 9, 1, tzinfo=UTC),
            }
        )

    asyncio.run(seed())
    return db


def _client(db: Any, roles: tuple[str, ...] = ("admin",)) -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)

    @app.middleware("http")
    async def _tenant(request: Request, call_next: Any) -> Any:
        token = set_academy_id(ACADEMY)
        try:
            return await call_next(request)
        finally:
            _tenant_var.reset(token)  # type: ignore[arg-type]

    app.include_router(admin_router, prefix="/api/v2")
    app.dependency_overrides[get_auth_claims] = lambda: AuthClaims(
        user_id="u-admin",
        email="admin@example.test",
        academy_id=ACADEMY,
        roles=roles,  # type: ignore[arg-type]
    )
    app.state.admin_public_page = compose_admin_public_page(db)
    return TestClient(app)


BASE = "/api/v2/admin"


def test_program_crud_and_class_assignment_round_trip(db: Any) -> None:
    with _client(db) as client:
        res = client.post(
            f"{BASE}/programs",
            json={"name": "Juniors", "level": "Beginner", "age_band": {"min_age": 6, "max_age": 9}},
        )
        assert res.status_code == 201, res.text
        program = res.json()
        assert "academy_id" not in program
        assert program["age_band"] == {"min_age": 6, "max_age": 9}

        res = client.patch(
            f"{BASE}/programs/{program['program_id']}", json={"name": "Junior Squad"}
        )
        assert res.status_code == 200, res.text
        assert res.json()["name"] == "Junior Squad"
        assert res.json()["level"] == "Beginner"

        res = client.get(f"{BASE}/programs")
        assert [p["name"] for p in res.json()["programs"]] == ["Junior Squad"]

        res = client.put(
            f"{BASE}/sessions/sess-juniors/program", json={"program_id": program["program_id"]}
        )
        assert res.status_code == 200, res.text
        assert res.json()["program_id"] == program["program_id"]

        res = client.post(f"{BASE}/programs/{program['program_id']}/archive")
        assert res.status_code == 200 and res.json()["archived"] is True
        assert client.get(f"{BASE}/programs").json()["programs"] == []

        res = client.put(f"{BASE}/sessions/sess-juniors/program", json={"program_id": None})
        assert res.status_code == 200 and res.json()["program_id"] is None


def test_classes_are_private_by_default_and_switch_on_explicitly(db: Any) -> None:
    with _client(db) as client:
        res = client.get(f"{BASE}/class-public-profiles")
        assert res.status_code == 200, res.text
        assert res.json()["classes"] == [
            {
                "session_id": "sess-juniors",
                "title": "Juniors",
                "status": None,
                "program_id": None,
                "published": False,
                "price_period": None,
                "coach_display": "full_name",
                "public_description": None,
                "level": None,
                "age_band": None,
            }
        ]
        res = client.patch(
            f"{BASE}/sessions/sess-juniors/public-fields",
            json={"published": True, "coach_display": "hidden", "price_period": "class"},
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert (body["published"], body["coach_display"], body["price_period"]) == (
            True,
            "hidden",
            "class",
        )


@pytest.mark.parametrize(
    "body",
    [
        {"published": "true"},
        {"published": 1},
        {"price_period": "week"},
        {"coach_display": "initials"},
        {"program_id": "prog-x"},
        {"public_description": "x" * 501},
    ],
)
def test_bad_public_fields_are_422_and_nothing_is_written(db: Any, body: dict[str, Any]) -> None:
    with _client(db) as client:
        res = client.patch(f"{BASE}/sessions/sess-juniors/public-fields", json=body)
    assert res.status_code == 422, res.text
    row = asyncio.run(db["sessions"].find_one({"session_id": "sess-juniors"}))
    assert "published" not in row and "program_id" not in row


def test_another_academys_class_and_program_are_404(db: Any) -> None:
    with _client(db) as client:
        assert (
            client.patch(
                f"{BASE}/sessions/sess-other/public-fields", json={"published": True}
            ).status_code
            == 404
        )
        assert (
            client.put(
                f"{BASE}/sessions/sess-juniors/program", json={"program_id": "prog-other"}
            ).status_code
            == 404
        )
        assert client.patch(f"{BASE}/programs/prog-other", json={"name": "X"}).status_code == 404
        assert client.post(f"{BASE}/programs/prog-other/archive").status_code == 404
        listed = client.get(f"{BASE}/programs", params={"include_archived": True}).json()
        assert listed["programs"] == []
    other = asyncio.run(db["sessions"].find_one({"session_id": "sess-other"}))
    assert "published" not in other


def test_the_caller_cannot_pick_the_academy(db: Any) -> None:
    with _client(db) as client:
        res = client.post(f"{BASE}/programs", json={"name": "Juniors", "academy_id": OTHER})
    assert res.status_code == 422


@pytest.mark.parametrize("roles", [("coach",), ("parent",)])
def test_non_admin_personas_are_refused(db: Any, roles: tuple[str, ...]) -> None:
    with _client(db, roles) as client:
        assert client.get(f"{BASE}/programs").status_code in {403, 404}
        assert client.post(f"{BASE}/programs", json={"name": "X"}).status_code in {403, 404}
        assert client.get(f"{BASE}/class-public-profiles").status_code in {403, 404}
        assert client.patch(
            f"{BASE}/sessions/sess-juniors/public-fields", json={"published": True}
        ).status_code in {403, 404}
    row = asyncio.run(db["sessions"].find_one({"session_id": "sess-juniors"}))
    assert "published" not in row
