"""``GET /admin/students/{student_id}/coach-notes`` (People CRM A4, #665).

The family record's child drawer shows coach notes read-only. Run over the
real Mongo reader (mongomock) because the rules are storage rules: only
``visibility == "shared"`` notes, only the caller's academy, and a student of
another academy is a 404.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.composition.family_record import compose_admin_family_record
from backend.v2.interfaces.admin.router import router as admin_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers

ACADEMY_A = "academy-a"
ACADEMY_B = "academy-b"
T0 = datetime(2026, 9, 1, 15, 0, tzinfo=UTC)


def _note(academy_id: str, note_id: str, student_id: str, visibility: str | None, days: int):
    doc: dict[str, Any] = {
        "academy_id": academy_id,
        "note_id": note_id,
        "session_id": "sess-1",
        "student_id": student_id,
        "coach_id": "coach-1",
        "body": f"body {note_id}",
        "created_at": T0 + timedelta(days=days),
    }
    if visibility is not None:
        doc["visibility"] = visibility
    return doc


@pytest.fixture
def db() -> Any:
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["admin-student-coach-notes"]

    async def seed() -> None:
        await db["students"].insert_many(
            [
                {"academy_id": ACADEMY_A, "student_id": "stu-a", "full_name": "Kid Testone"},
                {"academy_id": ACADEMY_B, "student_id": "stu-b", "full_name": "Kid Testtwo"},
            ]
        )
        await db["sessions"].insert_one(
            {"academy_id": ACADEMY_A, "session_id": "sess-1", "title": "Sat Beginners"}
        )
        await db["users"].insert_one({"user_id": "coach-1", "full_name": "Coach Testperson"})
        await db["progress_notes"].insert_many(
            [
                _note(ACADEMY_A, "n-shared-old", "stu-a", "shared", 1),
                _note(ACADEMY_A, "n-shared-new", "stu-a", "shared", 3),
                _note(ACADEMY_A, "n-private", "stu-a", "private", 4),
                # Legacy note with no flag: private (#665, migration 0167).
                _note(ACADEMY_A, "n-legacy", "stu-a", None, 5),
                # Another academy's shared note about a same-id student.
                _note(ACADEMY_B, "n-other-tenant", "stu-a", "shared", 6),
                _note(ACADEMY_B, "n-b", "stu-b", "shared", 2),
            ]
        )

    asyncio.run(seed())
    return db


def _client(db: Any, roles: tuple[str, ...] = ("admin",)) -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(admin_router, prefix="/api/v2")
    app.dependency_overrides[get_auth_claims] = lambda: AuthClaims(
        user_id="u-admin",
        email="admin@example.test",
        academy_id=ACADEMY_A,
        roles=roles,  # type: ignore[arg-type]
    )
    app.state.admin_family_record = compose_admin_family_record(db)
    return TestClient(app)


def test_only_shared_notes_of_this_academy_newest_first(db: Any) -> None:
    with _client(db) as client:
        res = client.get("/api/v2/admin/students/stu-a/coach-notes")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["student_id"] == "stu-a"
    assert [n["note_id"] for n in body["notes"]] == ["n-shared-new", "n-shared-old"]
    first = body["notes"][0]
    assert first["coach_name"] == "Coach Testperson"
    assert first["session_title"] == "Sat Beginners"
    assert first["body"] == "body n-shared-new"
    assert "coach_id" not in first


def test_a_student_of_another_academy_is_404(db: Any) -> None:
    with _client(db) as client:
        assert client.get("/api/v2/admin/students/stu-b/coach-notes").status_code == 404
        assert client.get("/api/v2/admin/students/ghost/coach-notes").status_code == 404


@pytest.mark.parametrize("roles", [("coach",), ("parent",)])
def test_non_admin_personas_are_refused(db: Any, roles: tuple[str, ...]) -> None:
    with _client(db, roles) as client:
        assert client.get("/api/v2/admin/students/stu-a/coach-notes").status_code in {403, 404}
