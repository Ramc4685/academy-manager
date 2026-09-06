"""Assistant coach role (``assistant_coach``): a per-session helper.

An assistant reaches the coach surface but only for sessions whose
``assistant_coach_ids`` list them, and only for attendance, skills and notes.
Lesson-plan authoring, roster edits, billing moves, messages, announcements
and feedback are lead-only (``require_coach_lead_surface``) and 404 for an
assistant exactly like a wrong persona. Admins manage the list through
``PUT /admin/sessions/{id}/assistants``, which re-syncs future occurrences.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.v2.composition.admin import compose_admin
from backend.v2.contexts.billing.infrastructure.fake_stripe_gateway import FakeStripeGateway
from backend.v2.contexts.enrollment.domain.models import Session, SessionOccurrence
from backend.v2.interfaces.admin.router import router as admin_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers
from backend.v2.shared.http.persona import is_assistant_only, is_coach_supervisor
from backend.v2.shared.tenancy.context import set_academy_id
from backend.v2.tests.interface.conftest import (
    _assistant_coach_claims,
    _build_use_cases,
    _make_app,
)

ASSISTANT = "asst-1"
ASSISTED_SESSION = "s-today-1"
ASSISTED_OCC = "occ-today-1"
OTHER_SESSION = "s-today-2"
OTHER_OCC = "occ-today-2"


@pytest.fixture()
def seed(seed):
    """Shared coach seed with ``asst-1`` listed as assistant on ``s-today-1``
    (and its occurrence). ``s-today-2`` / ``s-other-coach`` stay untouched."""
    seed["sessions"] = [
        s.model_copy(update={"assistant_coach_ids": (ASSISTANT,)})
        if s.session_id == ASSISTED_SESSION
        else s
        for s in seed["sessions"]
    ]
    seed["occurrences"] = [
        o.model_copy(update={"assistant_coach_ids": (ASSISTANT,)})
        if o.occurrence_id == ASSISTED_OCC
        else o
        for o in seed["occurrences"]
    ]
    return seed


class _SpyUseCase:
    def __init__(self, result) -> None:
        self.result = result
        self.calls: list[object] = []

    async def execute(self, command):
        self.calls.append(command)
        return self.result


class _Dumpable(SimpleNamespace):
    def model_dump(self):
        return dict(vars(self))


@pytest.fixture()
def assistant_client(seed):
    use_cases = _build_use_cases(seed)
    # Skill routes need a student-progress service and the student->sessions
    # read; the shared builder leaves both unwired.
    update_skill_status = _SpyUseCase(
        _Dumpable(student_id="st1", skill_id="skill-1", status="PRACTICING")
    )
    use_cases.student_progress = SimpleNamespace(update_skill_status=update_skill_status)

    async def _active_sessions_for_student(student_id: str):
        return [SimpleNamespace(session_id=ASSISTED_SESSION)] if student_id == "st1" else []

    use_cases.get_active_session_enrollments_for_student = _active_sessions_for_student
    with TestClient(_make_app(_assistant_coach_claims(), use_cases)) as client:
        client.coach_use_cases = use_cases  # type: ignore[attr-defined]
        client.update_skill_status = update_skill_status  # type: ignore[attr-defined]
        yield client


def _mark(client, occurrence_id=ASSISTED_OCC, session_id=ASSISTED_SESSION, **overrides):
    body = {
        "mutation_id": "01HXMVTASST000000000000001",
        "occurrence_id": occurrence_id,
        "session_id": session_id,
        "student_id": "st1",
        "status": "present",
        "client_app_version": "test",
    }
    body.update(overrides)
    return client.post("/api/v2/coach/attendance", json=body)


# --- claims semantics ------------------------------------------------------


def test_assistant_is_never_a_supervisor_and_is_assistant_only():
    claims = _assistant_coach_claims()
    assert is_coach_supervisor(claims) is False
    assert is_assistant_only(claims) is True


def test_assistant_who_is_also_a_coach_is_a_lead():
    claims = AuthClaims(
        user_id="dual",
        email="dual@example.com",
        academy_id="test-academy",
        roles=("assistant_coach", "coach"),
    )
    assert is_assistant_only(claims) is False


# --- scoped reads ----------------------------------------------------------


def test_today_lists_only_assisted_sessions(assistant_client):
    r = assistant_client.get("/api/v2/coach/today?date=2026-05-16")
    assert r.status_code == 200, r.text
    sessions = r.json()["sessions"]
    assert {s["session_id"] for s in sessions} == {ASSISTED_SESSION}
    # Roster still renders: the assistant marks these students.
    assert {e["student_id"] for e in sessions[0]["roster"]} == {"st1", "st2"}


def test_sessions_lists_only_assisted_sessions(assistant_client):
    r = assistant_client.get("/api/v2/coach/sessions")
    assert r.status_code == 200, r.text
    assert {s["session_id"] for s in r.json()["sessions"]} == {ASSISTED_SESSION}


def test_roster_read_for_assisted_session_and_not_others(assistant_client):
    assert (
        assistant_client.get(f"/api/v2/coach/sessions/{ASSISTED_SESSION}/roster").status_code == 200
    )
    assert assistant_client.get(f"/api/v2/coach/sessions/{OTHER_SESSION}/roster").status_code == 403


# --- allowed writes --------------------------------------------------------


def test_assistant_marks_attendance_on_assisted_occurrence(assistant_client):
    r = _mark(assistant_client)
    assert r.status_code == 200, r.text
    repo = assistant_client.coach_use_cases.mark_attendance._attendance  # type: ignore[attr-defined]
    assert [m.marked_by for m in repo.saved if m.occurrence_id == ASSISTED_OCC] == [ASSISTANT]


def test_assistant_bulk_marks_assisted_occurrence(assistant_client):
    r = assistant_client.post(
        f"/api/v2/coach/occurrences/{ASSISTED_OCC}/attendance/bulk",
        json={
            "mutation_id": "01HXMVTASST000000000000002",
            "session_id": ASSISTED_SESSION,
            "entries": [{"student_id": "st1", "status": "present"}],
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["results"][0]["student_id"] == "st1"


def test_assistant_corrects_own_fresh_mark(assistant_client):
    assert _mark(assistant_client).status_code == 200
    r = assistant_client.patch(
        f"/api/v2/coach/occurrences/{ASSISTED_OCC}/attendance/st1",
        json={"status": "absent", "reason": "left early"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "absent"


def test_assistant_sets_skill_status_for_student_on_assisted_session(assistant_client):
    r = assistant_client.post(
        "/api/v2/coach/students/st1/skills/skill-1/status",
        json={"level_id": "level-1", "program_id": "program-1", "status": "PRACTICING"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "PRACTICING"
    (command,) = assistant_client.update_skill_status.calls  # type: ignore[attr-defined]
    assert command.updated_by == ASSISTANT


def test_assistant_posts_progress_note_on_assisted_session(assistant_client):
    r = assistant_client.post(
        f"/api/v2/coach/sessions/{ASSISTED_SESSION}/progress-notes",
        json={"student_id": "st1", "body": "Great footwork today"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["student_id"] == "st1"
    listed = assistant_client.get(f"/api/v2/coach/sessions/{ASSISTED_SESSION}/progress-notes")
    assert listed.status_code == 200
    assert len(listed.json()["notes"]) == 1


# --- scope boundary --------------------------------------------------------


def test_assistant_cannot_mark_unassisted_occurrence(assistant_client):
    # Same answer a coach gets for someone else's class: the assignment
    # check is the use case's, not the guard's.
    r = _mark(assistant_client, occurrence_id=OTHER_OCC, session_id=OTHER_SESSION)
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "Coaching.SessionNotAssigned"


def test_assistant_cannot_note_unassisted_session(assistant_client):
    r = assistant_client.post(
        f"/api/v2/coach/sessions/{OTHER_SESSION}/progress-notes",
        json={"student_id": "st1", "body": "nope"},
    )
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "Coaching.SessionNotAssigned"


# --- lead-only routes are invisible ---------------------------------------


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        (
            "post",
            f"/api/v2/coach/sessions/{ASSISTED_SESSION}/lesson-plans",
            {"title": "Plan", "body": "Drills"},
        ),
        (
            "post",
            f"/api/v2/coach/sessions/{ASSISTED_SESSION}/roster",
            {"student_id": "st9", "parent_id": "p9", "full_name": "New Kid"},
        ),
        ("delete", f"/api/v2/coach/sessions/{ASSISTED_SESSION}/roster/st1", None),
        ("get", "/api/v2/coach/billing-enrollments", None),
        ("get", "/api/v2/coach/messages", None),
        ("get", f"/api/v2/coach/sessions/{ASSISTED_SESSION}/announcements", None),
        (
            "post",
            f"/api/v2/coach/sessions/{ASSISTED_SESSION}/feedback",
            {"rating": 5, "comment": "x"},
        ),
        ("get", f"/api/v2/coach/sessions/{ASSISTED_SESSION}/feedback", None),
    ],
)
def test_lead_only_routes_return_404_for_assistant(assistant_client, method, path, body):
    kwargs = {"json": body} if body is not None else {}
    r = getattr(assistant_client, method)(path, **kwargs)
    assert r.status_code == 404, (method, path, r.text)


def test_lead_only_routes_still_open_to_real_coach(coach_client):
    # The new guard narrows assistants only; the coach keeps every route.
    assert coach_client.get("/api/v2/coach/messages").status_code == 200
    assert (
        coach_client.get(f"/api/v2/coach/sessions/{ASSISTED_SESSION}/lesson-plans").status_code
        == 200
    )


def test_assistant_can_read_lesson_plans_but_not_author(assistant_client):
    assert (
        assistant_client.get(f"/api/v2/coach/sessions/{ASSISTED_SESSION}/lesson-plans").status_code
        == 200
    )


def test_coach_messages_audience_excludes_assisted_sessions(coach_client, assistant_client):
    # A message addressed to the session reaches its coach, never its assistant
    # (who is 404'd at the route anyway — this pins the visibility read).
    repo = coach_client.messages_repo  # type: ignore[attr-defined]
    ids = coach_client.coach_use_cases.list_messages
    del ids
    visible = _visible_ids(coach_client.coach_use_cases)
    assert ASSISTED_SESSION in visible("coach-1")
    assert visible(ASSISTANT) == []
    del repo


def _visible_ids(use_cases):
    import asyncio

    sessions = use_cases.list_today._sessions  # FakeSessionQuery

    def _run(coach_id: str) -> list[str]:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(
                sessions.assigned_session_ids_for_coach(coach_id, include_assistant=False)
            )
        finally:
            loop.close()

    return _run


# --- admin editor: PUT /admin/sessions/{id}/assistants ----------------------

ACADEMY = "academy-b"
_PAST = datetime(2026, 1, 5, 15, 0, tzinfo=UTC)
_FUTURE = datetime(2099, 1, 5, 15, 0, tzinfo=UTC)


class _FakeOutbox:
    async def append(self, event, *, session=None) -> None:
        pass

    async def pull_unprocessed(self, limit: int = 100) -> list[object]:
        return []

    async def mark_processed(self, event_id: str) -> None:
        pass


class _FakeIdempotencyStore:
    async def get(self, key: str):
        return None

    async def put(self, key: str, value) -> None:
        pass


def _mongo_admin_app(db) -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def _tenant_scope(request: Request, call_next):
        token = set_academy_id(ACADEMY)
        try:
            return await call_next(request)
        finally:
            from backend.v2.shared.tenancy.context import _current as _tenant_var

            _tenant_var.reset(token)

    register_exception_handlers(app)
    app.include_router(admin_router, prefix="/api/v2")
    app.state.admin = compose_admin(db, _FakeOutbox(), _FakeIdempotencyStore(), FakeStripeGateway())
    app.dependency_overrides[get_auth_claims] = lambda: AuthClaims(
        user_id="admin-1", email="admin@example.com", academy_id=ACADEMY, roles=("admin",)
    )
    return app


async def _seed_admin_db(db) -> None:
    await db.sessions.insert_one(
        {
            "academy_id": ACADEMY,
            "session_id": "sess-a",
            "title": "Junior A",
            "location": "Court 1",
            "coach_id": "coach-1",
            "capacity": 8,
            "status": "scheduled",
            "start_at": _PAST,
            "end_at": _PAST.replace(hour=16),
        }
    )
    await db.session_occurrences.insert_many(
        [
            {
                "academy_id": ACADEMY,
                "occurrence_id": "occ-past",
                "session_id": "sess-a",
                "start_at": _PAST,
                "end_at": _PAST.replace(hour=16),
                "status": "completed",
                "scheduled_coach_id": "coach-1",
            },
            {
                "academy_id": ACADEMY,
                "occurrence_id": "occ-future",
                "session_id": "sess-a",
                "template_session_id": "sess-a",
                "start_at": _FUTURE,
                "end_at": _FUTURE.replace(hour=16),
                "status": "scheduled",
                "scheduled_coach_id": "coach-1",
            },
        ]
    )
    await db.academy_memberships.insert_many(
        [
            {"academy_id": ACADEMY, "user_id": uid, "roles": roles, "status": status}
            for uid, roles, status in [
                ("coach-1", ["coach"], "active"),
                ("coach-2", ["coach"], "active"),
                ("asst-1", ["assistant_coach"], "active"),
                ("asst-gone", ["assistant_coach"], "removed"),
                ("p1", ["parent"], "active"),
            ]
        ]
    )
    await db.users.insert_many(
        [
            {
                "academy_id": ACADEMY,
                "user_id": uid,
                "email": f"{uid}@example.com",
                "display_name": name,
            }
            for uid, name in [
                ("coach-1", "Coach One"),
                ("coach-2", "Coach Two"),
                ("asst-1", "Helper"),
            ]
        ]
    )


@pytest.fixture()
def admin_mongo():
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["assistant-editor"]
    with TestClient(_mongo_admin_app(db)) as client:
        yield client, db


def _put(client, ids, reason=None):
    body = {"assistant_coach_ids": ids}
    if reason is not None:
        body["reason"] = reason
    return client.put("/api/v2/admin/sessions/sess-a/assistants", json=body)


@pytest.mark.asyncio
async def test_admin_sets_assistants_and_future_occurrences_follow(admin_mongo):
    client, db = admin_mongo
    await _seed_admin_db(db)

    r = _put(client, ["coach-2", "asst-1", "asst-1"], reason="extra hands")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["assistant_coach_ids"] == ["coach-2", "asst-1"]
    assert body["assistant_coach_names"] == ["Coach Two", "Helper"]
    assert body["coach_name"] == "Coach One"

    detail = client.get("/api/v2/admin/sessions/sess-a")
    assert detail.status_code == 200, detail.text
    assert detail.json()["assistant_coach_ids"] == ["coach-2", "asst-1"]

    future = await db.session_occurrences.find_one({"occurrence_id": "occ-future"})
    past = await db.session_occurrences.find_one({"occurrence_id": "occ-past"})
    assert future["assistant_coach_ids"] == ["coach-2", "asst-1"]
    assert "assistant_coach_ids" not in past, "history keeps the staff it ran with"

    cleared = _put(client, [])
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["assistant_coach_ids"] == []
    future = await db.session_occurrences.find_one({"occurrence_id": "occ-future"})
    assert future["assistant_coach_ids"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("user_id", "why"),
    [
        ("p1", "a parent is not coaching staff"),
        ("asst-gone", "a removed membership grants nothing"),
        ("nobody", "unknown users are refused"),
        ("coach-1", "the primary coach is not their own assistant"),
    ],
)
async def test_admin_put_rejects_ineligible_assistants(admin_mongo, user_id, why):
    client, db = admin_mongo
    await _seed_admin_db(db)
    r = _put(client, [user_id])
    assert r.status_code == 422, (why, r.text)
    assert r.json()["error"]["code"] == "Enrollment.InvalidSessionAssistant"
    session = await db.sessions.find_one({"session_id": "sess-a"})
    assert not session.get("assistant_coach_ids"), "a rejected PUT writes nothing"


@pytest.mark.asyncio
async def test_admin_put_unknown_session_is_404(admin_mongo):
    client, db = admin_mongo
    await _seed_admin_db(db)
    r = client.put("/api/v2/admin/sessions/no-such/assistants", json={"assistant_coach_ids": []})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_admin_edit_session_accepts_assistants_and_lists_them(admin_mongo):
    client, db = admin_mongo
    await _seed_admin_db(db)
    r = client.patch("/api/v2/admin/sessions/sess-a", json={"assistant_coach_ids": ["asst-1"]})
    assert r.status_code == 200, r.text
    assert r.json()["assistant_coach_ids"] == ["asst-1"]
    listed = client.get("/api/v2/admin/sessions?date=2026-01-05")
    assert listed.status_code == 200, listed.text
    (row,) = [s for s in listed.json()["sessions"] if s["session_id"] == "sess-a"]
    assert row["assistant_coach_ids"] == ["asst-1"]
    assert row["assistant_coach_names"] == ["Helper"]


def test_domain_round_trip_defaults_to_no_assistants():
    session = Session(
        session_id="s",
        academy_id="a",
        coach_id="c",
        title="t",
        location="l",
        start_at=_PAST,
        end_at=_PAST.replace(hour=16),
        capacity=1,
    )
    assert session.assistant_coach_ids == ()
    occurrence = SessionOccurrence(
        occurrence_id="o",
        academy_id="a",
        session_id="s",
        start_at=_PAST,
        end_at=_PAST.replace(hour=16),
        scheduled_coach_id="c",
    )
    assert occurrence.assistant_coach_ids == ()
