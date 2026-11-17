"""``POST /admin/closures`` — academy-wide closure dates (L12)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from backend.v2.contexts.enrollment.application.use_cases.close_academy_dates import (
    CloseAcademyDatesResult,
    ClosureDate,
)

URL = "/api/v2/admin/closures"
BODY = {"start_date": "2026-11-26", "end_date": "2026-11-29", "reason": "Thanksgiving"}


class _RecordingClose:
    def __init__(self) -> None:
        self.commands: list[Any] = []

    async def execute(self, cmd: Any) -> CloseAcademyDatesResult:
        self.commands.append(cmd)
        return CloseAcademyDatesResult(
            dates=(
                ClosureDate(
                    occurrence_id="occ-1",
                    session_id="sess-1",
                    start_at=datetime(2026, 11, 26, 23, tzinfo=UTC),
                    status="cancelled",
                    credits_issued=2,
                    billing_warning="Billing did not run.",
                ),
            ),
            cancelled=1,
            credits_issued=2,
            families_affected=3,
            families_notified=2,
            notice_failed=True,
        )


def test_closure_converts_local_dates_to_the_academy_day_bounds(admin_client):
    close = _RecordingClose()
    admin_client.use_cases.close_academy_dates = close

    r = admin_client.post(URL, json=BODY)

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["cancelled"] == 1 and body["families_notified"] == 2
    assert body["families_affected"] == 3 and body["notice_failed"] is True
    assert body["dates"][0]["billing_warning"] == "Billing did not run."
    assert body["timezone"] == "America/Chicago"
    assert "session_title" in body["dates"][0]
    cmd = close.commands[0]
    # Chicago midnight on the first day, through midnight after the last day.
    assert cmd.start_at.astimezone(UTC) == datetime(2026, 11, 26, 6, tzinfo=UTC)
    assert cmd.end_at.astimezone(UTC) == datetime(2026, 11, 30, 6, tzinfo=UTC)
    assert cmd.actor_id and cmd.notify is True and cmd.dry_run is False


def test_closure_is_503_when_unwired(admin_client):
    admin_client.use_cases.close_academy_dates = None
    assert admin_client.post(URL, json=BODY).status_code == 503


def test_closure_needs_a_reason(admin_client):
    admin_client.use_cases.close_academy_dates = _RecordingClose()
    assert admin_client.post(URL, json={**BODY, "reason": ""}).status_code == 422


def test_coach_persona_cannot_close_the_academy(coach_on_admin_client):
    assert coach_on_admin_client.post(URL, json=BODY).status_code == 404
