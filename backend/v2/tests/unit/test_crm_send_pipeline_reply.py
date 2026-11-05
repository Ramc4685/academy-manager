"""B3: the human-approved send of a pipeline reply.

Through the real prospect send path (``ProspectEmailer`` over the gated port
with the lead opt-out gate) on mongomock: a suppressed lead is refused and
nothing is sent, a lead with no email is refused, a sent reply carries the
CAN-SPAM footer and is logged on the family contact log by the staff actor.
"""

from __future__ import annotations

import asyncio
import importlib
from datetime import UTC, datetime
from typing import Any

import pytest

from backend.v2.composition.ai_pipeline import LeadOrFamilyDirectory, ProspectReplyEmailer
from backend.v2.composition.prospect_email import ProspectEmailer
from backend.v2.contexts.communications.application.unsubscribe_token import (
    UnsubscribeLinkBuilder,
)
from backend.v2.contexts.communications.infrastructure.gated_send_port import (
    GatedEmailSendPort,
)
from backend.v2.contexts.communications.infrastructure.mongo_prospect_opt_out_repo import (
    MongoProspectOptOutRepository,
    ProspectOptOutGate,
)
from backend.v2.contexts.communications.infrastructure.stub_send_port import StubEmailSendPort
from backend.v2.contexts.crm.application.family_messages import LogFamilyContact
from backend.v2.contexts.crm.application.use_cases.family_notes import Actor
from backend.v2.contexts.crm.application.use_cases.send_pipeline_reply import (
    SendPipelineReply,
    contact_log_parent_id,
)
from backend.v2.contexts.crm.domain.errors import ContactNotFound, PipelineReplyNotSendable
from backend.v2.contexts.crm.domain.models import ContactConsent, CrmContact
from backend.v2.contexts.crm.infrastructure.mongo_crm_contact_repo import (
    MongoCrmContactRepository,
)
from backend.v2.contexts.crm.infrastructure.mongo_family_contact_log_repo import (
    MongoFamilyContactLogRepository,
)
from backend.v2.shared.tenancy import tenant_scope

ACADEMY = "acad-riverside"
NOW = datetime(2026, 11, 4, 15, 0, tzinfo=UTC)
DOC = {"academy_id": ACADEMY, "slug": "riverside", "display_name": "Riverside Shuttle Club"}
STAFF = Actor(user_id="staff-1", roles=("admin",))
_M0192 = importlib.import_module("backend.v2.migrations.0192_crm_contacts")
_M0217 = importlib.import_module("backend.v2.migrations.0217_email_prospect_opt_outs")


def _contact(**overrides: Any) -> CrmContact:
    fields: dict[str, Any] = {
        "contact_id": "contact-1",
        "academy_id": ACADEMY,
        "name": "Jamie Testparent",
        "email": "jamie@example.test",
        "source": "website",
        "child_age": "9",
        "message": "Saturdays?",
        "consent": ContactConsent(contact_about_request=True, captured_at=NOW),
        "created_at": NOW,
        "updated_at": NOW,
    }
    fields.update(overrides)
    return CrmContact(**fields)


class _Academies:
    async def find_by_id(self, academy_id: str) -> dict[str, Any]:
        return dict(DOC)


class _NoFamilies:
    async def find(self, academy_id: str, family_id: str) -> None:
        return None

    async def names(self, academy_id: str) -> dict[str, str | None]:
        return {}


@pytest.fixture
def db() -> Any:
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["send-pipeline-reply"]
    asyncio.run(_M0192.up(db))
    asyncio.run(_M0217.up(db))
    return db


