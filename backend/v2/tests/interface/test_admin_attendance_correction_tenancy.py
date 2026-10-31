"""Admin attendance correction from the family record drawer (People CRM A4).

``PATCH /api/v2/admin/session-occurrences/{occurrence_id}/attendance/{student_id}``
(#517) is the admin correction route the family record's child drawer calls.
These tests run it over the REAL tenant-scoped ``MongoAttendanceRepository``
(mongomock) rather than a fake, because the properties that matter are
storage properties:

* an occurrence or student that belongs to another academy is a 404, and the
  other academy's row is untouched;
* the audit trail (actor, previous status, reason, time) is persisted on the
  tenant's own row and the outbox event carries the tenant and ``actor_role``;
* the coach 24h window does not apply to an admin.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.v2.contexts.coaching.application.use_cases.correct_attendance import (
    CorrectAttendance,
)
from backend.v2.contexts.coaching.infrastructure.mongo_attendance_repo import (
    MongoAttendanceRepository,
)
from backend.v2.interfaces.admin.router import router as admin_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers
from backend.v2.shared.tenancy.context import tenant_scope

ACADEMY_A = "academy-a"
ACADEMY_B = "academy-b"
NOW = datetime(2026, 9, 23, 15, 0, tzinfo=UTC)
PATH = "/api/v2/admin/session-occurrences/{occ}/attendance/{student}"


class RecordingOutbox:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def append(self, event: Any, **_: Any) -> None:
        self.events.append(event)


class NoOccurrences:
    """Admins never consult the occurrence lookup (no assignment check)."""

    async def get(self, occurrence_id: str) -> None:
        raise AssertionError("admin correction must not check coach assignment")


def _mark(academy_id: str, occurrence_id: str, student_id: str) -> dict[str, Any]:
    return {
        "academy_id": academy_id,
        "attendance_id": f"att-{occurrence_id}-{student_id}",
        "occurrence_id": occurrence_id,
        "session_id": "sess-1",
        "student_id": student_id,
        "marked_by": "coach-1",
        # A week old: far outside the coach's 24h window.
        "marked_at": NOW - timedelta(days=7),
        "status": "present",
        "client_app_version": "test",
    }


@pytest.fixture
def db() -> Any:
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["admin-attendance-correction-tenancy"]
    asyncio.run(
        db["attendance"].insert_many(
            [
                _mark(ACADEMY_A, "occ-a", "stu-a"),
                _mark(ACADEMY_B, "occ-b", "stu-b"),
                # Same ids in both academies: only academy A's row may change.
                _mark(ACADEMY_B, "occ-a", "stu-a"),
            ]
        )
    )
    return db


def _find(db: Any, query: dict[str, Any]) -> dict[str, Any] | None:
    return asyncio.run(db["attendance"].find_one(query))


def _client(db: Any, *, roles: tuple[str, ...], outbox: RecordingOutbox) -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)

    @app.middleware("http")
    async def _tenant(request: Request, call_next: Any) -> Any:
        with tenant_scope(ACADEMY_A):
            return await call_next(request)

    app.include_router(admin_router, prefix="/api/v2")
    app.dependency_overrides[get_auth_claims] = lambda: AuthClaims(
        user_id="u-admin-a",
        email="admin@example.test",
        academy_id=ACADEMY_A,
        roles=roles,  # type: ignore[arg-type]
    )
    app.state.admin = SimpleNamespace(
        correct_attendance=CorrectAttendance(
            attendance_repo=MongoAttendanceRepository(db),
            occurrence_lookup=NoOccurrences(),  # type: ignore[arg-type]
            outbox=outbox,  # type: ignore[arg-type]
            academy_id=lambda: ACADEMY_A,
            clock=lambda: NOW,
        )
    )
    return TestClient(app)


def test_admin_corrects_outside_the_coach_window_and_the_audit_trail_is_persisted(
    db: Any,
) -> None:
    outbox = RecordingOutbox()
    with _client(db, roles=("admin",), outbox=outbox) as client:
        r = client.patch(
            PATH.format(occ="occ-a", student="stu-a"),
            json={"status": "absent", "reason": "parent reported a no-show"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "absent"
    assert body["previous_status"] == "present"
    assert body["corrected_by"] == "u-admin-a"

    row = _find(db, {"academy_id": ACADEMY_A, "attendance_id": "att-occ-a-stu-a"})
    assert row is not None
    assert row["status"] == "absent"
    assert row["previous_status"] == "present"
    assert row["corrected_by"] == "u-admin-a"
    assert row["correction_reason"] == "parent reported a no-show"
    assert row["corrected_at"] is not None

    [event] = outbox.events
    assert event.name == "Coaching.AttendanceCorrected"
    assert event.academy_id == ACADEMY_A
    assert event.payload.actor_role == "admin"
    assert event.payload.previous_status == "present"
    assert event.payload.corrected_by == "u-admin-a"

    # The other academy's row with the same ids is untouched.
    other = _find(db, {"academy_id": ACADEMY_B, "occurrence_id": "occ-a"})
    assert other is not None
    assert other["status"] == "present"
    assert "corrected_by" not in other


def test_an_occurrence_and_student_from_another_academy_is_404(db: Any) -> None:
    outbox = RecordingOutbox()
    with _client(db, roles=("admin",), outbox=outbox) as client:
        r = client.patch(PATH.format(occ="occ-b", student="stu-b"), json={"status": "absent"})
    assert r.status_code == 404, r.text
    assert r.json()["error"]["code"] == "Coaching.AttendanceNotFound"
    assert outbox.events == []
    row = _find(db, {"academy_id": ACADEMY_B, "occurrence_id": "occ-b"})
    assert row is not None and row["status"] == "present"


def test_a_student_from_another_academy_on_our_occurrence_is_404(db: Any) -> None:
    outbox = RecordingOutbox()
    with _client(db, roles=("admin",), outbox=outbox) as client:
        r = client.patch(PATH.format(occ="occ-a", student="stu-b"), json={"status": "late"})
    assert r.status_code == 404, r.text
    assert outbox.events == []


def test_a_coach_cannot_use_the_admin_correction_route(db: Any) -> None:
    outbox = RecordingOutbox()
    with _client(db, roles=("coach",), outbox=outbox) as client:
        r = client.patch(PATH.format(occ="occ-a", student="stu-a"), json={"status": "absent"})
    assert r.status_code in {403, 404}, r.text
    assert outbox.events == []
    row = _find(db, {"academy_id": ACADEMY_A, "attendance_id": "att-occ-a-stu-a"})
    assert row is not None and row["status"] == "present"
