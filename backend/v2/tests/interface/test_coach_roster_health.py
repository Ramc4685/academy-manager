"""``GET /coach/roster-health`` (S49, decision D-14).

Run over the real Mongo reader (mongomock): who may read is decided by the
stored occurrence's staff fields, and the tenant boundary is a storage rule.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import BaseModel

from backend.v2.composition.coach_roster_health import compose_coach_roster_health
from backend.v2.contexts.coaching.application.use_cases.generate_daily_teaching_plan import (
    DailyTeachingPlan,
)
from backend.v2.interfaces.coach.router import router as coach_router
from backend.v2.interfaces.coach.views import (
    CoachScheduleResponse,
    CoachSessionTeachingPlanResponse,
    CoachTodayResponse,
    RosterResponse,
)
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers
from backend.v2.shared.profile.completeness import MEDICAL_NONE_SENTINEL
from backend.v2.shared.tenancy.context import _current as _tenant_var
from backend.v2.shared.tenancy.context import set_academy_id

ACADEMY = "academy-a"
OTHER = "academy-b"
START = datetime(2026, 11, 26, 22, 30, tzinfo=UTC)
END = datetime(2026, 11, 26, 23, 30, tzinfo=UTC)
URL = "/api/v2/coach/roster-health?occurrence_id=occ-1"


def _occurrence(academy: str, occ_id: str, session_id: str, **staff: Any) -> dict[str, Any]:
    return {
        "academy_id": academy,
        "occurrence_id": occ_id,
        "session_id": session_id,
        "start_at": START,
        "end_at": END,
        "status": "scheduled",
        "scheduled_coach_id": staff.get("lead", "coach-lead"),
        "substitute_coach_id": staff.get("cover"),
        "assistant_coach_ids": staff.get("assistants", []),
    }


def _student(sid: str, name: str, note: str | None, **extra: Any) -> dict[str, Any]:
    doc = {"academy_id": ACADEMY, "student_id": sid, "full_name": name, "parent_id": "par-1"}
    if note is not None:
        doc["medical_notes"] = note
    return {**doc, **extra}


@pytest.fixture
def db() -> Any:
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["coach-roster-health"]

    async def seed() -> None:
        await db["session_occurrences"].insert_many(
            [
                _occurrence(ACADEMY, "occ-1", "sess-1", cover="coach-cover", assistants=["asst-1"]),
                _occurrence(ACADEMY, "occ-2", "sess-2", lead="coach-other", assistants=["asst-2"]),
                _occurrence(OTHER, "occ-b", "sess-b", lead="coach-lead"),
            ]
        )
        await db["enrollments"].insert_many(
            [
                {
                    "academy_id": ACADEMY,
                    "enrollment_id": f"enr-{sid}",
                    "session_id": "sess-1",
                    "student_id": sid,
                    "status": "active",
                }
                for sid in ("stu-sam", "stu-alex", "stu-dev")
            ]
        )
        await db["students"].insert_many(
            [
                _student(
                    "stu-sam",
                    "Sam Demo",
                    "Peanut allergy, carries EpiPen",
                    emergency_contact_name="Rosa Demo",
                    emergency_contact_phone="(309) 555-0177",
                ),
                _student("stu-alex", "Alex Demo", MEDICAL_NONE_SENTINEL),
                _student("stu-dev", "Dev Patel", None),
            ]
        )
        await db["users"].insert_one(
            {"user_id": "par-1", "display_name": "Demo Parent", "phone": "(309) 555-0120"}
        )

    asyncio.run(seed())
    return db


def _client(db: Any, user_id: str, roles: tuple[str, ...]) -> TestClient:
    app = FastAPI()

    @app.middleware("http")
    async def _tenant(request: Request, call_next: Any) -> Any:
        token = set_academy_id(ACADEMY)
        try:
            return await call_next(request)
        finally:
            _tenant_var.reset(token)

    register_exception_handlers(app)
    app.include_router(coach_router, prefix="/api/v2")
    app.dependency_overrides[get_auth_claims] = lambda: AuthClaims(
        user_id=user_id,
        email=f"{user_id}@example.com",
        academy_id=ACADEMY,
        roles=roles,  # type: ignore[arg-type]
    )
    app.state.coach_roster_health = compose_coach_roster_health(db)
    return TestClient(app)


@pytest.mark.parametrize(
    ("user_id", "roles"),
    [
        ("coach-lead", ("coach",)),
        ("coach-cover", ("coach",)),
        ("asst-1", ("assistant_coach",)),
        ("adm-1", ("admin",)),
    ],
)
def test_assigned_staff_read_notes_contacts_and_parent_phone(
    db: Any, user_id: str, roles: tuple[str, ...]
) -> None:
    with _client(db, user_id, roles) as client:
        res = client.get(URL)
    assert res.status_code == 200, res.text
    assert res.headers["cache-control"] == "no-store"
    body = res.json()
    assert body["declared_count"] == 1
    by_id = {c["student_id"]: c for c in body["children"]}
    assert by_id["stu-sam"] == {
        "student_id": "stu-sam",
        "full_name": "Sam Demo",
        "status": "declared",
        "note": "Peanut allergy, carries EpiPen",
        "emergency_contact_name": "Rosa Demo",
        "emergency_contact_phone": "(309) 555-0177",
        "parent_name": "Demo Parent",
        "parent_phone": "(309) 555-0120",
    }
    # "None declared" is an answer; "not answered" is not. Neither leaks the sentinel.
    assert by_id["stu-alex"]["status"] == "none_declared"
    assert by_id["stu-alex"]["note"] is None
    assert by_id["stu-dev"]["status"] == "not_answered"


@pytest.mark.parametrize(
    ("user_id", "roles"),
    [
        ("coach-new", ("coach",)),  # not on this class
        ("asst-2", ("assistant_coach",)),  # assistant on another class
        ("par-1", ("parent",)),
        ("stu-sam", ("student",)),
    ],
)
def test_everyone_else_gets_404(db: Any, user_id: str, roles: tuple[str, ...]) -> None:
    with _client(db, user_id, roles) as client:
        assert client.get(URL).status_code == 404


def test_another_academys_class_is_404_even_for_its_lead(db: Any) -> None:
    with _client(db, "coach-lead", ("coach",)) as client:
        assert client.get("/api/v2/coach/roster-health?occurrence_id=occ-b").status_code == 404
        assert client.get("/api/v2/coach/roster-health?occurrence_id=ghost").status_code == 404


def _property_names(schema: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for definition in [schema, *schema.get("$defs", {}).values()]:
        names |= set(definition.get("properties", {}))
    return names


@pytest.mark.parametrize(
    "model",
    [
        CoachTodayResponse,
        CoachScheduleResponse,
        RosterResponse,
        CoachSessionTeachingPlanResponse,
        DailyTeachingPlan,
    ],
)
def test_cached_coach_payloads_carry_no_health_field(model: type[BaseModel]) -> None:
    """Today, sessions and plan payloads are cached for 24h on the phone (sw.ts)
    and persisted to localStorage, so no health or contact field may ride on them."""
    names = _property_names(model.model_json_schema())
    for banned in ("medical", "health", "emergency", "allerg", "phone"):
        assert not [n for n in names if banned in n], (model.__name__, banned)
