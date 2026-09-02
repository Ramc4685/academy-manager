"""Coach supervision (#632): admins/owners cover any session on the coach surface.

The coach BFF admits academy ``admin``/``owner`` claims. On that surface a
supervisor sees every session in the academy and passes every "assigned to
this session" check, while writes stay attributed to their own user id.
Coaches keep their personal scope; parents still get 404 everywhere.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from backend.v2.contexts.enrollment.domain.models import Enrollment
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.tests.interface.conftest import _admin_claims, _build_use_cases, _make_app

OTHER_OCC = "occ-other-coach"
OTHER_SESSION = "s-other-coach"


def _owner_claims() -> AuthClaims:
    return AuthClaims(
        user_id="adm",
        email="owner@example.com",
        academy_id="test-academy",
        roles=("owner",),
    )


@pytest.fixture()
def seed(seed):
    """Shared coach seed plus one active enrollment on the other coach's
    session, so a supervisor has someone to mark there. Coach-1's own
    sessions (and the golden master) are untouched."""
    seed["enrollments"] = [
        *seed["enrollments"],
        Enrollment(
            enrollment_id="e-other",
            academy_id="test-academy",
            session_id=OTHER_SESSION,
            student_id="st1",
            status="active",
        ),
    ]
    return seed


@pytest.fixture()
def coach_admin_client(seed):
    use_cases = _build_use_cases(seed)
    with TestClient(_make_app(_admin_claims(), use_cases)) as client:
        client.coach_use_cases = use_cases  # type: ignore[attr-defined]
        yield client


@pytest.fixture()
def owner_client(seed):
    use_cases = _build_use_cases(seed)
    with TestClient(_make_app(_owner_claims(), use_cases)) as client:
        client.coach_use_cases = use_cases  # type: ignore[attr-defined]
        yield client


def _mark(client, mutation_id="01HXMVTADMCVR0000000000001", **overrides):
    body = {
        "mutation_id": mutation_id,
        "occurrence_id": OTHER_OCC,
        "session_id": OTHER_SESSION,
        "student_id": "st1",
        "status": "present",
        "client_app_version": "test",
    }
    body.update(overrides)
    return client.post("/api/v2/coach/attendance", json=body)


# --- reads -----------------------------------------------------------------


def test_admin_today_is_academy_wide_and_labelled(coach_admin_client):
    r = coach_admin_client.get("/api/v2/coach/today?date=2026-05-16")
    assert r.status_code == 200, r.text
    by_id = {s["session_id"]: s for s in r.json()["sessions"]}
    assert set(by_id) == {"s-today-1", "s-today-2", OTHER_SESSION}
    assert by_id[OTHER_SESSION]["coach_id"] == "coach-2"
    assert by_id[OTHER_SESSION]["coach_name"] == "Coach Two"
    assert by_id["s-today-1"]["coach_name"] == "Coach One"


def test_owner_role_is_a_supervisor_too(owner_client):
    r = owner_client.get("/api/v2/coach/today?date=2026-05-16")
    assert r.status_code == 200, r.text
    assert {s["session_id"] for s in r.json()["sessions"]} == {
        "s-today-1",
        "s-today-2",
        OTHER_SESSION,
    }


def test_coach_today_stays_personal_and_unlabelled(coach_client):
    r = coach_client.get("/api/v2/coach/today?date=2026-05-16")
    assert r.status_code == 200, r.text
    sessions = r.json()["sessions"]
    assert {s["session_id"] for s in sessions} == {"s-today-1", "s-today-2"}
    # coach_id is carried; the name lookup is skipped on the coach path.
    assert all(s["coach_name"] is None for s in sessions)
    assert {s["coach_id"] for s in sessions} == {"coach-1"}


def test_admin_sessions_list_is_academy_wide(coach_admin_client):
    r = coach_admin_client.get("/api/v2/coach/sessions")
    assert r.status_code == 200, r.text
    sessions = r.json()["sessions"]
    assert OTHER_SESSION in {s["session_id"] for s in sessions}
    assert all(s["coach_name"] for s in sessions)


def test_admin_roster_read_for_unassigned_session(coach_admin_client):
    r = coach_admin_client.get(f"/api/v2/coach/sessions/{OTHER_SESSION}/roster")
    assert r.status_code == 200, r.text


def test_admin_roster_read_unknown_session_still_forbidden(coach_admin_client):
    # Supervision widens scope inside the tenant only: a session that does
    # not exist here is not reachable even for an admin.
    r = coach_admin_client.get("/api/v2/coach/sessions/no-such-session/roster")
    assert r.status_code == 403


# --- writes ----------------------------------------------------------------


def test_admin_marks_attendance_on_unassigned_session(coach_admin_client):
    r = _mark(coach_admin_client)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["occurrence_id"] == OTHER_OCC
    assert body["status"] == "present"
    # Attributed to the admin, not to the assigned coach.
    marks = coach_admin_client.coach_use_cases.list_attendance_for_occurrence  # type: ignore[attr-defined]
    rows = asyncio.run(marks(OTHER_OCC))
    assert [m.marked_by for m in rows] == ["adm"]


def test_admin_mark_is_idempotent_on_mutation_id(coach_admin_client):
    first = _mark(coach_admin_client)
    second = _mark(coach_admin_client)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()


def test_admin_mark_still_requires_enrolled_student(coach_admin_client):
    r = _mark(coach_admin_client, student_id="ghost")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "Coaching.StudentNotEnrolled"


def test_admin_mark_still_rejects_unknown_occurrence(coach_admin_client):
    r = _mark(coach_admin_client, occurrence_id="occ-nope")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "Coaching.SessionNotAssigned"


def test_admin_bulk_marks_unassigned_session(coach_admin_client):
    r = coach_admin_client.post(
        f"/api/v2/coach/occurrences/{OTHER_OCC}/attendance/bulk",
        json={
            "mutation_id": "01HXMVTADMCVR0000000000002",
            "session_id": OTHER_SESSION,
            "entries": [{"student_id": "st1", "status": "present"}],
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["results"][0]["student_id"] == "st1"


def test_admin_corrects_old_mark_without_coach_window(coach_admin_client):
    # A coach could not correct a mark older than 48h; a supervisor takes the
    # admin path and can.
    use_cases = coach_admin_client.coach_use_cases  # type: ignore[attr-defined]
    stale = datetime.now(UTC) - timedelta(days=5)
    use_cases.mark_attendance._now = lambda: stale
    assert _mark(coach_admin_client).status_code == 200
    r = coach_admin_client.patch(
        f"/api/v2/coach/occurrences/{OTHER_OCC}/attendance/st1",
        json={"status": "absent", "reason": "left early per parent"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "absent"


# --- boundaries stay put ---------------------------------------------------


def test_coach_still_cannot_mark_unassigned_session(coach_client):
    r = _mark(coach_client)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "Coaching.SessionNotAssigned"


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/v2/coach/today"),
        ("get", "/api/v2/coach/sessions"),
        ("get", f"/api/v2/coach/sessions/{OTHER_SESSION}/roster"),
        ("post", "/api/v2/coach/attendance"),
    ],
)
def test_parent_still_gets_404_everywhere(parent_client, method, path):
    kwargs = {"json": {}} if method == "post" else {}
    r = getattr(parent_client, method)(path, **kwargs)
    assert r.status_code == 404
