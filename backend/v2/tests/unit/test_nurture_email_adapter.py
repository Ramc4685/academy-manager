"""The nurture step email (AI strategy Phase 3, C1): sent through the prospect
send path (``ProspectEmailer`` over ``GatedEmailSendPort`` with the real
``ProspectOptOutGate``) as ``CAMPAIGN`` to the ``crm_contact:<id>`` pseudo id,
with the unsubscribe footer, merge fields filled from the academy's own data
and everything escaped."""

from __future__ import annotations

import importlib
from datetime import UTC, datetime
from typing import Any

import mongomock_motor
import pytest

from backend.v2.composition.nurture import NurtureEmailAdapter
from backend.v2.composition.prospect_email import ProspectEmailer
from backend.v2.contexts.communications.application.unsubscribe_token import (
    UnsubscribeLinkBuilder,
)
from backend.v2.contexts.communications.domain.email_category import EmailCategory
from backend.v2.contexts.communications.infrastructure.gated_send_port import GatedEmailSendPort
from backend.v2.contexts.communications.infrastructure.mongo_prospect_opt_out_repo import (
    MongoProspectOptOutRepository,
    ProspectOptOutGate,
)
from backend.v2.contexts.communications.infrastructure.stub_send_port import StubEmailSendPort
from backend.v2.contexts.crm.domain.models import ContactConsent, CrmContact
from backend.v2.contexts.crm.domain.nurture import NurtureStep, render_html
from backend.v2.contexts.enrollment.application.use_cases.public_catalog import (
    PublicCatalogSession,
)
from backend.v2.contexts.enrollment.domain.programs import ClassPublicProfile
from backend.v2.shared.tenancy import tenant_scope

pytestmark = pytest.mark.asyncio

ACADEMY = "acad-riverside"
NOW = datetime(2026, 11, 4, 15, 0, tzinfo=UTC)
DOC = {
    "academy_id": ACADEMY,
    "slug": "riverside",
    "display_name": "Riverside <Shuttle> Club",
    "reply_to_email": "hello@riverside.example.test",
}
STEP = NurtureStep(
    day=7,
    subject="{{class}} at {{academy_name}}",
    body="Hi!\n\n{{seat_band}} Book here: {{booking_link}}",
)
_M0217 = importlib.import_module("backend.v2.migrations.0217_email_prospect_opt_outs")


class Academies:
    async def find_by_id(self, academy_id: str) -> dict[str, Any] | None:
        return dict(DOC) if academy_id == ACADEMY else None


class Sessions:
    def __init__(self, occupied: int = 8, published: bool = True) -> None:
        self.row = PublicCatalogSession(
            profile=ClassPublicProfile(session_id="sess-1", published=published),
            title="Junior & Teens",
            capacity=10,
            occupied_seats=occupied,
        )

    async def available_for_public_catalog(self) -> list[PublicCatalogSession]:
        return [self.row]


def _contact(**overrides: Any) -> CrmContact:
    fields: dict[str, Any] = {
        "contact_id": "c1",
        "academy_id": ACADEMY,
        "name": "Jamie <script>",
        "email": "jamie@example.test",
        "source": "website",
        "requested_session_id": "sess-1",
        "consent": ContactConsent(contact_about_request=True, marketing=True, captured_at=NOW),
        "created_at": NOW,
        "updated_at": NOW,
    }
    fields.update(overrides)
    return CrmContact(**fields)


async def _adapter(sessions: Sessions | None = None, secret: str | None = "s3cret"):
    db = mongomock_motor.AsyncMongoMockClient()["nurture-email"]
    await _M0217.up(db)
    stub = StubEmailSendPort()
    opt_outs = MongoProspectOptOutRepository(db)
    adapter = NurtureEmailAdapter(
        academies=Academies(),
        sessions=sessions or Sessions(),
        prospects=ProspectEmailer(
            sender=GatedEmailSendPort(inner=stub, prospects=ProspectOptOutGate(opt_outs)),
            unsubscribe_links=UnsubscribeLinkBuilder(
                frontend_url="https://app.courtmastr.test", secret=secret
            ),
        ),
        frontend_url="https://app.courtmastr.test",
    )
    return adapter, stub, opt_outs


async def test_sends_a_campaign_email_to_the_prospect_with_the_footer() -> None:
    adapter, stub, _ = await _adapter()
    with tenant_scope(ACADEMY):
        assert await adapter.send_step(contact=_contact(), step=STEP) == "sent"
    (sent,) = stub.sent
    assert sent["user_id"] == "crm_contact:c1"
    assert sent["category"] == EmailCategory.CAMPAIGN
    assert sent["subject"] == "Junior & Teens at Riverside <Shuttle> Club"
    body = sent["body"]
    assert "/api/v2/unsubscribe/prospect?t=" in body
    assert "Only 2 seats are left." in body
    assert '<a href="https://riverside.courtmastr.test/">' in body
    assert "Riverside &lt;Shuttle&gt; Club" in body
    # Nothing the lead typed is merged into the email.
    assert "Jamie" not in body and "<script>" not in body


async def test_an_opted_out_address_is_skipped_for_good() -> None:
    adapter, stub, opt_outs = await _adapter()
    with tenant_scope(ACADEMY):
        await opt_outs.opt_out(email="jamie@example.test", recipient_id="crm_contact:c1")
        assert await adapter.send_step(contact=_contact(), step=STEP) == "skipped"
    assert stub.sent == []


async def test_no_unsubscribe_link_sends_nothing_and_retries() -> None:
    adapter, stub, _ = await _adapter(secret=None)
    with tenant_scope(ACADEMY):
        assert await adapter.send_step(contact=_contact(), step=STEP) == "failed"
    assert stub.sent == []


@pytest.mark.parametrize(
    ("contact", "sessions", "expected"),
    [
        (_contact(requested_session_id=None), Sessions(), "Reply and we will find you a class"),
        (_contact(), Sessions(occupied=10), "The class is full right now"),
        (_contact(), Sessions(occupied=1), "There are seats available."),
        (_contact(), Sessions(published=False), "Reply and we will find you a class"),
    ],
)
async def test_seat_band_follows_the_class_the_lead_asked_about(
    contact: CrmContact, sessions: Sessions, expected: str
) -> None:
    adapter, stub, _ = await _adapter(sessions)
    with tenant_scope(ACADEMY):
        await adapter.send_step(contact=contact, step=STEP)
    assert expected in stub.sent[0]["body"]


async def test_render_html_escapes_the_template_and_keeps_paragraphs() -> None:
    out = render_html("<b>Hi</b> {{class}}\nline two\n\nnext", {"class": "A & B"})
    assert out == (
        '<p style="margin:0 0 12px;">&lt;b&gt;Hi&lt;/b&gt; A &amp; B<br>line two</p>'
        '<p style="margin:0 0 12px;">next</p>'
    )
