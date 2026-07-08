"""Interface tests for GET /api/v2/coach/today.

Covers happy path, empty day, wrong-persona 404 (security matrix), and
unauthenticated 401.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from backend.v2.contexts.enrollment.application.use_cases.absence_notices import AbsenceNotice
from backend.v2.contexts.enrollment.domain.models import Student
from backend.v2.contexts.enrollment.domain.self_service import OccurrenceRosterEntry
from backend.v2.tests.interface.conftest import _build_use_cases, _coach_claims, _make_app


def test_coach_today_happy_path(coach_client):
    r = coach_client.get("/api/v2/coach/today?date=2026-05-16")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["date"] == "2026-05-16"
    session_ids = [s["session_id"] for s in body["sessions"]]
    assert session_ids == ["s-today-1", "s-today-2"]
    occurrence_ids = [s["occurrence_id"] for s in body["sessions"]]
    assert occurrence_ids == ["occ-today-1", "occ-today-2"]
    # Coach BFF must not leak other coaches' sessions.
    assert "s-other-coach" not in session_ids
    # Roster is composed for assigned sessions.
    first = body["sessions"][0]
    assert {r["full_name"] for r in first["roster"]} == {"Alice", "Bob"}


def test_coach_today_hydrates_existing_attendance(coach_client):
    """A recorded mark must come back on /today so reloads don't render a
    marked class as unmarked (and bulk mark-all doesn't 409 on re-send)."""
    mark = coach_client.post(
        "/api/v2/coach/attendance",
        json={
            "mutation_id": "01HTESTHYDRATE0000000000001",
            "occurrence_id": "occ-today-1",
            "session_id": "s-today-1",
            "student_id": "st1",
            "status": "present",
        },
    )
    assert mark.status_code in (200, 201), mark.text

    r = coach_client.get("/api/v2/coach/today?date=2026-05-16")
    assert r.status_code == 200, r.text
    first = r.json()["sessions"][0]
    by_id = {entry["student_id"]: entry for entry in first["roster"]}
    assert by_id["st1"]["attendance_status"] == "present"
    unmarked = [e for sid, e in by_id.items() if sid != "st1"]
    assert all(e["attendance_status"] is None for e in unmarked)


def test_coach_today_hydrates_late_attendance_without_response_validation_error(coach_client):
    """A "late" mark must round-trip through /today — the roster DTO's
    attendance_status must accept it, not just present/absent, or FastAPI
    response validation fails the whole day payload."""
    mark = coach_client.post(
        "/api/v2/coach/attendance",
        json={
            "mutation_id": "01HTESTHYDRATE0000000000002",
            "occurrence_id": "occ-today-1",
            "session_id": "s-today-1",
            "student_id": "st1",
            "status": "late",
        },
    )
    assert mark.status_code in (200, 201), mark.text

    r = coach_client.get("/api/v2/coach/today?date=2026-05-16")
    assert r.status_code == 200, r.text
    first = r.json()["sessions"][0]
    by_id = {entry["student_id"]: entry for entry in first["roster"]}
    assert by_id["st1"]["attendance_status"] == "late"


def test_coach_today_other_day_empty(coach_client):
    r = coach_client.get("/api/v2/coach/today?date=2026-05-17")
    assert r.status_code == 200
    assert r.json() == {"date": "2026-05-17", "sessions": []}


def test_coach_today_default_date_is_today(coach_client):
    r = coach_client.get("/api/v2/coach/today")
    assert r.status_code == 200


def test_coach_today_parent_persona_returns_404(parent_client):
    r = parent_client.get("/api/v2/coach/today")
    assert r.status_code == 404
    assert "/coach/" not in r.text.lower() or r.json().get("detail") == "Not found"


def test_coach_today_admin_persona_returns_404(admin_client):
    r = admin_client.get("/api/v2/coach/today")
    assert r.status_code == 404


def test_coach_today_unauthenticated_returns_401(anon_client):
    r = anon_client.get("/api/v2/coach/today")
    assert r.status_code == 401


# ---------- expected-absence flags + one-time roster entries (Task 3) ----------


def test_coach_today_flags_expected_absence_for_student_with_notice(seed):
    """Occurrence occ-today-1 (session s-today-1) has students st1/st2. An
    absence notice for st1 on that occurrence flags expected_absence=True;
    st2 (no notice) stays False."""
    seed["absence_notices"] = [
        AbsenceNotice(
            notice_id="notice-1",
            academy_id="test-academy",
            student_id="st1",
            occurrence_id="occ-today-1",
            session_id="s-today-1",
            submitted_by="p1",
            submitted_at=datetime(2026, 5, 15, 8, 0, tzinfo=UTC),
            notice_window_met=True,
        )
    ]
    use_cases = _build_use_cases(seed)
    app = _make_app(_coach_claims(), use_cases)
    with TestClient(app) as client:
        r = client.get("/api/v2/coach/today?date=2026-05-16")
    assert r.status_code == 200, r.text
    first = r.json()["sessions"][0]
    by_id = {entry["student_id"]: entry for entry in first["roster"]}
    assert by_id["st1"]["expected_absence"] is True
    assert by_id["st1"]["entry_source"] == "enrollment"
    assert by_id["st2"]["expected_absence"] is False


def test_coach_today_appends_one_time_makeup_entry_with_entry_source(seed):
    """A student with an OccurrenceRosterEntry(source="makeup") for
    occ-today-1 appears in the roster with entry_source="makeup", alongside
    the regular enrollment-backed students."""
    seed["students"] = [
        *seed["students"],
        Student(
            student_id="st-makeup",
            academy_id="test-academy",
            parent_id="p3",
            full_name="Charlie",
        ),
    ]
    seed["occurrence_roster_entries"] = [
        OccurrenceRosterEntry(
            entry_id="ore-1",
            academy_id="test-academy",
            occurrence_id="occ-today-1",
            student_id="st-makeup",
            source="makeup",
            origin_request_id="req-1",
            created_at=datetime(2026, 5, 15, 8, 0, tzinfo=UTC),
        )
    ]
    use_cases = _build_use_cases(seed)
    app = _make_app(_coach_claims(), use_cases)
    with TestClient(app) as client:
        r = client.get("/api/v2/coach/today?date=2026-05-16")
    assert r.status_code == 200, r.text
    first = r.json()["sessions"][0]
    by_id = {entry["student_id"]: entry for entry in first["roster"]}
    assert set(by_id) == {"st1", "st2", "st-makeup"}
    assert by_id["st-makeup"]["entry_source"] == "makeup"
    assert by_id["st-makeup"]["full_name"] == "Charlie"
    assert by_id["st-makeup"]["enrollment_status"] is None
    assert by_id["st1"]["entry_source"] == "enrollment"
