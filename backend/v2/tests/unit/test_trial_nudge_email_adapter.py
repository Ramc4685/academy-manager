"""The three templated nudge emails go to the parent through the gated user
send path, themed with the academy's brand, and report whether a retry is
worth it."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from backend.v2.composition.trial_nudges import TrialNudgeEmailAdapter
from backend.v2.contexts.communications.application.ports import (
    ResolvedRecipient,
    SendOutcome,
)
from backend.v2.contexts.communications.domain.email_category import EmailCategory
from backend.v2.contexts.enrollment.domain.models import Session, Student
from backend.v2.contexts.enrollment.domain.self_service import TrialRequest
from backend.v2.contexts.identity.domain.models import AcademyMembership, User
from backend.v2.contexts.onboarding.domain.models import Application, ChildProfile
from backend.v2.shared.tenancy import tenant_scope

pytestmark = pytest.mark.asyncio

ACADEMY_ID = "acad-1"
ACADEMY_DOC = {
    "academy_id": ACADEMY_ID,
    "display_name": "Floodlit Badminton",
    "slug": "floodlit",
    "email_reply_to": "hello@floodlit.example",
}


class _Audiences:
    def __init__(self, recipients: dict[str, ResolvedRecipient]) -> None:
        self._recipients = recipients

    async def resolve_selected_audience(self, audience):
        return [self._recipients[u] for u in audience.user_ids if u in self._recipients]


class _Memberships:
    def __init__(self, rows: dict[tuple[str, str], AcademyMembership] | None = None) -> None:
        self._rows = rows or {}

    async def get_membership(self, academy_id: str, user_id: str):
        return self._rows.get((academy_id, user_id))


class _Users:
    def __init__(self, users: dict[str, User] | None = None) -> None:
        self._users = users or {}

    async def get_by_id(self, user_id: str):
        return self._users.get(user_id)


class _Academies:
    async def find_by_id(self, academy_id: str):
        return ACADEMY_DOC if academy_id == ACADEMY_ID else None


class _Students:
    async def by_ids(self, student_ids):
        return [
            Student(student_id=s, academy_id=ACADEMY_ID, parent_id="parent-1", full_name="Mia Chen")
            for s in student_ids
            if s == "stu-1"
        ]


class _Sessions:
    async def get(self, session_id: str):
        if session_id != "sess-1":
            return None
        start = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)
        return Session(
            session_id="sess-1",
            academy_id=ACADEMY_ID,
            title="Juniors Monday",
            location="Court 3",
            start_at=start,
            end_at=start + timedelta(hours=1),
            coach_id="coach-1",
            capacity=12,
            amount_cents=0,
        )


class _Sender:
    def __init__(self, outcome: SendOutcome | None = None) -> None:
        self.outcome = outcome or SendOutcome(ok=True, provider_message_id="m1", failed_reason=None)
        self.calls: list[dict[str, Any]] = []

    async def send(self, **kwargs):
        self.calls.append(kwargs)
        return self.outcome


def _adapter(
    sender: _Sender | None = None,
    recipients: dict | None = None,
    memberships: _Memberships | None = None,
    users: _Users | None = None,
):
    sender = sender or _Sender()
    recipients = (
        {"parent-1": ResolvedRecipient(user_id="parent-1", email="p@example.com")}
        if recipients is None
        else recipients
    )
    return (
        TrialNudgeEmailAdapter(
            audiences=_Audiences(recipients),
            memberships=memberships or _Memberships(),
            users=users or _Users(),
            academies=_Academies(),
            students=_Students(),
            sessions=_Sessions(),
            sender=sender,
            frontend_url="https://app.courtmastr.com",
        ),
        sender,
    )


def _trial(**kwargs) -> TrialRequest:
    base = dict(
        request_id="t1",
        academy_id=ACADEMY_ID,
        parent_user_id="parent-1",
        student_ref="prospective",
        prospective_child_name="Ava <b>",
        requested_session_id="sess-1",
        preferred_start="2026-11-01",
        preferred_end="2026-11-30",
        status="approved",
        created_at=datetime(2026, 10, 20, tzinfo=UTC),
    )
    base.update(kwargs)
    return TrialRequest(**base)


async def test_reminder_names_child_class_local_time_and_place() -> None:
    adapter, sender = _adapter()
    local_start = datetime(2026, 11, 5, 9, 30, tzinfo=ZoneInfo("America/Chicago"))

    with tenant_scope(ACADEMY_ID):
        assert await adapter.trial_reminder(trial=_trial(), local_start=local_start) == "sent"

    (call,) = sender.calls
    assert call["recipient"].user_id == "parent-1"
    assert call["subject"] == "Reminder: Ava <b>'s free trial is tomorrow"
    assert call["category"] is EmailCategory.TRANSACTIONAL
    assert call["reply_to"] == "hello@floodlit.example"
    assert call["sender_name"] == "Floodlit Badminton"
    body = call["body"]
    assert "Ava &lt;b&gt;" in body and "<b>" not in body.split("Ava")[1][:10]
    assert "Juniors Monday" in body
    assert "Thursday, November 5 at 9:30 AM at Court 3" in body
    assert "Floodlit Badminton" in body  # themed shell


async def test_reminder_uses_the_rostered_students_name() -> None:
    adapter, sender = _adapter()
    trial = _trial(student_ref="existing_student", student_id="stu-1", prospective_child_name=None)
    with tenant_scope(ACADEMY_ID):
        await adapter.trial_reminder(trial=trial, local_start=datetime(2026, 11, 5, 9, tzinfo=UTC))
    assert sender.calls[0]["subject"] == "Reminder: Mia Chen's free trial is tomorrow"


async def test_no_show_is_a_campaign_with_a_link_to_request_again() -> None:
    adapter, sender = _adapter()
    with tenant_scope(ACADEMY_ID):
        assert await adapter.trial_no_show(trial=_trial(status="completed")) == "sent"
    (call,) = sender.calls
    assert call["category"] is EmailCategory.CAMPAIGN
    assert "We missed" in call["subject"]
    assert 'href="https://floodlit.courtmastr.com/parent/requests"' in call["body"]


async def test_checkout_recovery_links_back_to_the_wizard() -> None:
    adapter, sender = _adapter()
    application = Application(
        application_id="app-1",
        academy_id=ACADEMY_ID,
        parent_user_id="parent-1",
        parent_email="p@example.com",
        status="CHECKOUT_EXPIRED",
        child_profile=ChildProfile(first_name="Leo"),
        selected_session_id="sess-1",
        expires_at=datetime(2026, 11, 1, tzinfo=UTC),
        created_at=datetime(2026, 10, 25, tzinfo=UTC),
        updated_at=datetime(2026, 11, 2, tzinfo=UTC),
    )
    with tenant_scope(ACADEMY_ID):
        assert await adapter.checkout_recovery(application=application) == "sent"
    (call,) = sender.calls
    assert call["subject"] == "Finish Leo's registration"
    assert call["category"] is EmailCategory.CAMPAIGN
    assert "Juniors Monday" in call["body"]
    # Neither state can be resumed, so the link says start again, not resume.
    assert (
        'href="https://floodlit.courtmastr.com/parent/onboarding">Start the registration again</a>'
        in call["body"]
    )
    assert "where you left off" not in call["body"]


async def test_provider_failure_is_retried_but_suppression_is_skipped() -> None:
    failed, failed_sender = _adapter(
        _Sender(SendOutcome(ok=False, provider_message_id=None, failed_reason="boom"))
    )
    suppressed, _ = _adapter(
        _Sender(
            SendOutcome(
                ok=False, provider_message_id=None, failed_reason="unsubscribed", suppressed=True
            )
        )
    )
    start = datetime(2026, 11, 5, 9, tzinfo=UTC)
    with tenant_scope(ACADEMY_ID):
        assert await failed.trial_reminder(trial=_trial(), local_start=start) == "failed"
        assert await suppressed.trial_reminder(trial=_trial(), local_start=start) == "skipped"
    assert len(failed_sender.calls) == 1


async def test_a_parent_without_an_address_is_skipped_not_retried() -> None:
    adapter, sender = _adapter(recipients={})
    with tenant_scope(ACADEMY_ID):
        assert await adapter.trial_no_show(trial=_trial(status="completed")) == "skipped"
    assert sender.calls == []


async def test_a_nameless_prospective_child_reads_naturally_mid_sentence() -> None:
    adapter, sender = _adapter()
    with tenant_scope(ACADEMY_ID):
        await adapter.trial_no_show(trial=_trial(status="completed", prospective_child_name=" "))
    assert sender.calls[0]["subject"] == "We missed your child at the trial"
    assert "racquet" not in sender.calls[0]["body"]


async def test_a_parent_who_joined_this_academy_second_is_found_through_their_membership() -> None:
    # ensure_parent_user keeps the first academy on the users row, so the
    # tenant-local audience query finds nobody here; the membership proves the tie.
    member = AcademyMembership(
        membership_id="m1", academy_id=ACADEMY_ID, user_id="parent-2", roles=("parent",)
    )
    user = User(user_id="parent-2", email="second@example.com", display_name="Sam")
    adapter, sender = _adapter(
        recipients={},
        memberships=_Memberships({(ACADEMY_ID, "parent-2"): member}),
        users=_Users({"parent-2": user}),
    )
    with tenant_scope(ACADEMY_ID):
        assert await adapter.trial_no_show(trial=_trial(parent_user_id="parent-2")) == "sent"
    assert sender.calls[0]["recipient"].email == "second@example.com"


async def test_a_user_with_no_membership_here_is_not_mailed() -> None:
    user = User(user_id="parent-2", email="second@example.com", display_name="Sam")
    adapter, sender = _adapter(recipients={}, users=_Users({"parent-2": user}))
    with tenant_scope(ACADEMY_ID):
        assert await adapter.trial_no_show(trial=_trial(parent_user_id="parent-2")) == "skipped"
    assert sender.calls == []
