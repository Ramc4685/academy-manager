"""The roster-alert adapter — audience, category, count and clock (#612).

This is where the requirements that are easy to get subtly wrong live:

* who hears about a roster change (coach + admins + owners, deduped, never the
  person who made the change, never another tenant);
* which category each message carries — staff alerts are NOTIFICATION and
  therefore unsubscribable and footered, the family's seat-opened email is
  TRANSACTIONAL and is not;
* what "roster now N/CAP" counts (active enrollments, not ``reserved_seats``);
* and the class time, which must be the SESSION's wall clock with its zone
  named — prod has sessions stamped ``UTC`` under an America/Chicago academy,
  and a silently shifted class time is the #541/#604 defect class.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest

from backend.v2.composition.roster_notifications import RosterAlertAdapter
from backend.v2.contexts.communications.application.ports import (
    ResolvedRecipient,
    SendOutcome,
)
from backend.v2.contexts.communications.application.unsubscribe_token import (
    UnsubscribeLinkBuilder,
)
from backend.v2.contexts.communications.domain.email_category import EmailCategory
from backend.v2.contexts.enrollment.domain.models import Enrollment, Session
from backend.v2.shared.tenancy import tenant_scope

ACADEMY = "acad-1"


def _session(
    session_id: str = "sess-1",
    *,
    title: str = "Beginner Badminton",
    timezone: str | None = "America/Chicago",
    recurring: bool = True,
    capacity: int = 10,
) -> Session:
    return Session(
        session_id=session_id,
        academy_id=ACADEMY,
        coach_id="coach-1",
        title=title,
        location="Court 1",
        # Stored UTC instant. For a recurring template this is a *rolling*
        # value (the repo synthesises the next matching occurrence), so the
        # renderer must never format it when days_of_week is present.
        start_at=datetime(2026, 9, 1, 23, 0, tzinfo=UTC),
        end_at=datetime(2026, 9, 2, 0, 30, tzinfo=UTC),
        capacity=capacity,
        days_of_week=["Tue", "Thu"] if recurring else [],
        start_time="18:00" if recurring else None,
        end_time="19:30" if recurring else None,
        timezone=timezone,
    )


@dataclass
class FakeSessions:
    rows: dict[str, Session] = field(default_factory=dict)

    async def get(self, session_id: str) -> Session | None:
        return self.rows.get(session_id)


@dataclass
class FakeRoster:
    active: list[Enrollment] = field(default_factory=list)

    async def active_for_session(self, session_id: str) -> list[Enrollment]:
        return [row for row in self.active if row.session_id == session_id]


@dataclass
class FakeStudents:
    names: dict[str, str] = field(default_factory=dict)

    async def by_ids(self, student_ids: list[str]) -> list[Any]:
        return [
            type("S", (), {"full_name": self.names[sid]})()
            for sid in student_ids
            if sid in self.names
        ]


@dataclass
class FakeAcademies:
    doc: dict[str, Any] | None = None

    async def find_by_id(self, academy_id: str) -> dict[str, Any] | None:
        return self.doc


@dataclass
class FakeAudiences:
    coaches: dict[str, list[ResolvedRecipient]] = field(default_factory=dict)
    by_role: dict[str, list[ResolvedRecipient]] = field(default_factory=dict)
    users: dict[str, ResolvedRecipient] = field(default_factory=dict)
    raise_on_coach: bool = False

    async def resolve_coach_audience(self, audience: Any) -> list[ResolvedRecipient]:
        if self.raise_on_coach:
            raise RuntimeError("mongo is down")
        return self.coaches.get(audience.session_id or "", [])

    async def resolve_academy_audience(self, audience: Any) -> list[ResolvedRecipient]:
        return self.by_role.get(audience.role, [])

    async def resolve_selected_audience(self, audience: Any) -> list[ResolvedRecipient]:
        return [self.users[uid] for uid in audience.user_ids if uid in self.users]

    async def resolve_session_audience(self, audience: Any) -> list[ResolvedRecipient]:
        return []

    async def resolve_payment_risk_audience(self, audience: Any) -> list[ResolvedRecipient]:
        return []


@dataclass
class FakeSender:
    sent: list[dict[str, Any]] = field(default_factory=list)
    fail_for: set[str] = field(default_factory=set)

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
        if recipient.user_id in self.fail_for:
            raise RuntimeError("resend rejected the message")
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


def _adapter(
    *,
    sessions: FakeSessions,
    audiences: FakeAudiences,
    sender: FakeSender,
    roster: FakeRoster | None = None,
    academy: dict[str, Any] | None = None,
    students: FakeStudents | None = None,
) -> RosterAlertAdapter:
    return RosterAlertAdapter(
        sessions=sessions,  # type: ignore[arg-type]
        enrollments=roster or FakeRoster(),  # type: ignore[arg-type]
        students=students or FakeStudents(names={"st-1": "Alice Nguyen"}),  # type: ignore[arg-type]
        academies=FakeAcademies(  # type: ignore[arg-type]
            doc=academy
            if academy is not None
            else {"display_name": "BLNO Badminton", "timezone": "America/Chicago", "slug": "blno"}
        ),
        audiences=audiences,  # type: ignore[arg-type]
        sender=sender,  # type: ignore[arg-type]
        unsubscribe_links=UnsubscribeLinkBuilder(
            frontend_url="https://app.courtmastr.com", secret="s3cret"
        ),
    )


def _staff() -> FakeAudiences:
    return FakeAudiences(
        coaches={
            "sess-1": [ResolvedRecipient(user_id="coach-1", email="coach@x.com")],
            "sess-2": [ResolvedRecipient(user_id="coach-2", email="coach2@x.com")],
        },
        by_role={
            "admin": [
                ResolvedRecipient(user_id="admin-1", email="admin@x.com"),
                # Also a coach on this session — must be mailed once, not twice.
                ResolvedRecipient(user_id="coach-1", email="coach@x.com"),
                # No address at all: dropped rather than attempted.
                ResolvedRecipient(user_id="admin-2", email=None),
            ],
            "owner": [ResolvedRecipient(user_id="owner-1", email="owner@x.com")],
        },
        users={"par-1": ResolvedRecipient(user_id="par-1", email="parent@x.com")},
    )


@pytest.mark.asyncio
async def test_staff_audience_is_coach_admins_and_owners_deduped_without_the_actor() -> None:
    sender = FakeSender()
    adapter = _adapter(
        sessions=FakeSessions(rows={"sess-1": _session()}),
        audiences=_staff(),
        sender=sender,
    )

    with tenant_scope(ACADEMY):
        await adapter.roster_changed(
            change="added",
            session_id="sess-1",
            student_id="st-1",
            student_name="Alice Nguyen",
            actor_id="admin-1",
        )

    # coach-1 once (not twice), owner-1, and NOT admin-1 (they did it) and not
    # admin-2 (no address).
    assert [row["user_id"] for row in sender.sent] == ["coach-1", "owner-1"]


@pytest.mark.asyncio
async def test_staff_alerts_are_notification_and_carry_the_unsubscribe_footer() -> None:
    sender = FakeSender()
    adapter = _adapter(
        sessions=FakeSessions(rows={"sess-1": _session()}),
        audiences=_staff(),
        sender=sender,
    )

    with tenant_scope(ACADEMY):
        await adapter.roster_changed(change="added", session_id="sess-1", student_id="st-1")

    assert sender.sent
    for row in sender.sent:
        # NOTIFICATION is in UNSUBSCRIBABLE_CATEGORIES, so the CAN-SPAM footer
        # is mandatory — and the link is per recipient, not per event.
        assert row["category"] is EmailCategory.NOTIFICATION
        assert "/unsubscribe?t=" in row["body"]
    tokens = {row["body"].split("/unsubscribe?t=")[1].split('"')[0] for row in sender.sent}
    assert len(tokens) == len(sender.sent)


@pytest.mark.asyncio
async def test_the_roster_count_is_active_enrollments_over_capacity() -> None:
    sender = FakeSender()
    roster = FakeRoster(
        active=[
            Enrollment(
                enrollment_id=f"enr-{i}",
                academy_id=ACADEMY,
                session_id="sess-1",
                student_id=f"st-{i}",
                status="active",
            )
            for i in range(3)
        ]
    )
    adapter = _adapter(
        sessions=FakeSessions(rows={"sess-1": _session(capacity=12)}),
        audiences=_staff(),
        sender=sender,
        roster=roster,
    )

    with tenant_scope(ACADEMY):
        await adapter.roster_changed(change="added", session_id="sess-1", student_id="st-1")

    # Not `reserved_seats`: that counter drifts (WithdrawEnrollment never
    # releases a seat), so the alert quotes what the roster actually holds.
    assert "3 of 12 enrolled" in sender.sent[0]["body"]


@pytest.mark.asyncio
async def test_a_recurring_session_renders_its_own_clock_with_the_zone_named() -> None:
    sender = FakeSender()
    adapter = _adapter(
        sessions=FakeSessions(rows={"sess-1": _session()}),
        audiences=_staff(),
        sender=sender,
    )

    with tenant_scope(ACADEMY):
        await adapter.roster_changed(change="added", session_id="sess-1", student_id="st-1")

    body = sender.sent[0]["body"]
    assert "6:00 PM" in body and "7:30 PM" in body
    assert "(America/Chicago)" in body
    # The stored instant is 23:00 UTC. Rendering it (or any UTC clock) is the
    # bug this asserts against.
    assert "11:00 PM" not in body


@pytest.mark.asyncio
async def test_a_session_stamped_utc_says_so_rather_than_shifting_silently() -> None:
    sender = FakeSender()
    adapter = _adapter(
        sessions=FakeSessions(rows={"sess-1": _session(timezone="UTC")}),
        audiences=_staff(),
        sender=sender,
    )

    with tenant_scope(ACADEMY):
        await adapter.roster_changed(change="added", session_id="sess-1", student_id="st-1")

    # Prod has exactly this shape. Printing the zone makes the bad data visible
    # to the human reading the email.
    assert "(UTC)" in sender.sent[0]["body"]


@pytest.mark.asyncio
async def test_with_no_zone_anywhere_the_alert_says_so() -> None:
    sender = FakeSender()
    adapter = _adapter(
        sessions=FakeSessions(rows={"sess-1": _session(timezone=None)}),
        audiences=_staff(),
        sender=sender,
        academy={"display_name": "BLNO Badminton", "slug": "blno"},
    )

    with tenant_scope(ACADEMY):
        await adapter.roster_changed(change="added", session_id="sess-1", student_id="st-1")

    assert "(timezone not set)" in sender.sent[0]["body"]


@pytest.mark.asyncio
async def test_a_move_tells_both_coaches() -> None:
    sender = FakeSender()
    adapter = _adapter(
        sessions=FakeSessions(rows={"sess-1": _session(), "sess-2": _session("sess-2")}),
        audiences=_staff(),
        sender=sender,
    )

    with tenant_scope(ACADEMY):
        await adapter.roster_changed(
            change="moved",
            session_id="sess-2",
            student_id="st-1",
            from_session_id="sess-1",
            to_session_id="sess-2",
        )

    assert {"coach-1", "coach-2"} <= {row["user_id"] for row in sender.sent}
    assert "Moved from" in sender.sent[0]["body"]


@pytest.mark.asyncio
async def test_one_failed_send_does_not_cost_the_rest_of_the_audience() -> None:
    sender = FakeSender(fail_for={"coach-1"})
    adapter = _adapter(
        sessions=FakeSessions(rows={"sess-1": _session()}),
        audiences=_staff(),
        sender=sender,
    )

    with tenant_scope(ACADEMY):
        await adapter.roster_changed(change="added", session_id="sess-1", student_id="st-1")

    # No exception escaped, and everyone after the failure still got theirs.
    assert [row["user_id"] for row in sender.sent] == ["admin-1", "owner-1"]


@pytest.mark.asyncio
async def test_an_audience_lookup_failure_costs_only_that_group() -> None:
    audiences = _staff()
    audiences.raise_on_coach = True
    sender = FakeSender()
    adapter = _adapter(
        sessions=FakeSessions(rows={"sess-1": _session()}),
        audiences=audiences,
        sender=sender,
    )

    with tenant_scope(ACADEMY):
        await adapter.roster_changed(change="added", session_id="sess-1", student_id="st-1")

    # The coach lookup is lost, so nobody is resolved *through it* — the rest
    # of the staff still hear about the change, and one of them happens to
    # also be the coach.
    assert [row["user_id"] for row in sender.sent] == ["admin-1", "coach-1", "owner-1"]


@pytest.mark.asyncio
async def test_a_missing_session_sends_nothing_rather_than_guessing() -> None:
    sender = FakeSender()
    adapter = _adapter(sessions=FakeSessions(), audiences=_staff(), sender=sender)

    with tenant_scope(ACADEMY):
        await adapter.roster_changed(change="added", session_id="sess-9", student_id="st-1")

    assert sender.sent == []


@pytest.mark.asyncio
async def test_a_promotion_also_emails_the_family_transactionally() -> None:
    sender = FakeSender()
    adapter = _adapter(
        sessions=FakeSessions(rows={"sess-1": _session()}),
        audiences=_staff(),
        sender=sender,
    )

    with tenant_scope(ACADEMY):
        await adapter.roster_changed(
            change="promoted",
            session_id="sess-1",
            student_id="st-1",
            parent_user_id="par-1",
        )

    parent = [row for row in sender.sent if row["user_id"] == "par-1"]
    assert len(parent) == 1
    # TRANSACTIONAL: a family that switched off digests still learns their
    # child took the seat, and the message carries no opt-out footer.
    assert parent[0]["category"] is EmailCategory.TRANSACTIONAL
    assert "/unsubscribe?t=" not in parent[0]["body"]
    # The portal link is built on the academy's own subdomain (ADR-0007): a
    # link on the generic frontend host resolves to no tenant at all.
    assert "https://blno.courtmastr.com/parent" in parent[0]["body"]
    assert "Alice Nguyen" in parent[0]["subject"]


@pytest.mark.asyncio
async def test_a_promotion_with_no_parent_still_alerts_staff() -> None:
    sender = FakeSender()
    adapter = _adapter(
        sessions=FakeSessions(rows={"sess-1": _session()}),
        audiences=_staff(),
        sender=sender,
    )

    with tenant_scope(ACADEMY):
        await adapter.roster_changed(change="promoted", session_id="sess-1", student_id="st-1")

    assert [row["user_id"] for row in sender.sent] == ["coach-1", "admin-1", "owner-1"]


@pytest.mark.asyncio
async def test_the_student_name_falls_back_to_a_lookup_and_is_escaped() -> None:
    sender = FakeSender()
    adapter = _adapter(
        sessions=FakeSessions(rows={"sess-1": _session(title="A & B <Squad>")}),
        audiences=_staff(),
        sender=sender,
        students=FakeStudents(names={"st-1": "Bobby <b>Tables</b>"}),
    )

    with tenant_scope(ACADEMY):
        await adapter.roster_changed(change="cancelled", session_id="sess-1", student_id="st-1")

    body = sender.sent[0]["body"]
    assert "Bobby &lt;b&gt;Tables&lt;/b&gt;" in body
    assert "A &amp; B &lt;Squad&gt;" in body