def _use_case(db: Any) -> tuple[SendPipelineReply, StubEmailSendPort]:
    stub = StubEmailSendPort()
    sender = GatedEmailSendPort(
        inner=stub, prospects=ProspectOptOutGate(MongoProspectOptOutRepository(db))
    )
    contacts = MongoCrmContactRepository(db)
    use_case = SendPipelineReply(
        contacts,
        ProspectReplyEmailer(
            ProspectEmailer(
                sender=sender,
                unsubscribe_links=UnsubscribeLinkBuilder(
                    frontend_url="https://app.courtmastr.test", secret="s3cret"
                ),
            ),
            _Academies(),
        ),
        LogFamilyContact(
            MongoFamilyContactLogRepository(db), LeadOrFamilyDirectory(contacts, _NoFamilies())
        ),
    )
    return use_case, stub


async def _file(db: Any, contact: CrmContact) -> None:
    with tenant_scope(ACADEMY):
        await MongoCrmContactRepository(db).add_if_absent(contact)


async def test_sent_reply_carries_the_footer_and_is_logged_by_the_staff_actor(db: Any) -> None:
    await _file(db, _contact())
    use_case, stub = _use_case(db)
    with tenant_scope(ACADEMY):
        row = await use_case.execute(
            academy_id=ACADEMY,
            contact_id="contact-1",
            subject="About Saturdays",
            body="Hi,\n\nYes, Juniors meets on Saturdays.\n\nSam",
            actor=STAFF,
        )
        logged = await MongoFamilyContactLogRepository(db).get("crm_contact:contact-1", row.log_id)

    [sent] = stub.sent
    assert sent["user_id"] == "crm_contact:contact-1" and sent["email"] == "jamie@example.test"
    assert sent["subject"] == "About Saturdays"
    assert "Yes, Juniors meets on Saturdays." in sent["body"]
    assert "Unsubscribe from these emails" in sent["body"]
    assert "/api/v2/unsubscribe/prospect" in sent["body"]
    assert str(sent["category"]) == "transactional"
    assert logged is not None and logged == row
    assert (row.channel, row.status, row.author_user_id) == ("email", "logged", "staff-1")
    assert row.note == "Subject: About Saturdays\n\nHi,\n\nYes, Juniors meets on Saturdays.\n\nSam"


async def test_suppressed_lead_is_refused_and_nothing_is_sent(db: Any) -> None:
    await _file(db, _contact())
    with tenant_scope(ACADEMY):
        await MongoProspectOptOutRepository(db).opt_out(
            email="jamie@example.test", recipient_id="crm_contact:contact-1"
        )
    use_case, stub = _use_case(db)
    with tenant_scope(ACADEMY), pytest.raises(PipelineReplyNotSendable) as exc:
        await use_case.execute(
            academy_id=ACADEMY, contact_id="contact-1", subject="s", body="b", actor=STAFF
        )
    assert exc.value.details["reason"] == "suppressed"
    assert stub.sent == []
    assert await db["family_contact_log"].count_documents({}) == 0


async def test_lead_without_email_is_refused_before_any_send(db: Any) -> None:
    await _file(db, _contact(email=None, phone_digits="5550102030"))
    use_case, stub = _use_case(db)
    with tenant_scope(ACADEMY), pytest.raises(PipelineReplyNotSendable) as exc:
        await use_case.execute(
            academy_id=ACADEMY, contact_id="contact-1", subject="s", body="b", actor=STAFF
        )
    assert exc.value.details["reason"] == "no_email"
    assert stub.sent == []


async def test_another_academys_contact_is_not_found(db: Any) -> None:
    await _file(db, _contact())
    use_case, stub = _use_case(db)
    with tenant_scope("acad-other"), pytest.raises(ContactNotFound):
        await use_case.execute(
            academy_id="acad-other", contact_id="contact-1", subject="s", body="b", actor=STAFF
        )
    assert stub.sent == []


def test_log_lands_on_the_linked_family_when_there_is_one() -> None:
    assert contact_log_parent_id(_contact(linked_family_id="fam-1")) == "fam-1"
    assert contact_log_parent_id(_contact(converted_parent_id="par-1")) == "par-1"
    assert contact_log_parent_id(_contact()) == "crm_contact:contact-1"
