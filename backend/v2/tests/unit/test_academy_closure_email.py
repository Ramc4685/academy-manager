"""Academy closure notice: one email per family and per staff member (L12).

A family losing several dates gets ONE email listing all of them, and only
the dates billing actually credited say so. The staff copy carries the
billing warning when a date's sync did not run.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from backend.v2.contexts.communications.application.ports import ResolvedRecipient
from backend.v2.contexts.enrollment.application.ports import ClosedClassDate
from backend.v2.shared.tenancy import tenant_scope
from backend.v2.tests.unit.test_parent_push_hookups import RecordingPush
from backend.v2.tests.unit.test_roster_alert_adapter import (
    ACADEMY,
    FakeAudiences,
    FakeRoster,
    FakeSender,
    FakeSessions,
    _adapter,
    _session,
)


class ParentStudents:
    async def by_ids(self, student_ids: list[str]) -> list[Any]:
        return [SimpleNamespace(full_name="Alice Nguyen", parent_id="par-1") for _ in student_ids]


@pytest.mark.asyncio
async def test_one_email_per_family_lists_every_closed_date() -> None:
    sender, push = FakeSender(), RecordingPush()
    adapter = _adapter(
        sessions=FakeSessions(rows={"sess-1": _session()}),
        audiences=FakeAudiences(
            coaches={"sess-1": [ResolvedRecipient(user_id="coach-1", email="coach@x.com")]},
            users={"par-1": ResolvedRecipient(user_id="par-1", email="parent@x.com")},
        ),
        sender=sender,
        roster=FakeRoster(),
        students=ParentStudents(),  # type: ignore[arg-type]
    )
    adapter._push = push  # type: ignore[assignment]
    dates = [
        ClosedClassDate(
            session_id="sess-1",
            start_at=datetime(2026, 11, 30, 23, 0, tzinfo=UTC),
            one_time_student_ids=("st-1",),
        ),
        ClosedClassDate(
            session_id="sess-1",
            start_at=datetime(2026, 11, 26, 23, 0, tzinfo=UTC),
            one_time_student_ids=("st-1",),
            credited_student_ids=("st-1",),
            billing_warning="Billing did not run for this cancellation.",
        ),
    ]
    with tenant_scope(ACADEMY):
        families = await adapter.academy_closed(dates=dates, reason="Thanksgiving", actor_id="a-1")

    assert families == 1
    parent_mail = [row for row in sender.sent if row["user_id"] == "par-1"]
    assert len(parent_mail) == 1
    body = parent_mail[0]["body"]
    assert parent_mail[0]["subject"].startswith("Classes cancelled: 2 class dates")
    # Sorted by date, and only the credited date promises a credit.
    assert body.index("November 26") < body.index("November 30")
    assert body.count("credited to your account") == 1
    assert "Billing did not run" not in body
    assert len(push.sent) == 1

    coach_mail = [row for row in sender.sent if row["user_id"] == "coach-1"]
    assert len(coach_mail) == 1
    assert "Billing did not run" in coach_mail[0]["body"]
