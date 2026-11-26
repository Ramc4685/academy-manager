"""``POST /admin/session-occurrences/{id}/credit-missed`` (#1207)."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from backend.v2.contexts.enrollment.domain.models import SessionOccurrence

BASE = "/api/v2/admin/session-occurrences"


@pytest.fixture(autouse=True)
def _past_dates(admin_seed):
    """One past date nobody attended, one held (conftest marks st-1 present on it)."""
    for past_id, day in (("occ-admin-missed", 9), ("occ-admin-held", 2)):
        admin_seed["occurrences"].rows[past_id] = SessionOccurrence(
            occurrence_id=past_id,
            academy_id="acad",
            session_id="sess-1",
            start_at=datetime(2026, 5, day, 9, 0, tzinfo=UTC),
            end_at=datetime(2026, 5, day, 10, 30, tzinfo=UTC),
            status="scheduled",
            scheduled_coach_id="coach-1",
        )


def test_preview_lists_families_and_writes_nothing(admin_client):
    r = admin_client.post(
        f"{BASE}/occ-admin-missed/credit-missed", json={"reason": "gym closed", "dry_run": True}
    )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dry_run"] is True
    assert body["families"][0]["enrollment_id"] == "enr-1"
    assert body["families"][0]["amount_cents"] == 3000
    assert body["credit_total_cents"] == 3000
    rows = admin_client.get("/api/v2/admin/sessions/sess-1/occurrences").json()["occurrences"]
    assert next(o for o in rows if o["occurrence_id"] == "occ-admin-missed")["status"] == (
        "scheduled"
    )


def test_confirm_marks_the_past_date_no_class_and_reports_the_credits(admin_client):
    r = admin_client.post(f"{BASE}/occ-admin-missed/credit-missed", json={"reason": "gym closed"})

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dry_run"] is False
    assert body["credits_issued"] == 1
    assert body["credit_total_cents"] == 3000
    rows = admin_client.get("/api/v2/admin/sessions/sess-1/occurrences").json()["occurrences"]
    row = next(o for o in rows if o["occurrence_id"] == "occ-admin-missed")
    assert row["status"] == "cancelled" and row["cancellation_reason"] == "gym closed"

    again = admin_client.post(f"{BASE}/occ-admin-missed/credit-missed", json={"reason": "x"})
    assert again.status_code == 409


def test_a_date_with_students_present_is_refused(admin_client):
    r = admin_client.post(
        f"{BASE}/occ-admin-held/credit-missed", json={"reason": "gym closed", "dry_run": True}
    )
    assert r.status_code == 409
    assert "present" in r.text


def test_a_future_date_is_refused(admin_client):
    r = admin_client.post(f"{BASE}/occ-admin-1/credit-missed", json={"reason": "gym closed"})
    assert r.status_code == 409


def test_reason_is_required(admin_client):
    r = admin_client.post(f"{BASE}/occ-admin-missed/credit-missed", json={"reason": ""})
    assert r.status_code == 422


def test_other_personas_get_404(coach_on_admin_client, parent_on_admin_client):
    for client in (coach_on_admin_client, parent_on_admin_client):
        r = client.post(f"{BASE}/occ-admin-missed/credit-missed", json={"reason": "x"})
        assert r.status_code == 404


class _OneSeatRoster:
    async def remove_for_occurrence(self, occurrence_id: str) -> list[SimpleNamespace]:
        return [SimpleNamespace(student_id="st-makeup")]


class _TwoMakeups:
    async def reopen_for_target_occurrence(self, occurrence_id: str, **_: object) -> int:
        return 2


def test_confirm_reports_the_seat_changes_it_made(admin_client):
    """#1209 item 4: one-time seats removed and make-ups reopened are not dropped."""
    cancel = admin_client.use_cases.cancel_session_occurrence
    cancel._roster = _OneSeatRoster()
    cancel._makeups = _TwoMakeups()

    r = admin_client.post(f"{BASE}/occ-admin-missed/credit-missed", json={"reason": "gym closed"})

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["roster_entries_removed"] == 1
    assert body["makeups_reopened"] == 2
    assert body["trials_reopened"] == 0
