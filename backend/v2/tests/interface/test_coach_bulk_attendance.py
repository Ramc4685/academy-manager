"""Interface tests for POST /api/v2/coach/occurrences/{occurrence_id}/attendance/bulk."""

from __future__ import annotations


def _payload(**overrides):
    base = {
        "mutation_id": "01HXBULK001",
        "session_id": "s-today-1",
        "entries": [
            {"student_id": "st1", "status": "present"},
            {"student_id": "st2", "status": "absent"},
        ],
    }
    base.update(overrides)
    return base


def test_bulk_mark_attendance_happy_path(coach_client):
    r = coach_client.post(
        "/api/v2/coach/occurrences/occ-today-1/attendance/bulk",
        json=_payload(),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "results" in body
    assert len(body["results"]) == 2
    student_ids = {e["student_id"] for e in body["results"]}
    assert student_ids == {"st1", "st2"}
    for entry in body["results"]:
        assert "attendance_id" in entry
        assert entry["status"] in ("present", "absent")


def test_bulk_mark_attendance_idempotent_replay(coach_client):
    first = coach_client.post(
        "/api/v2/coach/occurrences/occ-today-1/attendance/bulk",
        json=_payload(),
    )
    second = coach_client.post(
        "/api/v2/coach/occurrences/occ-today-1/attendance/bulk",
        json=_payload(),
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()


def test_bulk_mark_attendance_unassigned_coach_returns_403(coach_client):
    # occ-other-coach is assigned to coach-2, not coach-1
    r = coach_client.post(
        "/api/v2/coach/occurrences/occ-other-coach/attendance/bulk",
        json=_payload(session_id="s-other-coach"),
    )
    assert r.status_code == 403, r.text


def test_bulk_mark_attendance_non_enrolled_student_returns_422(coach_client):
    r = coach_client.post(
        "/api/v2/coach/occurrences/occ-today-1/attendance/bulk",
        json=_payload(
            entries=[
                {"student_id": "st1", "status": "present"},
                {"student_id": "ghost", "status": "present"},  # not enrolled
            ]
        ),
    )
    assert r.status_code == 422, r.text


def test_bulk_mark_attendance_anon_returns_401(anon_client):
    r = anon_client.post(
        "/api/v2/coach/occurrences/occ-today-1/attendance/bulk",
        json=_payload(),
    )
    assert r.status_code == 401


def test_bulk_mark_attendance_wrong_persona_returns_404(parent_client):
    r = parent_client.post(
        "/api/v2/coach/occurrences/occ-today-1/attendance/bulk",
        json=_payload(),
    )
    assert r.status_code == 404
