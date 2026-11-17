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

from backend.v2.contexts.communications.application.ports import ResolvedRecipient, SendOutcome
from backend.v2.contexts.enrollment.application.ports import ClosedClassDate, ClosureNotice
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
        notice = await adapter.academy_closed(dates=dates, reason="Thanksgiving", actor_id="a-1")

    assert notice == ClosureNotice(families_affected=1, families_emailed=1, failed=False)
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


def _closure_adapter(sender: Any, *, parent_email: str | None) -> Any:
    adapter = _adapter(
        sessions=FakeSessions(rows={"sess-1": _session()}),
        audiences=FakeAudiences(
            coaches={},
            users={"par-1": ResolvedRecipient(user_id="par-1", email=parent_email)},
        ),
        sender=sender,
        roster=FakeRoster(),
        students=ParentStudents(),  # type: ignore[arg-type]
    )
    adapter._push = RecordingPush()  # type: ignore[assignment]
    return adapter


_ONE_DATE = [
    ClosedClassDate(
        session_id="sess-1",
        start_at=datetime(2026, 11, 26, 23, 0, tzinfo=UTC),
        one_time_student_ids=("st-1",),
    )
]


@pytest.mark.asyncio
async def test_a_roster_only_parent_with_no_email_counts_as_affected_not_emailed() -> None:
    adapter = _closure_adapter(FakeSender(), parent_email=None)
    with tenant_scope(ACADEMY):
        notice = await adapter.academy_closed(dates=_ONE_DATE, reason="Snow", actor_id="a-1")
    assert notice == ClosureNotice(families_affected=1, families_emailed=0, failed=False)


@pytest.mark.asyncio
async def test_a_failing_send_never_raises_and_reports_the_notice_failed() -> None:
    adapter = _closure_adapter(FakeSender(), parent_email="parent@x.com")

    async def boom(**kwargs: Any) -> None:
        raise RuntimeError("smtp down")

    adapter._send_one = boom  # type: ignore[method-assign]
    with tenant_scope(ACADEMY):
        notice = await adapter.academy_closed(dates=_ONE_DATE, reason="Snow", actor_id="a-1")
    assert notice.failed is True and notice.families_emailed == 0


class RefusingSender:
    """A provider that answers "not delivered" instead of raising."""

    def __init__(self, *, suppressed: bool) -> None:
        self.suppressed = suppressed

    async def send(self, **kwargs: Any) -> SendOutcome:
        return SendOutcome(
            ok=False,
            provider_message_id=None,
            failed_reason="suppressed" if self.suppressed else "email_delivery_failed",
            suppressed=self.suppressed,
        )


@pytest.mark.asyncio
async def test_a_provider_refusal_is_not_counted_as_emailed_and_flags_the_notice() -> None:
    adapter = _closure_adapter(RefusingSender(suppressed=False), parent_email="parent@x.com")
    with tenant_scope(ACADEMY):
        notice = await adapter.academy_closed(dates=_ONE_DATE, reason="Snow", actor_id="a-1")
    assert notice == ClosureNotice(families_affected=1, families_emailed=0, failed=True)


@pytest.mark.asyncio
async def test_a_suppressed_address_is_not_emailed_but_is_not_a_failure() -> None:
    adapter = _closure_adapter(RefusingSender(suppressed=True), parent_email="parent@x.com")
    with tenant_scope(ACADEMY):
        notice = await adapter.academy_closed(dates=_ONE_DATE, reason="Snow", actor_id="a-1")
    assert notice == ClosureNotice(families_affected=1, families_emailed=0, failed=False)
