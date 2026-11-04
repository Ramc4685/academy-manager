"""Mobile M3: the four parent emails that also push to the family's phone.

Owner-confirmed list (2026-11-04): class date cancelled, waitlist seat offered,
urgent announcement, payment due / past due. Each push follows its email, goes
to the same family user, and carries an in-app ``url`` the shell opens on tap.
Nothing else pushes: the waitlist "offer expired" mail and routine
announcements stay email-only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from backend.v2.composition.dues_reminders import compose_dues_reminders
from backend.v2.composition.session_announcements import SessionAnnouncementService
from backend.v2.contexts.billing.application.use_cases.admin_payment_ops import (
    SendDuesRemindersCommand,
)
from backend.v2.contexts.communications.application.ports import ResolvedRecipient, SendOutcome
from backend.v2.shared.comms import CommsService
from backend.v2.shared.tenancy import tenant_scope
from backend.v2.tests.interface.test_session_announcements import (
    _FakeAcademies as _AnnouncementAcademies,
)
from backend.v2.tests.interface.test_session_announcements import (
    _FakeAudiences as _SessionAudiences,
)
from backend.v2.tests.interface.test_session_announcements import (
    _FakeMessageRepo,
    _FakeUsers,
    _RecordingSendPort,
)
from backend.v2.tests.interface.test_session_announcements import (
    _FakeSessions as _AnnouncementSessions,
)
from backend.v2.tests.interface.test_session_announcements import (
    _session as _announcement_session,
)
from backend.v2.tests.unit.test_roster_alert_adapter import (
    ACADEMY,
    FakeAudiences,
    FakeRoster,
    FakeSender,
    FakeSessions,
    _adapter,
    _session,
)


@dataclass
class RecordingPush:
    sent: list[dict[str, Any]] = field(default_factory=list)

    async def execute(self, **kwargs: Any) -> None:
        self.sent.append(kwargs)


@dataclass
class ParentStudents:
    """Students that know their parent, so the cancellation audience resolves."""

    async def by_ids(self, student_ids: list[str]) -> list[Any]:
        return [SimpleNamespace(full_name="Alice Nguyen", parent_id="par-1") for _ in student_ids]


def _roster_adapter(push: RecordingPush, sender: FakeSender | None = None):
    adapter = _adapter(
        sessions=FakeSessions(rows={"sess-1": _session()}),
        audiences=FakeAudiences(
            users={"par-1": ResolvedRecipient(user_id="par-1", email="parent@x.com")}
        ),
        sender=sender or FakeSender(),
        roster=FakeRoster(),
        students=ParentStudents(),  # type: ignore[arg-type]
    )
    adapter._push = push  # type: ignore[assignment]
    return adapter


@pytest.mark.asyncio
async def test_a_cancelled_class_date_pushes_each_family_after_the_email() -> None:
    push, sender = RecordingPush(), FakeSender()
    with tenant_scope(ACADEMY):
        await _roster_adapter(push, sender).occurrence_cancelled(
            session_id="sess-1",
            occurrence_id="occ-1",
            start_at=datetime(2026, 9, 3, 23, 0, tzinfo=UTC),
            reason="Gym closed",
            actor_id="admin-1",
            extra_student_ids=("st-1",),
        )

    assert [row["user_id"] for row in sender.sent] == ["par-1"]
    assert len(push.sent) == 1
    sent = push.sent[0]
    assert sent["academy_id"] == ACADEMY
    assert sent["user_id"] == "par-1"
    assert sent["title"] == "BLNO Badminton"
    assert sent["body"].startswith("Beginner Badminton on ")
    assert sent["body"].endswith("is cancelled.")
    assert sent["data"] == {"url": "/parent"}


@pytest.mark.asyncio
async def test_a_waitlist_offer_pushes_a_claim_link_but_its_expiry_does_not() -> None:
    push = RecordingPush()
    adapter = _roster_adapter(push)
    with tenant_scope(ACADEMY):
        await adapter.waitlist_offer_made(
            waitlist_id="wl 1",
            session_id="sess-1",
            student_id="st-1",
            parent_user_id="par-1",
            offer_expires_at=datetime(2026, 9, 17, 17, 0, tzinfo=UTC),
        )
        await adapter.waitlist_offer_expired(
            waitlist_id="wl 1", session_id="sess-1", student_id="st-1", parent_user_id="par-1"
        )

    assert len(push.sent) == 1
    sent = push.sent[0]
    assert sent["user_id"] == "par-1"
    assert "A seat opened in Beginner Badminton for Alice Nguyen." in sent["body"]
    # 17:00 UTC is noon in the academy's Chicago clock.
    assert sent["body"].endswith("Claim it by Thu 17 Sep, 12:00 PM.")
    assert sent["data"] == {"url": "/parent/requests?offer=wl%201"}


@pytest.mark.asyncio
async def test_without_a_push_sender_the_emails_go_out_unchanged() -> None:
    sender = FakeSender()
    adapter = _roster_adapter(RecordingPush(), sender)
    adapter._push = None
    with tenant_scope(ACADEMY):
        await adapter.occurrence_cancelled(
            session_id="sess-1",
            occurrence_id="occ-1",
            start_at=datetime(2026, 9, 3, 23, 0, tzinfo=UTC),
            reason="Gym closed",
            actor_id="admin-1",
            extra_student_ids=("st-1",),
        )
    assert [row["user_id"] for row in sender.sent] == ["par-1"]


def _announcements(push: RecordingPush) -> SessionAnnouncementService:
    return SessionAnnouncementService(
        comms=CommsService(messages=_FakeMessageRepo(), academy_id="acad"),  # type: ignore[arg-type]
        sessions=_AnnouncementSessions({"sess-1": _announcement_session()}),
        academies=_AnnouncementAcademies(),
        users=_FakeUsers({"adm-1": "Priya Admin"}),
        audiences=_SessionAudiences(  # type: ignore[arg-type]
            [ResolvedRecipient("p1", "p1@example.com"), ResolvedRecipient("p2", "p2@example.com")]
        ),
        sender=_RecordingSendPort(),
        push=push,  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_an_urgent_announcement_pushes_every_family_and_a_routine_one_does_not() -> None:
    push = RecordingPush()
    service = _announcements(push)
    long_body = "No class tonight.\n\nThe gym lost power. " + "More detail. " * 20
    with tenant_scope("acad"):
        await service.post(
            session_id="sess-1", author_id="adm-1", author_persona="admin", body="Routine note."
        )
        assert push.sent == []
        await service.post(
            session_id="sess-1",
            author_id="adm-1",
            author_persona="admin",
            body=long_body,
            urgent=True,
        )

    assert [row["user_id"] for row in push.sent] == ["p1", "p2"]
    sent = push.sent[0]
    assert sent["title"] == "Junior A"
    assert sent["body"].startswith("No class tonight. The gym lost power.")
    assert len(sent["body"]) <= 140 and sent["body"].endswith("…")
    assert sent["data"] == {"url": "/parent/messages"}


class _DuesAcademies:
    async def get_academy_name(self, academy_id: str) -> str | None:
        return "BLNO Badminton"

    async def find_by_id(self, academy_id: str) -> dict[str, Any] | None:
        return {"display_name": "BLNO Badminton"}


class _DuesUsers:
    async def get_by_id(self, user_id: str) -> Any:
        email = {"par-1": "parent@x.com", "par-2": ""}.get(user_id)
        return SimpleNamespace(email=email, display_name="Pat") if email is not None else None


class _OkEmail:
    async def send(self, **_kw: Any) -> SendOutcome:
        return SendOutcome(ok=True, provider_message_id="m-1", failed_reason=None)


@pytest.mark.asyncio
async def test_a_dues_reminder_pushes_only_parents_whose_email_went_out() -> None:
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["parent-push"]
    for user_id in ("par-1", "par-2"):
        await db["academy_memberships"].insert_one(
            {"academy_id": ACADEMY, "user_id": user_id, "roles": ["parent"], "status": "active"}
        )
    rows = [
        {"parent_id": "par-1", "total_due_cents": 12500, "pending_count": 2},
        # No email on file: skipped, so no push either.
        {"parent_id": "par-2", "total_due_cents": 4000, "pending_count": 1},
    ]

    async def _list_dues() -> list[dict[str, Any]]:
        return rows

    async def _pay_link(academy_id: str) -> tuple[str | None, str]:
        return "https://blno.example/parent/payments", "BLNO Badminton"

    push = RecordingPush()
    bundle = compose_dues_reminders(
        db,
        academies=_DuesAcademies(),
        users=_DuesUsers(),
        email_sender=_OkEmail(),
        email_sender_is_real=True,
        ledger=None,
        billing_counters=None,
        billing_settings=None,
        parent_payments_link=_pay_link,
        list_dues_followup=_list_dues,
        generate_invoice_artifact=None,  # type: ignore[arg-type]
        push=push,  # type: ignore[arg-type]
    )
    with tenant_scope(ACADEMY):
        result = await bundle.send_dues_reminders.execute(SendDuesRemindersCommand())

    assert result["sent"] == 1
    assert push.sent == [
        {
            "academy_id": ACADEMY,
            "user_id": "par-1",
            "title": "BLNO Badminton",
            "body": "You have $125.00 due. Tap to pay.",
            "data": {"url": "/parent/payments"},
        }
    ]
