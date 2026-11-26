"""``GET /admin/today`` and ``GET /admin/today/roster-health`` (S63, D-20, D-14).

Over the real Mongo readers (mongomock) with a fixed clock: phases and counts
are server facts, and the tenant boundary is a storage rule.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.v2.composition.admin_today import AdminToday, AdminTodayReader
from backend.v2.composition.coach_roster_health import compose_coach_roster_health
from backend.v2.interfaces.admin.router import router as admin_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers
from backend.v2.shared.profile.completeness import MEDICAL_NONE_SENTINEL
from backend.v2.shared.tenancy.context import _current as _tenant_var
from backend.v2.shared.tenancy.context import set_academy_id

ACADEMY = "academy-a"
OTHER = "academy-b"
TZ = "America/Chicago"
# Thu Nov 26 2026, 4:45 PM in Chicago (UTC-6).
NOW = datetime(2026, 11, 26, 22, 45, tzinfo=UTC)


def _at(day: int, hour: int, minute: int = 0) -> datetime:
    """Chicago wall time on Nov ``day`` 2026 as UTC."""
    return datetime(2026, 11, day, minute=minute, tzinfo=UTC) + timedelta(hours=hour + 6)


def _session(academy: str, sid: str, title: str, coach: str) -> dict[str, Any]:
    return {
        "academy_id": academy,
        "session_id": sid,
        "title": title,
        "location": "Court 1",
        "coach_id": coach,
        "timezone": TZ,
        "start_at": _at(1, 9),
        "end_at": _at(1, 10),
        "capacity": 12,
        "status": "scheduled",
    }


def _occ(academy: str, oid: str, sid: str, start: datetime, end: datetime, **extra: Any):
    return {
        "academy_id": academy,
        "occurrence_id": oid,
        "session_id": sid,
        "start_at": start,
        "end_at": end,
        "status": "scheduled",
        "scheduled_coach_id": extra.pop("coach", "coach-demo"),
        **extra,
    }


@pytest.fixture
def db() -> Any:
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["admin-today"]

    async def seed() -> None:
        await db["academies"].insert_many(
            [{"academy_id": ACADEMY, "timezone": TZ}, {"academy_id": OTHER, "timezone": TZ}]
        )
        await db["sessions"].insert_many(
            [
                _session(ACADEMY, "sess-jb", "Junior Beginners", "coach-demo"),
                _session(ACADEMY, "sess-ti", "Tuesday Intermediate", "coach-casey"),
                _session(ACADEMY, "sess-as", "Adult Social", "coach-demo"),
                _session(ACADEMY, "sess-late", "Evening Squad", "coach-demo"),
                _session(OTHER, "sess-b", "Other Academy Class", "coach-b"),
            ]
        )
        await db["session_occurrences"].insert_many(
            [
                _occ(ACADEMY, "occ-jb", "sess-jb", _at(26, 16, 30), _at(26, 17, 30)),
                _occ(
                    ACADEMY,
                    "occ-ti",
                    "sess-ti",
                    _at(26, 17, 10),
                    _at(26, 18, 10),
                    coach="coach-casey",
                    substitute_coach_id="coach-cover",
                ),
                _occ(
                    ACADEMY,
                    "occ-as",
                    "sess-as",
                    _at(26, 19),
                    _at(26, 20),
                    status="cancelled",
                    cancellation_reason="Gym flooded",
                ),
                _occ(ACADEMY, "occ-late", "sess-late", _at(26, 20), _at(26, 21)),
                _occ(ACADEMY, "occ-done", "sess-jb", _at(26, 9), _at(26, 10)),
                _occ(ACADEMY, "occ-tomorrow-2", "sess-ti", _at(27, 11), _at(27, 12)),
                _occ(ACADEMY, "occ-tomorrow-1", "sess-jb", _at(27, 9), _at(27, 10)),
                _occ(OTHER, "occ-b", "sess-b", _at(26, 16, 30), _at(26, 17, 30)),
            ]
        )
        await db["enrollments"].insert_many(
            [
                {
                    "academy_id": ACADEMY,
                    "enrollment_id": f"enr-{sid}",
                    "session_id": "sess-jb",
                    "student_id": sid,
                    "status": "active",
                }
                for sid in ("stu-sam", "stu-alex", "stu-dev")
            ]
        )
        await db["students"].insert_many(
            [
                {
                    "academy_id": ACADEMY,
                    "student_id": "stu-sam",
                    "full_name": "Sam Demo",
                    "parent_id": "par-demo",
                    "medical_notes": "Peanut allergy, carries EpiPen",
                    "emergency_contact_name": "Rosa Demo",
                    "emergency_contact_phone": "(309) 555-0177",
                },
                {
                    "academy_id": ACADEMY,
                    "student_id": "stu-alex",
                    "full_name": "Alex Demo",
                    "parent_id": "par-demo",
                    "medical_notes": MEDICAL_NONE_SENTINEL,
                },
                {
                    "academy_id": ACADEMY,
                    "student_id": "stu-dev",
                    "full_name": "Dev Patel",
                    "parent_id": "par-patel",
                },
            ]
        )
        await db["attendance"].insert_many(
            [
                {
                    "academy_id": ACADEMY,
                    "attendance_id": f"att-{sid}",
                    "occurrence_id": "occ-jb",
                    "session_id": "sess-jb",
                    "student_id": sid,
                    "marked_by": "coach-demo",
                    "marked_at": _at(26, 16, 35),
                    "status": status,
                }
                for sid, status in (("stu-sam", "absent"), ("stu-alex", "late"))
            ]
        )
        await db["users"].insert_many(
            [
                {"user_id": "par-demo", "display_name": "Demo Parent", "phone": "(309) 555-0120"},
                {"user_id": "par-patel", "display_name": "Asha Patel"},
                {"user_id": "coach-demo", "display_name": "Coach Demo"},
                {"user_id": "coach-casey", "display_name": "Coach Casey"},
                {"user_id": "coach-cover", "display_name": "Coach Cover"},
            ]
        )

    asyncio.run(seed())
    return db


def _client(db: Any, roles: tuple[str, ...] = ("admin",), academy: str = ACADEMY) -> TestClient:
    app = FastAPI()

    @app.middleware("http")
    async def _tenant(request: Request, call_next: Any) -> Any:
        token = set_academy_id(academy)
        try:
            return await call_next(request)
        finally:
            _tenant_var.reset(token)

    register_exception_handlers(app)
    app.include_router(admin_router, prefix="/api/v2")
    app.dependency_overrides[get_auth_claims] = lambda: AuthClaims(
        user_id="u-admin",
        email="admin@example.com",
        academy_id=academy,
        roles=roles,  # type: ignore[arg-type]
    )
    app.state.admin_today = AdminTodayReader(
        db=db, health=compose_coach_roster_health(db), clock=lambda: NOW
    )
    return TestClient(app)


def test_today_lists_classes_in_order_with_server_phases(db: Any) -> None:
    with _client(db) as client:
        res = client.get("/api/v2/admin/today")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["date"] == "2026-11-26"
    assert body["timezone"] == TZ
    phases = [(c["occurrence_id"], c["phase"], c["starts_in_minutes"]) for c in body["classes"]]
    assert phases == [
        ("occ-done", "finished", None),
        ("occ-jb", "now", None),
        ("occ-ti", "next", 25),
        ("occ-as", "cancelled", None),
        ("occ-late", "later", None),
    ]
    assert body["tomorrow"] == {"class_count": 2, "first_start_at": "2026-11-27T15:00:00Z"}
    assert body["messages_waiting"] == 0
    assert body["health_enabled"] is True


def test_roster_has_parent_phone_attendance_and_counts(db: Any) -> None:
    with _client(db) as client:
        body = client.get("/api/v2/admin/today").json()
    jb = next(c for c in body["classes"] if c["occurrence_id"] == "occ-jb")
    assert jb["coach_name"] == "Coach Demo"
    assert (jb["enrolled_count"], jb["here_count"], jb["absent_count"], jb["marked_count"]) == (
        3,
        1,
        1,
        2,
    )
    # Sorted by name; parent phone on the row; no phone stays null.
    assert [r["full_name"] for r in jb["roster"]] == ["Alex Demo", "Dev Patel", "Sam Demo"]
    sam = jb["roster"][2]
    assert sam["attendance"] == "absent"
    assert sam["parent_name"] == "Demo Parent"
    assert sam["parent_phone"] == "(309) 555-0120"
    assert jb["roster"][1]["parent_phone"] is None
    assert jb["roster"][1]["attendance"] is None
    ti = next(c for c in body["classes"] if c["occurrence_id"] == "occ-ti")
    assert ti["coach_name"] == "Coach Casey"
    assert ti["cover_coach_name"] == "Coach Cover"
    assert ti["roster"] == []


def test_today_payload_has_no_health_field(db: Any) -> None:
    """The Today read is refetched and cached in the query client; health is not."""
    with _client(db) as client:
        raw = client.get("/api/v2/admin/today").text
    assert "Peanut" not in raw and "Rosa Demo" not in raw and "555-0177" not in raw
    schema = AdminToday.model_json_schema()
    names = {
        name
        for definition in [schema, *schema.get("$defs", {}).values()]
        for name in definition.get("properties", {})
    }
    assert not [n for n in names if any(b in n for b in ("medical", "emergency", "allerg"))]


def test_roster_health_is_no_store_with_three_answers(db: Any) -> None:
    with _client(db) as client:
        res = client.get("/api/v2/admin/today/roster-health?occurrence_id=occ-jb")
    assert res.status_code == 200, res.text
    assert res.headers["cache-control"] == "no-store"
    body = res.json()
    assert body["declared_count"] == 1
    by_id = {c["student_id"]: c for c in body["children"]}
    assert by_id["stu-sam"]["note"] == "Peanut allergy, carries EpiPen"
    assert by_id["stu-sam"]["emergency_contact_name"] == "Rosa Demo"
    assert by_id["stu-alex"]["status"] == "none_declared"
    assert by_id["stu-dev"]["status"] == "not_answered"
    assert "parent_phone" not in by_id["stu-sam"]


def test_another_academy_sees_none_of_this_academys_classes(db: Any) -> None:
    with _client(db, academy=OTHER) as client:
        body = client.get("/api/v2/admin/today").json()
        assert [c["occurrence_id"] for c in body["classes"]] == ["occ-b"]
        res = client.get("/api/v2/admin/today/roster-health?occurrence_id=occ-jb")
        assert res.status_code == 404


@pytest.mark.parametrize("roles", [("coach",), ("parent",), ("front_desk",)])
def test_non_admin_personas_get_404(db: Any, roles: tuple[str, ...]) -> None:
    with _client(db, roles) as client:
        assert client.get("/api/v2/admin/today").status_code == 404
        assert (
            client.get("/api/v2/admin/today/roster-health?occurrence_id=occ-jb").status_code == 404
        )
