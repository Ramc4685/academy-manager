"""Unit tests for the add-card reminder use case."""

from __future__ import annotations

import pytest

from backend.v2.contexts.billing.application.use_cases.send_add_card_reminder import (
    InviteEmailOutcome,
    ParentContact,
    SendAddCardReminder,
)

ACADEMY_ID = "academy-1"
RETURN_URL = "https://app.example.com/parent/billing"


class FakeContacts:
    def __init__(self, contacts: dict[str, ParentContact]):
        self._contacts = contacts

    async def get_parent_contact(self, parent_id: str, *, academy_id: str) -> ParentContact | None:
        return self._contacts.get(parent_id)


class FakeLinks:
    def __init__(self, link: str = "https://billing.stripe.com/session/test"):
        self._link = link
        self.calls: list[dict[str, str]] = []

    async def create_card_setup_link(
        self, *, parent_id: str, academy_id: str, return_url: str
    ) -> str:
        self.calls.append(
            {"parent_id": parent_id, "academy_id": academy_id, "return_url": return_url}
        )
        return self._link


class FakeSender:
    def __init__(self, outcome: InviteEmailOutcome | None = None):
        self._outcome = outcome or InviteEmailOutcome(ok=True)
        self.calls: list[dict[str, str]] = []

    async def send_invite_email(
        self, *, user_id: str, email: str, display_name: str, subject: str, body: str
    ) -> InviteEmailOutcome:
        self.calls.append(
            {
                "user_id": user_id,
                "email": email,
                "display_name": display_name,
                "subject": subject,
                "body": body,
            }
        )
        return self._outcome


class FakeAcademies:
    async def get_academy_name(self, academy_id: str) -> str | None:
        return "Acme Tennis Academy"


@pytest.mark.asyncio
async def test_sends_one_reminder_email_with_setup_link():
    contacts = FakeContacts(
        {"p1": ParentContact(parent_id="p1", email="parent@example.com", display_name="Pat Lee")}
    )
    links = FakeLinks()
    sender = FakeSender()
    use_case = SendAddCardReminder(
        contacts=contacts,
        links=links,
        sender=sender,
        academies=FakeAcademies(),
        return_url=RETURN_URL,
    )

    outcome = await use_case.execute(academy_id=ACADEMY_ID, parent_id="p1")

    assert outcome.ok is True
    assert len(sender.calls) == 1
    call = sender.calls[0]
    assert call["email"] == "parent@example.com"
    assert call["display_name"] == "Pat Lee"
    assert "billing.stripe.com" in call["body"]
    assert len(links.calls) == 1
    assert links.calls[0]["parent_id"] == "p1"
    assert links.calls[0]["return_url"] == RETURN_URL


@pytest.mark.asyncio
async def test_unknown_parent_returns_failure_without_sending():
    use_case = SendAddCardReminder(
        contacts=FakeContacts({}),
        links=FakeLinks(),
        sender=FakeSender(),
        academies=FakeAcademies(),
        return_url=RETURN_URL,
    )

    outcome = await use_case.execute(academy_id=ACADEMY_ID, parent_id="missing")

    assert outcome.ok is False
    assert outcome.failed_reason == "parent_not_found"


@pytest.mark.asyncio
async def test_email_send_failure_surfaces_reason():
    contacts = FakeContacts(
        {"p1": ParentContact(parent_id="p1", email="parent@example.com", display_name="Pat Lee")}
    )
    sender = FakeSender(InviteEmailOutcome(ok=False, failed_reason="smtp_error"))
    use_case = SendAddCardReminder(
        contacts=contacts,
        links=FakeLinks(),
        sender=sender,
        academies=FakeAcademies(),
        return_url=RETURN_URL,
    )

    outcome = await use_case.execute(academy_id=ACADEMY_ID, parent_id="p1")

    assert outcome.ok is False
    assert outcome.failed_reason == "smtp_error"
