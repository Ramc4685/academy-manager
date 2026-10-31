"""The academy's new-lead email for the public trial form (Lane B4).

The adapter is a background task body: it must send only for a NEW contact,
at most once per owner address, through the themed shell, and never raise.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from backend.v2.composition.public_trial_requests import (
    TrialRequestOwnerEmail,
    render_trial_request_alert,
)
from backend.v2.contexts.communications.application.ports import ResolvedRecipient
from backend.v2.contexts.communications.domain.email_category import EmailCategory
from backend.v2.contexts.communications.infrastructure.stub_send_port import StubEmailSendPort
from backend.v2.contexts.crm.domain.models import ContactConsent, CrmContact
from backend.v2.shared.comms.email_theme import EmailBrand
from backend.v2.shared.tenancy import current_academy_id

ACADEMY = "acad-riverside"
NOW = datetime(2026, 9, 23, 15, 0, tzinfo=UTC)


def _contact(**overrides: Any) -> CrmContact:
    fields: dict[str, Any] = {
        "contact_id": "contact-1",
        "academy_id": ACADEMY,
        "name": "Jamie Testparent",
        "email": "jamie@example.test",
        "phone_digits": "5550102030",
        "source": "website",
        "child_age": "9",
        "pipeline_status": "trial",
        "consent": ContactConsent(contact_about_request=True, captured_at=NOW),
        "created_at": NOW,
        "updated_at": NOW,
    }
    fields.update(overrides)
    return CrmContact(**fields)


class _Academies:
    def __init__(self, doc: dict[str, Any] | None) -> None:
        self.doc = doc
        self.seen_scope: list[str] = []

    async def find_by_id(self, academy_id: str) -> dict[str, Any] | None:
        self.seen_scope.append(current_academy_id())
        return self.doc


class _Audiences:
    def __init__(self, recipients: list[ResolvedRecipient]) -> None:
        self.recipients = recipients
        self.roles: list[str] = []

    async def resolve_academy_audience(self, audience: Any) -> list[ResolvedRecipient]:
        self.roles.append(audience.role)
        return self.recipients


def _adapter(
    recipients: list[ResolvedRecipient], doc: dict[str, Any] | None = None
) -> tuple[TrialRequestOwnerEmail, StubEmailSendPort, _Audiences, _Academies]:
    sender = StubEmailSendPort()
    audiences = _Audiences(recipients)
    academies = _Academies(
        doc
        if doc is not None
        else {
            "academy_id": ACADEMY,
            "display_name": "Riverside Shuttle Club",
            "brand_color": "#fde047",
            "contact_email": "desk@riverside.example.test",
        }
    )
    adapter = TrialRequestOwnerEmail(academies=academies, audiences=audiences, sender=sender)
    return adapter, sender, audiences, academies


OWNER = ResolvedRecipient(user_id="owner-1", email="owner@riverside.example.test")


async def test_new_contact_emails_each_owner_address_once_in_tenant_scope() -> None:
    twin = ResolvedRecipient(user_id="owner-2", email="OWNER@riverside.example.test")
    adapter, sender, audiences, academies = _adapter([OWNER, twin])
    await adapter.notify(
        academy_id=ACADEMY, contact=_contact(), created=True, class_title="Juniors"
    )

    assert audiences.roles == ["owner"]
    assert academies.seen_scope == [ACADEMY]
    [sent] = sender.sent
    assert sent["email"] == "owner@riverside.example.test"
    assert sent["reply_to"] == "jamie@example.test"
    assert sent["category"] == EmailCategory.TRANSACTIONAL
    assert sent["subject"] == "New trial request from Jamie Testparent"


async def test_repeat_or_honeypot_sends_nothing_and_reads_nothing() -> None:
    adapter, sender, audiences, academies = _adapter([OWNER])
    await adapter.notify(academy_id=ACADEMY, contact=_contact(), created=False, class_title=None)
    await adapter.notify(academy_id=ACADEMY, contact=None, created=False, class_title=None)
    assert sender.sent == []
    assert audiences.roles == []
    assert academies.seen_scope == []


async def test_no_owner_address_falls_back_to_the_academy_contact_email() -> None:
    blank = ResolvedRecipient(user_id="owner-3", email="  ")
    adapter, sender, _, _ = _adapter([blank])
    await adapter.notify(academy_id=ACADEMY, contact=_contact(), created=True, class_title=None)
    [sent] = sender.sent
    assert sent["email"] == "desk@riverside.example.test"


async def test_no_address_at_all_is_a_quiet_no_op() -> None:
    adapter, sender, _, _ = _adapter([], doc={"academy_id": ACADEMY})
    await adapter.notify(academy_id=ACADEMY, contact=_contact(), created=True, class_title=None)
    assert sender.sent == []


async def test_failures_never_escape_the_background_task() -> None:
    adapter, _, audiences, _ = _adapter([OWNER])

    async def _boom(_audience: Any) -> list[ResolvedRecipient]:
        raise RuntimeError("mongo down")

    audiences.resolve_academy_audience = _boom  # type: ignore[method-assign]
    await adapter.notify(academy_id=ACADEMY, contact=_contact(), created=True, class_title=None)


def test_render_uses_the_theme_shell_escapes_text_and_labels_a_lead() -> None:
    brand = EmailBrand(academy_name="Riverside Shuttle Club", brand_color="#0f766e")
    subject, body = render_trial_request_alert(
        brand=brand,
        contact=_contact(
            name="Jo <b>",
            pipeline_status="lead",
            message="Line one\n<i>two</i>",
            consent=ContactConsent(contact_about_request=True, marketing=True, captured_at=NOW),
        ),
        class_title=None,
    )
    assert subject == "New inquiry from Jo <b>"
    assert "Jo &lt;b&gt;" in body
    assert "Jo <b>" not in body
    assert "&lt;i&gt;two&lt;/i&gt;" in body
    assert "Sent by Riverside Shuttle Club" in body  # the shared email_theme shell
    assert "#0f766e" in body  # the academy's brand rule
    assert "News and offers" in body and ">Yes<" in body


async def test_owner_alert_uses_the_academy_display_name_but_family_reply_to() -> None:
    """L9a: the From name follows the academy's sender name; reply-to stays
    the family's address so the owner can answer them directly."""
    adapter, sender, _, _ = _adapter(
        [OWNER],
        doc={
            "academy_id": ACADEMY,
            "display_name": "Riverside Shuttle Club",
            "email_sender_name": "Riverside Front Desk",
            "email_reply_to": "desk@example.com",
        },
    )
    await adapter.notify(academy_id=ACADEMY, contact=_contact(), created=True, class_title=None)
    [sent] = sender.sent
    assert sent["sender_name"] == "Riverside Front Desk"
    assert sent["reply_to"] == "jamie@example.test"
