"""The absence-notice notification adapter (#616): audience, category, copy
and idempotency.

Runs over the REAL ``MongoAbsenceNoticeSendRepository`` on the mongomock
``db`` fixture, so the once-per-notice guarantee is exercised against the
same ``digest_claim`` rule production uses — not an in-memory fake that could
be more permissive than the store (the #664 lesson). Everything else (send
port, audience resolver, session/academy/policy lookups) is a fake that
records what it was handed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest

from backend.v2.composition.absence_notifications import (
    AbsenceNoticeNotificationAdapter,
    MongoAbsenceNoticeSendRepository,
)
from backend.v2.contexts.communications.application.ports import (
    ResolvedRecipient,
    SendOutcome,
)
from backend.v2.contexts.communications.application.unsubscribe_token import (
    UnsubscribeLinkBuilder,
)
from backend.v2.contexts.communications.domain.email_category import EmailCategory
from backend.v2.contexts.enrollment.application.use_cases.absence_notices import AbsenceNotice
from backend.v2.contexts.enrollment.domain.models import Session, SessionOccurrence, Student
from backend.v2.contexts.enrollment.domain.self_service import ParentSelfServicePolicy

ACADEMY = "test-academy"


def _session(*, timezone: str | None = "America/Chicago") -> Session:
    return Session(
        session_id="sess-1",
        academy_id=ACADEMY,
        coach_id="coach-1",
        title="Beginner Badminton",
        location="Court 1",
        start_at=datetime(2026, 9, 1, 23, 0, tzinfo=UTC),
        end_at=datetime(2026, 9, 2, 0, 30, tzinfo=UTC),
        capacity=10,
        timezone=timezone,
    )


def _occurrence(*, substitute: str | None = None) -> SessionOccurrence:
    # 22:45 UTC on 2026-09-09 is 5:45 PM in Chicago — the #706 incident's occurrence.
    return SessionOccurrence(
        occurrence_id="occ-1",
        academy_id=ACADEMY,
        session_id="sess-1",
        start_at=datetime(2026, 9, 9, 22, 45, tzinfo=UTC),
        end_at=datetime(2026, 9, 10, 0, 15, tzinfo=UTC),
        scheduled_coach_id="coach-1",
        substitute_coach_id=substitute,
    )


def _student() -> Student:
    return Student(
        student_id="st-1", academy_id=ACADEMY, parent_id="par-1", full_name="Alice Nguyen"
    )


def _notice(
    *, notice_id: str = "nt-1", window_met: bool = True, recorded_by_admin: bool = False
) -> AbsenceNotice:
    return AbsenceNotice(
        notice_id=notice_id,
        academy_id=ACADEMY,
        student_id="st-1",
        occurrence_id="occ-1",
        session_id="sess-1",
        submitted_by="admin-1" if recorded_by_admin else "par-1",
        submitted_at=datetime(2026, 9, 9, 15, 0, tzinfo=UTC),
        notice_window_met=window_met,
        recorded_by_admin=recorded_by_admin,
    )


@dataclass
class FakeSessions:
    rows: dict[str, Session] = field(default_factory=dict)

    async def get(self, session_id: str) -> Session | None:
        return self.rows.get(session_id)


@dataclass
class FakeAcademies:
    doc: dict[str, Any] | None = None

    async def find_by_id(self, academy_id: str) -> dict[str, Any] | None:
        return self.doc


@dataclass
class FakePolicies:
    min_hours: int = 2
    raise_on_read: bool = False

    async def get_or_default(self) -> ParentSelfServicePolicy:
        if self.raise_on_read:
            raise RuntimeError("mongo is down")
        return ParentSelfServicePolicy.default(ACADEMY).model_copy(
            update={"absence_notice_min_hours": self.min_hours}
        )


@dataclass
class FakeAudiences:
    coaches: dict[str, list[ResolvedRecipient]] = field(default_factory=dict)
    by_role: dict[str, list[ResolvedRecipient]] = field(default_factory=dict)
    users: dict[str, ResolvedRecipient] = field(default_factory=dict)
    selected_calls: list[tuple[str, ...]] = field(default_factory=list)

    async def resolve_coach_audience(self, audience: Any) -> list[ResolvedRecipient]:
        return self.coaches.get(audience.session_id or "", [])

    async def resolve_academy_audience(self, audience: Any) -> list[ResolvedRecipient]:
        return self.by_role.get(audience.role, [])

    async def resolve_selected_audience(self, audience: Any) -> list[ResolvedRecipient]:
        self.selected_calls.append(tuple(audience.user_ids))
        return [self.users[uid] for uid in audience.user_ids if uid in self.users]

    async def resolve_session_audience(self, audience: Any) -> list[ResolvedRecipient]:
        return []

    async def resolve_payment_risk_audience(self, audience: Any) -> list[ResolvedRecipient]:
        return []


@dataclass
class FakeSender:
    sent: list[dict[str, Any]] = field(default_factory=list)
    raise_for: set[str] = field(default_factory=set)
    suppress_for: set[str] = field(default_factory=set)

    async def send(
        self,
        *,
        recipient: ResolvedRecipient,
        subject: str,
        body: str,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        reply_to: str | None = None,
        category: EmailCategory = EmailCategory.TRANSACTIONAL,
    ) -> SendOutcome:
        if recipient.user_id in self.raise_for:
            raise RuntimeError("resend rejected the message")
        if recipient.user_id in self.suppress_for:
            return SendOutcome(
                ok=False, provider_message_id=None, failed_reason="unsubscribed", suppressed=True
            )
        self.sent.append(
            {
                "user_id": recipient.user_id,
                "email": recipient.email,
                "subject": subject,
                "body": body,
                "category": category,
            }
        )
        return SendOutcome(ok=True, provider_message_id="msg-1", failed_reason=None)


def _staff() -> FakeAudiences:
    return FakeAudiences(
        coaches={"sess-1": [ResolvedRecipient(user_id="coach-1", email="coach@x.com")]},
        by_role={
            "admin": [
                ResolvedRecipient(user_id="admin-1", email="admin@x.com"),
                # Also the session coach — mailed once, not twice.
                ResolvedRecipient(user_id="coach-1", email="coach@x.com"),
                # No address: dropped rather than attempted.
                ResolvedRecipient(user_id="admin-2", email=None),
            ],
            "owner": [ResolvedRecipient(user_id="owner-1", email="owner@x.com")],
        },
        users={
            "par-1": ResolvedRecipient(user_id="par-1", email="parent@x.com"),
            "coach-1": ResolvedRecipient(user_id="coach-1", email="coach@x.com"),
            "sub-1": ResolvedRecipient(user_id="sub-1", email="sub@x.com"),
        },
    )


def _adapter(
    db: Any,
    *,
    sender: FakeSender,
    audiences: FakeAudiences | None = None,
    sessions: FakeSessions | None = None,
    academy: dict[str, Any] | None = None,
    policies: FakePolicies | None = None,
) -> AbsenceNoticeNotificationAdapter:
    return AbsenceNoticeNotificationAdapter(
        sessions=sessions or FakeSessions(rows={"sess-1": _session()}),
        academies=FakeAcademies(
            doc=academy
            if academy is not None
            else {"display_name": "BLNO Badminton", "timezone": "America/Chicago", "slug": "blno"}
        ),
        policies=policies or FakePolicies(),
        audiences=audiences or _staff(),
        sender=sender,
        notice_sends=MongoAbsenceNoticeSendRepository(db),
        unsubscribe_links=UnsubscribeLinkBuilder(
            frontend_url="https://app.courtmastr.com", secret="s3cret"
        ),
    )


def _by_user(sender: FakeSender, user_id: str) -> dict[str, Any]:
    return next(row for row in sender.sent if row["user_id"] == user_id)


@pytest.mark.asyncio
async def test_parent_notice_mails_staff_once_each_and_confirms_to_the_parent(db, acad) -> None:
    sender = FakeSender()
    adapter = _adapter(db, sender=sender)

    await adapter.absence_notice_submitted(
        notice=_notice(), occurrence=_occurrence(), student=_student()
    )

    # coach-1 once (occurrence coach AND admin), admin-1, owner-1, then the
    # parent; admin-2 (no address) is never attempted.
    assert [row["user_id"] for row in sender.sent] == ["coach-1", "admin-1", "owner-1", "par-1"]

    staff = _by_user(sender, "coach-1")
    assert staff["category"] is EmailCategory.NOTIFICATION
    # Subject: "<student> will miss <session> on <local date/time>", academy zone.
    assert staff["subject"] == (
        "Alice Nguyen will miss Beginner Badminton on "
        "Wednesday, September 9 at 5:45 PM (America/Chicago)"
    )
    assert "/unsubscribe?t=" in staff["body"]
    assert "Court 1" in staff["body"]
    assert "counts toward a make-up" in staff["body"]

    parent = _by_user(sender, "par-1")
    assert parent["category"] is EmailCategory.TRANSACTIONAL
    assert "/unsubscribe?t=" not in parent["body"]
    assert "Alice Nguyen" in parent["body"]
    assert "Wednesday, September 9 at 5:45 PM (America/Chicago)" in parent["body"]
    assert "at least 2 hours' notice, so this absence counts toward a make-up" in parent["body"]
    assert "https://blno.courtmastr.com/parent" in parent["body"]


@pytest.mark.asyncio
async def test_staff_unsubscribe_links_are_per_recipient(db, acad) -> None:
    sender = FakeSender()
    await _adapter(db, sender=sender).absence_notice_submitted(
        notice=_notice(), occurrence=_occurrence(), student=_student()
    )
    staff_rows = [row for row in sender.sent if row["category"] is EmailCategory.NOTIFICATION]
    tokens = {row["body"].split("/unsubscribe?t=")[1].split('"')[0] for row in staff_rows}
    assert len(tokens) == len(staff_rows) == 3


@pytest.mark.asyncio
async def test_late_notice_tells_the_parent_it_does_not_count(db, acad) -> None:
    sender = FakeSender()
    await _adapter(db, sender=sender, policies=FakePolicies(min_hours=24)).absence_notice_submitted(
        notice=_notice(window_met=False), occurrence=_occurrence(), student=_student()
    )
    parent = _by_user(sender, "par-1")
    assert "less than 24 hours before the class" in parent["body"]
    assert "does not count toward a make-up" in parent["body"]
    assert "counts toward a make-up class. You can request" not in parent["body"]
    staff = _by_user(sender, "coach-1")
    assert "does not count toward a make-up" in staff["body"]


@pytest.mark.asyncio
async def test_admin_recorded_notice_alerts_staff_minus_the_admin_and_skips_the_parent(
    db, acad
) -> None:
    sender = FakeSender()
    adapter = _adapter(db, sender=sender)

    await adapter.absence_notice_submitted(
        notice=_notice(recorded_by_admin=True), occurrence=_occurrence(), student=_student()
    )

    # admin-1 recorded it (submitted_by) and is not told about their own
    # action; the parent gets nothing at all.
    assert [row["user_id"] for row in sender.sent] == ["coach-1", "owner-1"]
    assert all(row["category"] is EmailCategory.NOTIFICATION for row in sender.sent)
    assert "Recorded by the academy on the family's behalf" in sender.sent[0]["body"]
    # No parent claim row was even taken.
    rows = await db["absence_notice_sends"].find({"notice_id": "nt-1"}).to_list(None)
    assert {row["audience"] for row in rows} == {"staff"}


@pytest.mark.asyncio
async def test_substitute_coach_on_the_occurrence_is_alerted(db, acad) -> None:
    sender = FakeSender()
    await _adapter(db, sender=sender).absence_notice_submitted(
        notice=_notice(), occurrence=_occurrence(substitute="sub-1"), student=_student()
    )
    assert [row["user_id"] for row in sender.sent][:2] == ["sub-1", "coach-1"]


@pytest.mark.asyncio
async def test_second_call_for_the_same_notice_sends_nothing(db, acad) -> None:
    sender = FakeSender()
    adapter = _adapter(db, sender=sender)
    notice, occurrence, student = _notice(), _occurrence(), _student()

    await adapter.absence_notice_submitted(notice=notice, occurrence=occurrence, student=student)
    first = len(sender.sent)
    await adapter.absence_notice_submitted(notice=notice, occurrence=occurrence, student=student)

    assert first == 4
    assert len(sender.sent) == 4
    rows = await db["absence_notice_sends"].find({"notice_id": "nt-1"}).to_list(None)
    assert sorted((row["audience"], row["status"]) for row in rows) == [
        ("parent", "sent"),
        ("staff", "sent"),
    ]
    assert all(row["academy_id"] == ACADEMY for row in rows)


@pytest.mark.asyncio
async def test_a_different_notice_is_its_own_claim(db, acad) -> None:
    sender = FakeSender()
    adapter = _adapter(db, sender=sender)
    await adapter.absence_notice_submitted(
        notice=_notice(notice_id="nt-1"), occurrence=_occurrence(), student=_student()
    )
    await adapter.absence_notice_submitted(
        notice=_notice(notice_id="nt-2"), occurrence=_occurrence(), student=_student()
    )
    assert len(sender.sent) == 8


@pytest.mark.asyncio
async def test_a_failing_recipient_does_not_cost_the_others_and_never_raises(db, acad) -> None:
    sender = FakeSender(raise_for={"coach-1"})
    adapter = _adapter(db, sender=sender)

    await adapter.absence_notice_submitted(
        notice=_notice(), occurrence=_occurrence(), student=_student()
    )

    assert [row["user_id"] for row in sender.sent] == ["admin-1", "owner-1", "par-1"]
    rows = {
        row["audience"]: row
        for row in await db["absence_notice_sends"].find({"notice_id": "nt-1"}).to_list(None)
    }
    assert rows["staff"]["status"] == "failed"
    assert rows["staff"]["failed_reason"] == "send_exception"
    assert rows["parent"]["status"] == "sent"


@pytest.mark.asyncio
async def test_a_gate_suppressed_recipient_is_a_preference_not_a_failure(db, acad) -> None:
    sender = FakeSender(suppress_for={"coach-1"})
    await _adapter(db, sender=sender).absence_notice_submitted(
        notice=_notice(), occurrence=_occurrence(), student=_student()
    )
    rows = await db["absence_notice_sends"].find({"notice_id": "nt-1"}).to_list(None)
    assert all(row["status"] == "sent" for row in rows)


@pytest.mark.asyncio
async def test_parent_without_an_address_is_recorded_not_retried(db, acad) -> None:
    audiences = _staff()
    audiences.users["par-1"] = ResolvedRecipient(user_id="par-1", email=None)
    sender = FakeSender()
    await _adapter(db, sender=sender, audiences=audiences).absence_notice_submitted(
        notice=_notice(), occurrence=_occurrence(), student=_student()
    )
    assert "par-1" not in [row["user_id"] for row in sender.sent]
    row = await db["absence_notice_sends"].find_one({"notice_id": "nt-1", "audience": "parent"})
    assert row is not None
    assert (row["status"], row["failed_reason"], row["retryable"]) == (
        "failed",
        "no_recipient",
        False,
    )


@pytest.mark.asyncio
async def test_missing_session_and_academy_still_send_with_plain_copy(db, acad) -> None:
    sender = FakeSender()
    adapter = _adapter(
        db,
        sender=sender,
        sessions=FakeSessions(rows={}),
        academy={},
        policies=FakePolicies(raise_on_read=True),
    )
    await adapter.absence_notice_submitted(
        notice=_notice(), occurrence=_occurrence(), student=_student()
    )
    staff = _by_user(sender, "coach-1")
    # No academy zone and no session: the UTC instant with the gap named,
    # never a silently guessed local time.
    assert staff["subject"] == (
        "Alice Nguyen will miss class on Wednesday, September 9 at 10:45 PM (timezone not set)"
    )
    parent = _by_user(sender, "par-1")
    # Policy read failed: the default window (2 hours) is quoted, not nothing.
    assert "at least 2 hours' notice" in parent["body"]
    assert "Your academy" in parent["body"]


@pytest.mark.asyncio
async def test_claim_rows_are_tenant_scoped(db, acad, other_acad) -> None:
    """Two academies filing the same notice id never share a claim."""
    sender = FakeSender()
    adapter = _adapter(db, sender=sender)
    # ``other_acad`` is the active tenant (last fixture wins); the adapter
    # reads the tenant at call time, so this send is scoped to it.
    await adapter.absence_notice_submitted(
        notice=_notice(), occurrence=_occurrence(), student=_student()
    )
    rows = await db["absence_notice_sends"].find({"notice_id": "nt-1"}).to_list(None)
    assert rows and all(row["academy_id"] == "other-academy" for row in rows)
