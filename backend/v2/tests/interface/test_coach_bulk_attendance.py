"""Interface tests for POST /api/v2/coach/occurrences/{occurrence_id}/attendance/bulk."""

from __future__ import annotations


def _payload(**overrides):
    base = {
        "mutation_id": "01HXBKATTENDANCE0000000001",
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


# --- issue #672: make-up / trial attendees on the occurrence roster ---


def _seed_with_one_time_rows(seed):
    """Seed the make-up and trial rows the coach roster renders for
    occ-today-1, plus a paused enrollment that must stay ineligible."""
    from datetime import UTC, datetime

    from backend.v2.contexts.enrollment.domain.models import Enrollment, Student
    from backend.v2.contexts.enrollment.domain.self_service import OccurrenceRosterEntry

    seed["students"] = [
        *seed["students"],
        Student(student_id="st-makeup", academy_id="test-academy", parent_id="p3", full_name="C"),
        Student(student_id="st-trial", academy_id="test-academy", parent_id="p4", full_name="D"),
        Student(student_id="st-paused", academy_id="test-academy", parent_id="p5", full_name="E"),
    ]
    seed["enrollments"] = [
        *seed["enrollments"],
        Enrollment(
            enrollment_id="e-paused",
            academy_id="test-academy",
            session_id="s-today-1",
            student_id="st-paused",
            status="paused",
        ),
    ]
    created = datetime(2026, 5, 15, 8, 0, tzinfo=UTC)
    seed["occurrence_roster_entries"] = [
        OccurrenceRosterEntry(
            entry_id="ore-makeup",
            academy_id="test-academy",
            occurrence_id="occ-today-1",
            student_id="st-makeup",
            source="makeup",
            origin_request_id="req-1",
            created_at=created,
        ),
        OccurrenceRosterEntry(
            entry_id="ore-trial",
            academy_id="test-academy",
            occurrence_id="occ-today-1",
            student_id="st-trial",
            source="trial",
            origin_request_id="req-2",
            created_at=created,
        ),
        # Approved for a *different* occurrence: not eligible today.
        OccurrenceRosterEntry(
            entry_id="ore-other-day",
            academy_id="test-academy",
            occurrence_id="occ-today-2",
            student_id="st-paused",
            source="makeup",
            origin_request_id="req-3",
            created_at=created,
        ),
    ]
    return seed


def _client_for(seed):
    from fastapi.testclient import TestClient

    from backend.v2.tests.interface.conftest import _build_use_cases, _coach_claims, _make_app

    use_cases = _build_use_cases(seed)
    return TestClient(_make_app(_coach_claims(), use_cases)), use_cases


def test_bulk_mark_all_present_accepts_makeup_and_trial_rows(seed):
    """The issue's scenario: every unmarked roster row — enrolled kids plus
    the approved make-up and trial — on one "Mark all present" tap."""
    client, use_cases = _client_for(_seed_with_one_time_rows(seed))
    with client:
        r = client.post(
            "/api/v2/coach/occurrences/occ-today-1/attendance/bulk",
            json=_payload(
                entries=[
                    {"student_id": "st1", "status": "present"},
                    {"student_id": "st2", "status": "present"},
                    {"student_id": "st-makeup", "status": "present"},
                    {"student_id": "st-trial", "status": "present"},
                ]
            ),
        )
    assert r.status_code == 200, r.text
    assert {e["student_id"] for e in r.json()["results"]} == {"st1", "st2", "st-makeup", "st-trial"}
    saved = {a.student_id: a.entry_source for a in use_cases.mark_attendance._attendance.saved}
    assert saved == {
        "st1": "enrollment",
        "st2": "enrollment",
        "st-makeup": "makeup",
        "st-trial": "trial",
    }


def test_bulk_422_names_every_ineligible_student(seed):
    """A paused row (and a ghost) in the batch: 422 with the ids in
    ``details.student_ids`` so the coach UI can say who, and nothing saved."""
    client, use_cases = _client_for(_seed_with_one_time_rows(seed))
    with client:
        r = client.post(
            "/api/v2/coach/occurrences/occ-today-1/attendance/bulk",
            json=_payload(
                entries=[
                    {"student_id": "st1", "status": "present"},
                    {"student_id": "st-paused", "status": "present"},
                    {"student_id": "st-makeup", "status": "present"},
                    {"student_id": "ghost", "status": "present"},
                ]
            ),
        )
    assert r.status_code == 422, r.text
    error = r.json()["error"]
    assert error["code"] == "Coaching.BulkStudentNotEnrolled"
    assert error["details"]["student_ids"] == ["st-paused", "ghost"]
    assert error["details"]["occurrence_id"] == "occ-today-1"
    assert use_cases.mark_attendance._attendance.saved == []
