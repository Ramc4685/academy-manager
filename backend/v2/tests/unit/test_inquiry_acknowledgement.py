"""The family's instant acknowledgement for a website inquiry (AI strategy Phase 1 #2).

Template: trial vs lead wording, class named, footer and unsubscribe link,
no submitter text in the body. Send path: one email per contact (the claim on
the row), one per address per day, a provider failure gives the claim back,
nothing to an address that opted out, and the owner alert untouched by any.
"""

from __future__ import annotations

import asyncio
import importlib
from datetime import UTC, datetime
from typing import Any

import pytest

from backend.v2.composition.prospect_email import ProspectEmailer
from backend.v2.composition.public_trial_requests import (
    TrialRequestOwnerEmail,
    render_inquiry_acknowledgement,
)
from backend.v2.contexts.communications.application.ports import (
    ResolvedRecipient,
    SendOutcome,
)
from backend.v2.contexts.communications.application.unsubscribe_token import (
    UnsubscribeLinkBuilder,
)
from backend.v2.contexts.communications.domain.email_category import EmailCategory
from backend.v2.contexts.communications.infrastructure.gated_send_port import (
    GatedEmailSendPort,
)
from backend.v2.contexts.communications.infrastructure.mongo_prospect_opt_out_repo import (
    MongoProspectOptOutRepository,
    ProspectOptOutGate,
)
from backend.v2.contexts.communications.infrastructure.stub_send_port import StubEmailSendPort
from backend.v2.contexts.crm.domain.models import ContactConsent, CrmContact
from backend.v2.contexts.crm.infrastructure.mongo_crm_contact_repo import (
    MongoCrmContactRepository,
)
from backend.v2.shared.tenancy import tenant_scope

ACADEMY = "acad-riverside"
NOW = datetime(2026, 11, 4, 15, 0, tzinfo=UTC)
OWNER = ResolvedRecipient(user_id="owner-1", email="owner@riverside.example.test")
DOC = {
    "academy_id": ACADEMY,
    "slug": "riverside-academy",
    "display_name": "Riverside Shuttle Club",
    "brand_color": "#0f766e",
}
_M0192 = importlib.import_module("backend.v2.migrations.0192_crm_contacts")
_M0215 = importlib.import_module("backend.v2.migrations.0215_email_prospect_opt_outs")


