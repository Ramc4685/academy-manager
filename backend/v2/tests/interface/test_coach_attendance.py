"""Interface tests for POST /api/v2/coach/attendance.

Happy path + idempotent replay + each rejection case + wrong-persona 404.
"""

from __future__ import annotations


def _payload(**overrides):
    base = {
        "mutation_id": "01HXMUT123",
        "occurrence_id": "occ-today-1",
        "session_id": "s-today-1",
        "student_id": "st1",
        "status": "present",
        "client_app_version": "test",
    }
    base.update(overrides)
    return base


def test_mark_attendance_happy_path(coach_client):
    r = coach_client.post("/api/v2/coach/attendance", json=_payload())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["attendance_id"] == "01HXMUT123"
    assert body["status"] == "present"


def test_mark_attendance_idempotent_replay(coach_client):
    first = coach_client.post("/api/v2/coach/attendance", json=_payload())
    second = coach_client.post("/api/v2/coach/attendance", json=_payload())
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()


def test_mark_attendance_conflict_for_different_mutation(coach_client):
    coach_client.post("/api/v2/coach/attendance", json=_payload(mutation_id="m1"))
    r = coach_client.post("/api/v2/coach/attendance", json=_payload(mutation_id="m2"))
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "Coaching.ConflictAttendanceExists"


def test_mark_attendance_session_not_assigned(coach_client):
    r = coach_client.post("/api/v2/coach/attendance", json=_payload(session_id="s-other-coach"))
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "Coaching.SessionNotAssigned"


def test_mark_attendance_unknown_student(coach_client):
    r = coach_client.post("/api/v2/coach/attendance", json=_payload(student_id="ghost"))
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "Coaching.StudentNotEnrolled"


def test_mark_attendance_parent_persona_returns_404(parent_client):
    r = parent_client.post("/api/v2/coach/attendance", json=_payload())
    assert r.status_code == 404


def test_mark_attendance_admin_persona_returns_404(admin_client):
    r = admin_client.post("/api/v2/coach/attendance", json=_payload())
    assert r.status_code == 404


def test_mark_attendance_unauthenticated(anon_client):
    r = anon_client.post("/api/v2/coach/attendance", json=_payload())
    assert r.status_code == 401


def test_mark_attendance_invalid_status_rejected(coach_client):
    r = coach_client.post("/api/v2/coach/attendance", json=_payload(status="excellent"))
    assert r.status_code == 422  # FastAPI/Pydantic body validation
