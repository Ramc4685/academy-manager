"""Settings overhaul Phase 1 Lane C item 4: when the academy has switched off
claiming waitlist offers in the app, the "a seat opened" email must not carry
a claim link — a parent could otherwise use a link that 403s.

This applies only to the offer-made ("claim it by <date>") email, never to
the offer-expired email, which links to a read-only "view your requests"
page.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
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
from backend.v2.contexts.enrollment.domain.models import Session
from backend.v2.contexts.enrollment.domain.self_service import ParentSelfServicePolicy
from backend.v2.shared.tenancy import tenant_scope

ACADEMY = "acad-1"


def _session() -> Session:
    return Session(
        session_id="sess-1",
        academy_id=ACADEMY,
        coach_id="coach-1",
        title="Beginner Badminton",
        location="Court 1",
        start_at=datetime(2026, 9, 1, 23, 0, tzinfo=UTC),
        end_at=datetime(2026, 9, 2, 0, 30, tzinfo=UTC),
        capacity=10,
        timezone="America/Chicago",
    )


@dataclass
class FakeSessions:
    async def get(self, session_id: str) -> Session | None:
        return _session()


@dataclass
class FakeStudents:
    async def by_ids(self, student_ids: list[str]) -> list[Any]:
        return [type("S", (), {"full_name": "Alice Nguyen"})()]


@dataclass
class FakeAcademies:
    async def find_by_id(self, academy_id: str) -> dict[str, Any]:
        return {"display_name": "BLNO Badminton", "timezone": "America/Chicago", "slug": "blno"}


@dataclass
class FakeAudiences:
    users: dict[str, ResolvedRecipient] = field(default_factory=dict)

    async def resolve_selected_audience(self, audience: Any) -> list[ResolvedRecipient]:
        return [self.users[uid] for uid in audience.user_ids if uid in self.users]

    async def resolve_coach_audience(self, audience: Any) -> list[ResolvedRecipient]:
        return []

    async def resolve_academy_audience(self, audience: Any) -> list[ResolvedRecipient]:
        return []

    async def resolve_session_audience(self, audience: Any) -> list[ResolvedRecipient]:
        return []

    async def resolve_payment_risk_audience(self, audience: Any) -> list[ResolvedRecipient]:
        return []


@dataclass
class FakeSender:
    sent: list[dict[str, Any]] = field(default_factory=list)

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
        sender_name: str | None = None,
    ) -> SendOutcome:
        self.sent.append({"subject": subject, "body": body})
        return SendOutcome(ok=True, provider_message_id="msg-1", failed_reason=None)


@dataclass
class FakePolicies:
    can_claim: bool

    async def get_or_default(self) -> ParentSelfServicePolicy:
        return ParentSelfServicePolicy(academy_id=ACADEMY, can_claim_waitlist_offer=self.can_claim)


def _adapter(*, sender: FakeSender, can_claim: bool) -> RosterAlertAdapter:
    return RosterAlertAdapter(
        sessions=FakeSessions(),  # type: ignore[arg-type]
        enrollments=None,  # type: ignore[arg-type]
        students=FakeStudents(),  # type: ignore[arg-type]
        academies=FakeAcademies(),  # type: ignore[arg-type]
        audiences=FakeAudiences(
            users={"parent-1": ResolvedRecipient(user_id="parent-1", email="parent@x.com")}
        ),  # type: ignore[arg-type]
        sender=sender,  # type: ignore[arg-type]
        unsubscribe_links=UnsubscribeLinkBuilder(
            frontend_url="https://app.courtmastr.com", secret="s3cret"
        ),
        self_service_policies=FakePolicies(can_claim=can_claim),  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_offer_email_has_claim_link_when_switch_on() -> None:
    sender = FakeSender()
    with tenant_scope(ACADEMY):
        await _adapter(sender=sender, can_claim=True).waitlist_offer_made(
            waitlist_id="wl-1",
            session_id="sess-1",
            student_id="st-1",
            parent_user_id="parent-1",
            offer_expires_at=datetime.now(UTC) + timedelta(days=2),
        )
    assert "/parent/requests?offer=wl-1" in sender.sent[0]["body"]


@pytest.mark.asyncio
async def test_offer_email_has_no_claim_link_when_switch_off() -> None:
    sender = FakeSender()
    with tenant_scope(ACADEMY):
        await _adapter(sender=sender, can_claim=False).waitlist_offer_made(
            waitlist_id="wl-1",
            session_id="sess-1",
            student_id="st-1",
            parent_user_id="parent-1",
            offer_expires_at=datetime.now(UTC) + timedelta(days=2),
        )
    body = sender.sent[0]["body"]
    assert "offer=wl-1" not in body
    assert "/parent/requests" not in body


@pytest.mark.asyncio
async def test_expired_offer_email_unaffected_by_claim_switch() -> None:
    """The expired-offer email's link is read-only ("view your requests"),
    never the claim action, so it is not gated by the switch."""
    sender = FakeSender()
    with tenant_scope(ACADEMY):
        await _adapter(sender=sender, can_claim=False).waitlist_offer_expired(
            waitlist_id="wl-1",
            session_id="sess-1",
            student_id="st-1",
            parent_user_id="parent-1",
        )
    assert "/parent/requests?offer=wl-1" in sender.sent[0]["body"]