def _contact(**overrides: Any) -> CrmContact:
    fields: dict[str, Any] = {
        "contact_id": "contact-1",
        "academy_id": ACADEMY,
        "name": "Jamie Testparent",
        "email": "jamie@example.test",
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
    def __init__(self, doc: dict[str, Any] = DOC) -> None:
        self.doc = doc

    async def find_by_id(self, academy_id: str) -> dict[str, Any] | None:
        return dict(self.doc)


class _ProspectsFail:
    """The provider refuses every prospect send; owner sends reach the stub."""

    def __init__(self, stub: StubEmailSendPort) -> None:
        self.stub = stub

    async def send(self, *, recipient: ResolvedRecipient, **kwargs: Any) -> SendOutcome:
        if recipient.user_id.startswith("crm_contact:"):
            return SendOutcome(ok=False, provider_message_id=None, failed_reason="provider_5xx")
        return await self.stub.send(recipient=recipient, **kwargs)


class _Audiences:
    async def resolve_academy_audience(self, audience: Any) -> list[ResolvedRecipient]:
        return [OWNER]


@pytest.fixture
def db() -> Any:
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["inquiry-ack"]
    asyncio.run(_M0192.up(db))
    asyncio.run(_M0215.up(db))
    return db


def _adapter(
    db: Any,
    *,
    secret: str | None = "s3cret",
    doc: dict[str, Any] = DOC,
    prospects_fail: bool = False,
) -> tuple[TrialRequestOwnerEmail, Any]:
    stub = StubEmailSendPort()
    opt_outs = MongoProspectOptOutRepository(db)
    inner: Any = _ProspectsFail(stub) if prospects_fail else stub
    sender = GatedEmailSendPort(inner=inner, prospects=ProspectOptOutGate(opt_outs))
    adapter = TrialRequestOwnerEmail(
        academies=_Academies(doc),
        audiences=_Audiences(),
        sender=sender,
        contacts=MongoCrmContactRepository(db),
        prospects=ProspectEmailer(
            sender=sender,
            unsubscribe_links=UnsubscribeLinkBuilder(
                frontend_url="https://app.courtmastr.test", secret=secret
            ),
        ),
    )
    return adapter, stub


async def _file(db: Any, contact: CrmContact) -> CrmContact:
    with tenant_scope(ACADEMY):
        stored, _created = await MongoCrmContactRepository(db).add_if_absent(contact)
    return stored


def _prospect_sends(stub: StubEmailSendPort) -> list[dict[str, Any]]:
    return [s for s in stub.sent if s["user_id"].startswith("crm_contact:")]


# --- template -----------------------------------------------------------------


def test_trial_names_the_class_and_says_a_seat_is_there() -> None:
    subject, inner = render_inquiry_acknowledgement(
        academy_name="Riverside Shuttle Club",
        contact=_contact(),
        class_title="Juniors Saturday",
        can_reply=True,
    )
    assert subject == "Your free trial request at Riverside Shuttle Club"
    assert "Hello," in inner and "Jamie" not in inner
    assert "<strong>Juniors Saturday</strong>" in inner
    assert "A seat is available" in inner
    assert "Reply to this email" in inner


def test_lead_with_a_full_class_is_the_waitlist_and_without_one_is_tell_me() -> None:
    _, waitlisted = render_inquiry_acknowledgement(
        academy_name="Riverside Shuttle Club",
        contact=_contact(pipeline_status="lead"),
        class_title="Juniors Sunday",
        can_reply=False,
    )
    assert "Juniors Sunday is full right now, so you are on the waitlist" in waitlisted
    assert "Reply to this email" not in waitlisted

    subject, notify = render_inquiry_acknowledgement(
        academy_name="Riverside Shuttle Club",
        contact=_contact(pipeline_status="lead"),
        class_title=None,
        can_reply=False,
    )
    assert subject == "Your inquiry at Riverside Shuttle Club"
    assert "not taking new players right now" in notify
    assert "waitlist" not in notify


def test_template_carries_no_submitter_text_and_escapes_academy_text() -> None:
    _, inner = render_inquiry_acknowledgement(
        academy_name="Riverside <b>",
        contact=_contact(name="Jo <script>", message="call 555-0100 now"),
        class_title="Juniors & <i>Co</i>",
        can_reply=False,
    )
    # The address is unverified, so nothing a submitter typed reaches the inbox.
    assert "Jo" not in inner and "555-0100" not in inner
    assert "<i>Co</i>" not in inner and "Juniors &amp; &lt;i&gt;Co&lt;/i&gt;" in inner
    assert "Riverside &lt;b&gt;" in inner


# --- send path ------------------------------------------------------------------


def test_new_contact_gets_one_themed_transactional_email_with_an_unsubscribe_link(
    db: Any,
) -> None:
    adapter, stub = _adapter(db)
    contact = asyncio.run(_file(db, _contact()))
    asyncio.run(
        adapter.notify(academy_id=ACADEMY, contact=contact, created=True, class_title="Juniors")
    )

    [ack] = _prospect_sends(stub)
    assert ack["user_id"] == f"crm_contact:{contact.contact_id}"
    assert ack["email"] == "jamie@example.test"
    assert ack["category"] == EmailCategory.TRANSACTIONAL
    assert ack["sender_name"] == "Riverside Shuttle Club"
    # No academy reply-to: no reply line, and never an owner's own address.
    assert ack["reply_to"] is None
    assert "Reply to this email" not in ack["body"]
    assert "Sent by Riverside Shuttle Club" in ack["body"]  # the shared shell
    assert (
        'href="https://riverside-academy.courtmastr.test/api/v2/unsubscribe/prospect?t=u1.'
        in ack["body"]
    )
    assert "Unsubscribe from these emails" in ack["body"]
    # The owner alert still goes out, once, as before.
    assert [s["email"] for s in stub.sent if s is not ack] == [OWNER.email]


def test_a_configured_reply_to_is_used_and_invites_a_reply(db: Any) -> None:
    adapter, stub = _adapter(db, doc={**DOC, "email_reply_to": "desk@example.com"})
    contact = asyncio.run(_file(db, _contact()))
    asyncio.run(adapter.notify(academy_id=ACADEMY, contact=contact, created=True, class_title=None))
    [ack] = _prospect_sends(stub)
    assert ack["reply_to"] == "desk@example.com"
    assert "Reply to this email" in ack["body"]


def test_without_a_secret_the_footer_still_ships_as_plain_text(db: Any) -> None:
    adapter, stub = _adapter(db, secret=None)
    contact = asyncio.run(_file(db, _contact()))
    asyncio.run(adapter.notify(academy_id=ACADEMY, contact=contact, created=True, class_title=None))
    [ack] = _prospect_sends(stub)
    assert "/unsubscribe/prospect" not in ack["body"]
    assert "Do not want these emails?" in ack["body"]


def test_second_notify_for_the_same_contact_sends_no_second_acknowledgement(db: Any) -> None:
    adapter, stub = _adapter(db)
    contact = asyncio.run(_file(db, _contact()))
    asyncio.run(adapter.notify(academy_id=ACADEMY, contact=contact, created=True, class_title=None))
    asyncio.run(adapter.notify(academy_id=ACADEMY, contact=contact, created=True, class_title=None))
    assert len(_prospect_sends(stub)) == 1

    async def _row() -> dict[str, Any]:
        return await db["crm_contacts"].find_one({"contact_id": contact.contact_id})

    assert asyncio.run(_row())["acknowledged_at"] is not None


def test_a_second_contact_for_the_same_address_within_a_day_is_not_acknowledged(db: Any) -> None:
    adapter, stub = _adapter(db)
    first = asyncio.run(_file(db, _contact()))
    # A different child age is a new contact row for the same address.
    second = asyncio.run(_file(db, _contact(contact_id="contact-2", child_age="11")))
    asyncio.run(adapter.notify(academy_id=ACADEMY, contact=first, created=True, class_title=None))
    asyncio.run(adapter.notify(academy_id=ACADEMY, contact=second, created=True, class_title=None))

    assert [s["user_id"] for s in _prospect_sends(stub)] == ["crm_contact:contact-1"]
    assert [s["email"] for s in stub.sent if s["user_id"] == OWNER.user_id] == [OWNER.email] * 2

    async def _row(contact_id: str) -> dict[str, Any]:
        return await db["crm_contacts"].find_one({"contact_id": contact_id})

    assert asyncio.run(_row("contact-2")).get("acknowledged_at") is None


def test_a_provider_failure_gives_the_claim_back_and_the_owner_is_still_alerted(db: Any) -> None:
    adapter, stub = _adapter(db, prospects_fail=True)
    contact = asyncio.run(_file(db, _contact()))
    asyncio.run(adapter.notify(academy_id=ACADEMY, contact=contact, created=True, class_title=None))

    assert [s["email"] for s in stub.sent] == [OWNER.email]

    async def _row() -> dict[str, Any]:
        return await db["crm_contacts"].find_one({"contact_id": contact.contact_id})

    assert "acknowledged_at" not in asyncio.run(_row())


def test_an_opted_out_address_gets_nothing_but_the_owner_is_still_alerted(db: Any) -> None:
    adapter, stub = _adapter(db)
    contact = asyncio.run(_file(db, _contact(email="Jamie@Example.test")))

    async def _opt_out() -> None:
        with tenant_scope(ACADEMY):
            await MongoProspectOptOutRepository(db).opt_out(
                email="jamie@example.test", recipient_id="crm_contact:older-contact"
            )

    asyncio.run(_opt_out())
    asyncio.run(adapter.notify(academy_id=ACADEMY, contact=contact, created=True, class_title=None))
    assert _prospect_sends(stub) == []
    assert [s["email"] for s in stub.sent] == [OWNER.email]


def test_repeat_or_honeypot_sends_nothing_to_the_family(db: Any) -> None:
    adapter, stub = _adapter(db)
    contact = asyncio.run(_file(db, _contact()))
    asyncio.run(
        adapter.notify(academy_id=ACADEMY, contact=contact, created=False, class_title=None)
    )
    asyncio.run(adapter.notify(academy_id=ACADEMY, contact=None, created=False, class_title=None))
    assert stub.sent == []
