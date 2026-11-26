"""Interface tests for GET /api/v2/coach/today.

Covers happy path, empty day, wrong-persona 404 (security matrix), and
unauthenticated 401.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from fastapi.testclient import TestClient

from backend.v2.contexts.enrollment.application.use_cases.absence_notices import AbsenceNotice
from backend.v2.contexts.enrollment.domain.models import Enrollment, SessionOccurrence, Student
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
            "mutation_id": "01HTESTHYDRATE000000000001",
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
    # When it was recorded, so the app can close the 48h correction window.
    assert by_id["st1"]["attendance_marked_at"].startswith("2026-05-16T19:00")
    # UTC-marked, or the phone reads it as local time and shifts the 48h lock.
    assert by_id["st1"]["attendance_marked_at"].endswith(("Z", "+00:00"))
    unmarked = [e for sid, e in by_id.items() if sid != "st1"]
    assert all(e["attendance_status"] is None for e in unmarked)
    assert all(e["attendance_marked_at"] is None for e in unmarked)


def test_coach_today_hydrates_late_attendance_without_response_validation_error(coach_client):
    """A "late" mark must round-trip through /today — the roster DTO's
    attendance_status must accept it, not just present/absent, or FastAPI
    response validation fails the whole day payload."""
    mark = coach_client.post(
        "/api/v2/coach/attendance",
        json={
            "mutation_id": "01HTESTHYDRATE000000000002",
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


def test_coach_today_admin_persona_sees_every_session(coach_admin_client):
    # Admins are coach supervisors (#632): same route, academy-wide scope,
    # each session labelled with its coach.
    r = coach_admin_client.get("/api/v2/coach/today?date=2026-05-16")
    assert r.status_code == 200, r.text
    sessions = r.json()["sessions"]
    assert [s["session_id"] for s in sessions] == ["s-today-1", "s-other-coach", "s-today-2"]
    assert {s["coach_name"] for s in sessions} == {"Coach One", "Coach Two"}


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


# ---------- held enrollments stay on the day's roster (#732) ----------


def test_coach_today_includes_held_student_without_500(seed):
    """A held row (#697 keeps it on the roster) must not fail response
    validation. The DTO is shared by every session in the payload, so one
    rejected row 500s the coach's whole day, not just that class."""
    seed["enrollments"] = [
        *seed["enrollments"],
        Enrollment(
            enrollment_id="e-held",
            academy_id="test-academy",
            session_id="s-today-1",
            student_id="st-held",
            status="held",
            hold_return_on=date(2026, 6, 1),
        ),
    ]
    seed["students"] = [
        *seed["students"],
        Student(
            student_id="st-held",
            academy_id="test-academy",
            parent_id="p3",
            full_name="Held Hannah",
        ),
    ]
    use_cases = _build_use_cases(seed)
    app = _make_app(_coach_claims(), use_cases)
    with TestClient(app) as client:
        r = client.get("/api/v2/coach/today?date=2026-05-16")

    assert r.status_code == 200, r.text
    body = r.json()
    # Every session of the day still renders, not just the unaffected one.
    assert [s["session_id"] for s in body["sessions"]] == ["s-today-1", "s-today-2"]
    by_id = {entry["student_id"]: entry for entry in body["sessions"][0]["roster"]}
    assert set(by_id) == {"st1", "st2", "st-held"}
    assert by_id["st-held"]["enrollment_status"] == "held"
    assert by_id["st1"]["enrollment_status"] == "active"


# ---------- cancelled classes stay on the coach's day (#777) ----------


def test_coach_today_shows_cancelled_occurrence_with_reason(seed):
    """Issue #777: a cancelled class must stay on the coach's day, labelled
    with its status and reason. Dropping it silently is how a coach turns up
    to an empty court."""
    seed["occurrences"] = [
        *seed["occurrences"],
        SessionOccurrence(
            occurrence_id="occ-today-cancelled",
            academy_id="test-academy",
            session_id="occurrence-session-1",
            template_session_id="s-today-1",
            start_at=datetime(2026, 5, 16, 15, 0, tzinfo=UTC),
            end_at=datetime(2026, 5, 16, 16, 0, tzinfo=UTC),
            status="cancelled",
            cancellation_reason="Court flooded",
            is_billable=False,
            is_payable=False,
            scheduled_coach_id="coach-1",
        ),
    ]
    use_cases = _build_use_cases(seed)
    app = _make_app(_coach_claims(), use_cases)
    with TestClient(app) as client:
        r = client.get("/api/v2/coach/today?date=2026-05-16")

    assert r.status_code == 200, r.text
    by_occurrence = {s["occurrence_id"]: s for s in r.json()["sessions"]}
    assert "occ-today-cancelled" in by_occurrence
    cancelled = by_occurrence["occ-today-cancelled"]
    assert cancelled["status"] == "cancelled"
    assert cancelled["cancellation_reason"] == "Court flooded"
    assert by_occurrence["occ-today-1"]["status"] == "scheduled"
    assert by_occurrence["occ-today-1"]["cancellation_reason"] is None


def test_coach_today_trial_row_carries_request_id_and_outcome(seed):
    """People CRM L3a: a trial row names its trial request (the id the coach
    records Came / Didn't come against) and the outcome already recorded;
    other rows carry neither."""
    seed["students"] = [
        *seed["students"],
        Student(
            student_id="st-trial",
            academy_id="test-academy",
            parent_id="p3",
            full_name="Trial Kid",
        ),
    ]
    seed["occurrence_roster_entries"] = [
        OccurrenceRosterEntry(
            entry_id="ore-t",
            academy_id="test-academy",
            occurrence_id="occ-today-1",
            student_id="st-trial",
            source="trial",
            origin_request_id="tr-9",
            created_at=datetime(2026, 5, 15, 8, 0, tzinfo=UTC),
        )
    ]

    class _Outcomes:
        async def outcomes_for(self, request_ids):
            return {rid: "came" for rid in request_ids if rid == "tr-9"}

    use_cases = _build_use_cases(seed)
    use_cases.get_occurrence_roster._trial_outcomes = _Outcomes()  # type: ignore[union-attr]
    app = _make_app(_coach_claims(), use_cases)
    with TestClient(app) as client:
        r = client.get("/api/v2/coach/today?date=2026-05-16")
    assert r.status_code == 200, r.text
    by_id = {e["student_id"]: e for e in r.json()["sessions"][0]["roster"]}
    assert by_id["st-trial"]["entry_source"] == "trial"
    assert by_id["st-trial"]["trial_request_id"] == "tr-9"
    assert by_id["st-trial"]["trial_outcome"] == "came"
    assert by_id["st1"]["trial_request_id"] is None
    assert by_id["st1"]["trial_outcome"] is None


def test_coach_today_flags_sessions_whose_recap_is_saved(seed):
    use_cases = _build_use_cases(seed)
    asked: list[list[str]] = []

    async def recapped(occurrence_ids):
        asked.append(list(occurrence_ids))
        return {"occ-today-1"}

    use_cases.recapped_occurrence_ids = recapped
    with TestClient(_make_app(_coach_claims(), use_cases)) as client:
        body = client.get("/api/v2/coach/today?date=2026-05-16").json()
    saved = {s["occurrence_id"]: s["recap_saved"] for s in body["sessions"]}
    assert saved == {"occ-today-1": True, "occ-today-2": False}
    assert asked == [["occ-today-1", "occ-today-2"]]


def test_coach_today_survives_a_failed_recap_lookup(seed):
    use_cases = _build_use_cases(seed)

    async def broken(occurrence_ids):
        raise RuntimeError("mongo down")

    use_cases.recapped_occurrence_ids = broken
    with TestClient(_make_app(_coach_claims(), use_cases)) as client:
        r = client.get("/api/v2/coach/today?date=2026-05-16")
    assert r.status_code == 200, r.text
    assert all(s["recap_saved"] is False for s in r.json()["sessions"])


def test_coach_roster_row_carries_age_in_years_and_level_never_the_date_of_birth(seed):
    from types import SimpleNamespace

    from backend.v2.contexts.enrollment.domain.models import age_in_years
    from backend.v2.contexts.enrollment.domain.programs import AgeBand

    seed["students"] = [
        Student(
            student_id="st1",
            academy_id="test-academy",
            parent_id="p1",
            full_name="Alice",
            date_of_birth="2015-03-02",
        ),
        Student(student_id="st2", academy_id="test-academy", parent_id="p2", full_name="Bob"),
    ]
    seed["sessions"][0] = seed["sessions"][0].model_copy(
        update={"age_band": AgeBand(min_age=8, max_age=12)}
    )
    use_cases = _build_use_cases(seed)

    class _Levels:
        async def execute(self, student_ids, program_id):
            assert program_id == "prog-1"
            return {"st1": "Grip & Control"} if "st1" in student_ids else {}

    class _Program:
        async def execute(self):
            return SimpleNamespace(program_id="prog-1")

    use_cases.student_progress = SimpleNamespace(get_active_level_names=_Levels())
    use_cases.curriculum = SimpleNamespace(resolve_default_program=_Program())
    app = _make_app(_coach_claims(), use_cases)
    with TestClient(app) as client:
        r = client.get("/api/v2/coach/today?date=2026-05-16")

    assert r.status_code == 200, r.text
    assert "date_of_birth" not in r.text and "2015-03-02" not in r.text
    first = r.json()["sessions"][0]
    by_id = {entry["student_id"]: entry for entry in first["roster"]}
    assert by_id["st1"]["age_years"] == age_in_years("2015-03-02", date.today())
    assert isinstance(by_id["st1"]["age_years"], int)
    assert by_id["st1"]["level_name"] == "Grip & Control"
    assert by_id["st2"]["age_years"] is None and by_id["st2"]["level_name"] is None
    assert first["age_band"] == {"min_age": 8, "max_age": 12}


def test_coach_today_survives_a_failing_level_lookup(seed):
    from types import SimpleNamespace

    use_cases = _build_use_cases(seed)

    class _Broken:
        async def execute(self):
            raise RuntimeError("curriculum down")

    use_cases.student_progress = SimpleNamespace(get_active_level_names=None)
    use_cases.curriculum = SimpleNamespace(resolve_default_program=_Broken())
    app = _make_app(_coach_claims(), use_cases)
    with TestClient(app) as client:
        r = client.get("/api/v2/coach/today?date=2026-05-16")

    assert r.status_code == 200, r.text
    assert all(e["level_name"] is None for e in r.json()["sessions"][0]["roster"])


def test_age_in_years_counts_whole_birthdays():
    from backend.v2.contexts.enrollment.domain.models import age_in_years

    assert age_in_years("2015-12-01", date(2026, 11, 30)) == 10
    assert age_in_years("2015-12-01", date(2026, 12, 1)) == 11
    assert age_in_years(None, date(2026, 12, 1)) is None
    assert age_in_years("not a date", date(2026, 12, 1)) is None
