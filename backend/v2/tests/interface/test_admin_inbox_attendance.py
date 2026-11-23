"""Admin Inbox "Attendance" tab: missing marks and corrections, linked to the class date."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from backend.v2.contexts.coaching.application.ports import ReviewCorrection, ReviewOccurrence
from backend.v2.contexts.coaching.application.use_cases.attendance_review import (
    AttendanceReview,
)

START = datetime(2026, 11, 18, 22, 0, tzinfo=UTC)


class _FakeReview:
    def __init__(self, missing: list[ReviewOccurrence], corrections: list[ReviewCorrection]):
        self._review = AttendanceReview(missing=missing, corrections=corrections)

    async def missing(self) -> list[ReviewOccurrence]:
        return self._review.missing

    async def execute(self) -> AttendanceReview:
        return self._review


def _missing(occurrence_id: str = "occ 1/a") -> ReviewOccurrence:
    return ReviewOccurrence(
        occurrence_id=occurrence_id,
        session_id="sess-juniors",
        session_name="Juniors",
        start_at=START,
        status="scheduled",
        enrolled_count=6,
        marked_count=0,
    )


def _correction() -> ReviewCorrection:
    return ReviewCorrection(
        attendance_id="att-1",
        occurrence_id="occ-2",
        session_id="sess-juniors",
        session_name="Juniors",
        start_at=START - timedelta(days=1),
        student_id="stu-1",
        student_name="Ava Pine",
        status="absent",
        previous_status="present",
        corrected_at=START,
        corrected_by_name="Coach Lee",
        reason="Left early",
    )


def test_attendance_tab_lists_items_with_class_date_links(admin_client):
    admin_client.use_cases.list_attendance_review = _FakeReview([_missing()], [_correction()])

    r = admin_client.get("/api/v2/admin/inbox/attendance")

    assert r.status_code == 200, r.text
    body = r.json()
    [missing] = body["missing"]
    assert missing["session_name"] == "Juniors"
    assert missing["enrolled_count"] == 6
    # Ids are URL-encoded so an odd id cannot break out of the query string.
    assert missing["href"] == "/admin/sessions/sess-juniors?tab=dates&occurrence=occ%201%2Fa"
    [correction] = body["corrections"]
    assert correction["student_name"] == "Ava Pine"
    assert (correction["previous_status"], correction["status"]) == ("present", "absent")
    assert correction["corrected_by_name"] == "Coach Lee"
    assert correction["href"] == "/admin/sessions/sess-juniors?tab=dates&occurrence=occ-2"
    assert "student_id" not in correction


def test_attendance_badge_counts_missing_dates_only(admin_client):
    admin_client.use_cases.list_attendance_review = _FakeReview(
        [_missing("occ-1"), _missing("occ-2")], [_correction()] * 5
    )

    r = admin_client.get("/api/v2/admin/inbox/counts")

    assert r.status_code == 200, r.text
    # Corrections are review-only (like absences), so only missing dates count.
    assert r.json()["counts"]["attendance"] == 2


def test_attendance_tab_is_empty_without_a_reader(admin_client):
    admin_client.use_cases.list_attendance_review = None

    r = admin_client.get("/api/v2/admin/inbox/attendance")

    assert r.status_code == 200, r.text
    assert r.json() == {"missing": [], "corrections": []}


def test_dashboard_attention_points_at_the_attendance_tab(admin_client):
    admin_client.use_cases.list_attendance_review = _FakeReview([_missing()], [])

    r = admin_client.get("/api/v2/admin/dashboard/attention")

    assert r.status_code == 200, r.text
    item = {i["attention_id"]: i for i in r.json()["items"]}["missing-attendance"]
    assert item["href"] == "/admin/inbox?tab=attendance"
    assert item["count"] == 1
    assert item["detail"] == "1 class date has no attendance marks."


def test_dashboard_has_no_attendance_card_when_everything_is_marked(admin_client):
    admin_client.use_cases.list_attendance_review = _FakeReview([], [_correction()])

    r = admin_client.get("/api/v2/admin/dashboard/attention")

    assert "missing-attendance" not in {i["attention_id"] for i in r.json()["items"]}


def test_attendance_tab_is_admin_only(coach_on_admin_client):
    assert coach_on_admin_client.get("/api/v2/admin/inbox/attendance").status_code == 404
