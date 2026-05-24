"""Admin waitlist BFF — happy + wrong-persona 404."""

from __future__ import annotations

from datetime import UTC, datetime

from backend.v2.contexts.enrollment.domain.models import Enrollment
from backend.v2.contexts.enrollment.domain.models_extra import WaitlistEntry
from backend.v2.interfaces.admin.waitlist_routes import _normalize_waitlist_entries


def _add(seed, waitlist_id: str, joined_at: datetime, status: str = "waiting"):
    seed["waitlist"].entries[waitlist_id] = WaitlistEntry(
        waitlist_id=waitlist_id,
        academy_id="acad",
        session_id="sess-1",
        student_id=f"st-{waitlist_id}",
        parent_id=f"p-{waitlist_id}",
        joined_at=joined_at,
        status=status,  # type: ignore[arg-type]
    )


def test_list_waitlist_returns_entries(admin_client):
    _add(admin_client.seed, "w1", datetime(2026, 5, 16, 8, 0, tzinfo=UTC))
    _add(admin_client.seed, "w2", datetime(2026, 5, 16, 9, 0, tzinfo=UTC))
    r = admin_client.get("/api/v2/admin/sessions/sess-1/waitlist")
    assert r.status_code == 200, r.text
    body = r.json()
    ids = {e["waitlist_id"] for e in body["entries"]}
    assert ids == {"w1", "w2"}


def test_list_global_waitlist_groups_waiting_entries(admin_client):
    _add(admin_client.seed, "w1", datetime(2026, 5, 16, 8, 0, tzinfo=UTC))
    _add(admin_client.seed, "w2", datetime(2026, 5, 16, 9, 0, tzinfo=UTC))

    r = admin_client.get("/api/v2/admin/waitlist")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_waitlisted"] == 2
    assert body["sessions"][0]["session_id"] == "sess-1"
    assert [entry["waitlist_id"] for entry in body["sessions"][0]["entries"]] == [
        "w1",
        "w2",
    ]


def test_normalize_waitlist_recomputes_positions_after_filtering():
    joined_at = datetime(2026, 5, 16, 8, 0, tzinfo=UTC)

    rows = _normalize_waitlist_entries(
        [
            {
                "waitlist_id": "promoted",
                "session_id": "sess-1",
                "student_id": "st-promoted",
                "parent_id": "p-promoted",
                "joined_at": joined_at,
                "status": "promoted",
                "position": 1,
            },
            {
                "waitlist_id": "waiting",
                "session_id": "sess-1",
                "student_id": "st-waiting",
                "parent_id": "p-waiting",
                "joined_at": joined_at,
                "status": "waiting",
                "position": 2,
            },
        ]
    )

    assert [row.waitlist_id for row in rows] == ["waiting"]
    assert [row.position for row in rows] == [1]


def test_list_waitlist_wrong_persona_404(coach_on_admin_client):
    r = coach_on_admin_client.get("/api/v2/admin/sessions/sess-1/waitlist")
    assert r.status_code == 404


def test_promote_picks_oldest_fifo(admin_client):
    older = datetime(2026, 5, 16, 8, 0, tzinfo=UTC)
    newer = datetime(2026, 5, 16, 9, 0, tzinfo=UTC)
    _add(admin_client.seed, "older", older)
    _add(admin_client.seed, "newer", newer)
    r = admin_client.post("/api/v2/admin/sessions/sess-1/waitlist/promote")
    assert r.status_code == 200, r.text
    assert r.json()["promoted_waitlist_id"] == "older"
    assert admin_client.seed["waitlist"].entries["older"].status == "promoted"


def test_promote_moves_oldest_waitlist_entry_to_roster(admin_client):
    _add(admin_client.seed, "older", datetime(2026, 5, 16, 8, 0, tzinfo=UTC))
    _add(admin_client.seed, "newer", datetime(2026, 5, 16, 9, 0, tzinfo=UTC))

    r = admin_client.post("/api/v2/admin/sessions/sess-1/waitlist/promote")

    assert r.status_code == 200, r.text
    enrollments = list(admin_client.seed["enrollments"].rows.values())
    assert len(enrollments) == 1
    assert enrollments[0].session_id == "sess-1"
    assert enrollments[0].student_id == "st-older"
    assert enrollments[0].status == "active"

    roster = admin_client.get("/api/v2/admin/sessions/sess-1/enrollments").json()
    assert [entry["student_id"] for entry in roster["enrollments"]] == ["st-older"]

    waitlist = admin_client.get("/api/v2/admin/sessions/sess-1/waitlist").json()
    assert [entry["waitlist_id"] for entry in waitlist["entries"]] == ["newer"]


def test_promote_resumes_existing_paused_enrollment_without_duplicate(admin_client):
    admin_client.seed["enrollments"].rows["enr-paused"] = Enrollment(
        enrollment_id="enr-paused",
        academy_id="acad",
        session_id="sess-1",
        student_id="st-older",
        status="paused",
    )
    _add(admin_client.seed, "older", datetime(2026, 5, 16, 8, 0, tzinfo=UTC))

    r = admin_client.post("/api/v2/admin/sessions/sess-1/waitlist/promote")

    assert r.status_code == 200, r.text
    enrollments = list(admin_client.seed["enrollments"].rows.values())
    assert len(enrollments) == 1
    assert enrollments[0].enrollment_id == "enr-paused"
    assert enrollments[0].status == "active"


def test_promote_empty_waitlist_returns_null(admin_client):
    r = admin_client.post("/api/v2/admin/sessions/sess-1/waitlist/promote")
    assert r.status_code == 200
    assert r.json()["promoted_waitlist_id"] is None


def test_skip_marks_status(admin_client):
    _add(admin_client.seed, "w1", datetime(2026, 5, 16, 8, 0, tzinfo=UTC))
    r = admin_client.post("/api/v2/admin/waitlist/w1/skip")
    assert r.status_code == 204
    assert admin_client.seed["waitlist"].entries["w1"].status == "skipped"


def test_remove_marks_status(admin_client):
    _add(admin_client.seed, "w1", datetime(2026, 5, 16, 8, 0, tzinfo=UTC))
    r = admin_client.delete("/api/v2/admin/waitlist/w1")
    assert r.status_code == 204
    assert admin_client.seed["waitlist"].entries["w1"].status == "removed"


def test_promote_wrong_persona_404(parent_on_admin_client):
    r = parent_on_admin_client.post("/api/v2/admin/sessions/sess-1/waitlist/promote")
    assert r.status_code == 404
