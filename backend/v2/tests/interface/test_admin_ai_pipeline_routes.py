"""Interface tests for the B3 pipeline reply routes: the real admin router,
``DraftPipelineReply`` and ``SendPipelineReply`` over fakes. Admin 200, coach
and parent 404, a foreign-tenant contact 404, and the AI error codes the
frontend maps (503 Ai.Disabled, 403 Ai.NotEntitled, 429, 409)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.contexts.ai.application.use_cases.draft_pipeline_reply import (
    DraftPipelineReply,
    InquiryFacts,
    ReplyContext,
)
from backend.v2.contexts.ai.application.use_cases.record_ai_call import RecordAiCall
from backend.v2.contexts.ai.domain.models import DEFAULT_MODEL, AiCallRecord, LlmResult
from backend.v2.contexts.ai.infrastructure.disabled_llm_port import DisabledLlmPort
from backend.v2.contexts.crm.application.family_messages import LogFamilyContact
from backend.v2.contexts.crm.application.use_cases.send_pipeline_reply import SendPipelineReply
from backend.v2.contexts.crm.domain.family_messages import FamilyContactLog
from backend.v2.contexts.crm.domain.models import ContactConsent, CrmContact
from backend.v2.interfaces.admin import ai_pipeline_routes
from backend.v2.interfaces.admin.router import router as admin_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers
from backend.v2.shared.tenancy import current_academy_id
from backend.v2.shared.tenancy.context import _current as _tenant
from backend.v2.tests.fixtures.ai_counters import counters_at

A = "acad-a"
B = "acad-b"
NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
DRAFT = "/api/v2/admin/pipeline/cards/contact-1/reply-draft"
REPLY = "/api/v2/admin/pipeline/cards/contact-1/reply"
GOOD = json.dumps({"subject": "Hello", "body": "Thanks for asking. Sam", "key_points": ["a"]})


def _contact(academy_id: str, email: str | None = "jamie@example.test") -> CrmContact:
    return CrmContact(
        contact_id="contact-1",
        academy_id=academy_id,
        name="Jamie Testparent",
        email=email,
        phone_digits=None if email else "5550102030",
        source="website",
        child_age="9",
        message="Saturdays?",
        consent=ContactConsent(contact_about_request=True, captured_at=NOW),
        created_at=NOW,
        updated_at=NOW,
    )


class Contacts:
    """Tenant-scoped like ``MongoCrmContactRepository``."""

    def __init__(self) -> None:
        self.rows: list[CrmContact] = [_contact(A)]

    async def get(self, contact_id: str) -> CrmContact | None:
        academy = current_academy_id()
        return next(
            (r for r in self.rows if r.academy_id == academy and r.contact_id == contact_id), None
        )


class Inquiries:
    def __init__(self, contacts: Contacts) -> None:
        self.contacts = contacts

    async def inquiry_facts(self, contact_id: str) -> InquiryFacts | None:
        contact = await self.contacts.get(contact_id)
        if contact is None:
            return None
        return InquiryFacts(contact.message, (contact.child_age or "",), None)


class Llm:
    def __init__(self, text: str = GOOD) -> None:
        self.text = text
        self.calls = 0

    async def complete(self, **kwargs: Any) -> LlmResult:
        self.calls += 1
        return LlmResult(
            text=self.text, input_tokens=1, output_tokens=1, cost_cents=1, model=DEFAULT_MODEL
        )


class Calls:
    def __init__(self) -> None:
        self.used = 0
        self.recorded: list[AiCallRecord] = []

    async def count_since(self, since: datetime) -> int:
        return self.used

    async def record(self, call: AiCallRecord) -> None:
        self.recorded.append(call)


class Cap:
    async def monthly_cap(self) -> int:
        return 2


class Entitlement:
    def __init__(self) -> None:
        self.entitled = True

    async def has_ai(self) -> bool:
        return self.entitled


class Context:
    async def reply_context(self) -> ReplyContext:
        return ReplyContext("Riverside", None, None, ())


class Staff:
    async def first_name(self, user_id: str) -> str | None:
        return "Sam"


class Emailer:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    async def send_reply(self, *, contact: CrmContact, subject: str, body: str) -> Any:
        self.sent.append((contact.contact_id, subject, body))
        return SimpleNamespace(ok=True, suppressed=False, failed_reason=None)


class Logs:
    def __init__(self) -> None:
        self.rows: list[FamilyContactLog] = []

    async def add(self, entry: FamilyContactLog) -> FamilyContactLog:
        self.rows.append(entry)
        return entry


class LeadDirectory:
    async def find(self, academy_id: str, family_id: str) -> Any:
        return SimpleNamespace(family_id=family_id, parent_name=None)


class Caller:
    def __init__(self) -> None:
        self.be("staff-1", "admin")

    def be(self, user_id: str, *roles: str, academy_id: str = A) -> None:
        self.claims = AuthClaims(
            user_id=user_id,
            email=f"{user_id}@example.test",
            academy_id=academy_id,
            roles=roles,  # type: ignore[arg-type]
        )


@pytest.fixture
def caller() -> Caller:
    return Caller()


@pytest.fixture
def world() -> SimpleNamespace:
    contacts = Contacts()
    return SimpleNamespace(
        contacts=contacts,
        llm=Llm(),
        calls=Calls(),
        counters=counters_at(),
        entitlement=Entitlement(),
        emailer=Emailer(),
        logs=Logs(),
    )


def _services(world: SimpleNamespace, llm: Any) -> SimpleNamespace:
    return SimpleNamespace(
        draft_reply=DraftPipelineReply(
            llm=llm,
            record_ai_call=RecordAiCall(
                calls=world.calls, counters=world.counters, cap_source=Cap(), clock=lambda: NOW
            ),
            entitlement=world.entitlement,
            inquiries=Inquiries(world.contacts),
            context=Context(),
            staff=Staff(),
        ),
        send_reply=SendPipelineReply(
            world.contacts, world.emailer, LogFamilyContact(world.logs, LeadDirectory())
        ),
    )


@pytest.fixture
def client(caller: Caller, world: SimpleNamespace) -> Iterator[TestClient]:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(admin_router, prefix="/api/v2")

    async def claims() -> AuthClaims:
        _tenant.set(caller.claims.academy_id)
        return caller.claims

    app.dependency_overrides[get_auth_claims] = claims
    app.dependency_overrides[ai_pipeline_routes.get_ai_pipeline] = lambda: _services(
        world, world.llm
    )
    with TestClient(app) as c:
        yield c


def test_admin_gets_a_draft_and_the_call_is_recorded(
    client: TestClient, world: SimpleNamespace
) -> None:
    response = client.post(DRAFT)
    assert response.status_code == 200, response.text
    assert response.json() == {
        "subject": "Hello",
        "body": "Thanks for asking. Sam",
        "key_points": ["a"],
        "prompt_version": "pipeline-reply-v1",
    }
    assert [r.approver for r in world.calls.recorded] == ["staff-1"]


def test_ai_off_is_503_ai_disabled(client: TestClient, world: SimpleNamespace) -> None:
    world.llm = DisabledLlmPort()
    response = client.post(DRAFT)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "Ai.Disabled"
    assert world.calls.recorded == []


def test_not_entitled_is_403_and_cap_is_429(client: TestClient, world: SimpleNamespace) -> None:
    world.entitlement.entitled = False
    response = client.post(DRAFT)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "Ai.NotEntitled"

    world.entitlement.entitled = True
    world.counters.counts["month:2026-11"] = 2
    response = client.post(DRAFT)
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "Ai.MonthlyCapReached"
    assert world.llm.calls == 0


def test_unreadable_answer_is_502_but_counted(client: TestClient, world: SimpleNamespace) -> None:
    world.llm = Llm("not json")
    response = client.post(DRAFT)
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "Ai.ProviderError"
    assert len(world.calls.recorded) == 1


def test_reply_sends_and_returns_the_log_entry(client: TestClient, world: SimpleNamespace) -> None:
    response = client.post(REPLY, json={"subject": "Hello", "body": "Thanks. Sam"})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["channel"] == "email" and body["status"] == "logged"
    assert body["author_user_id"] == "staff-1"
    assert body["parent_id"] == "crm_contact:contact-1"
    assert world.emailer.sent == [("contact-1", "Hello", "Thanks. Sam")]
    assert (
        client.post(REPLY, json={"subject": "x", "body": "y", "academy_id": B}).status_code == 422
    )


def test_lead_without_email_is_409(client: TestClient, world: SimpleNamespace) -> None:
    world.contacts.rows = [_contact(A, email=None)]
    response = client.post(REPLY, json={"subject": "Hello", "body": "Thanks. Sam"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "Crm.PipelineReplyNotSendable"
    assert world.emailer.sent == [] and world.logs.rows == []


def test_foreign_tenant_contact_is_404(
    client: TestClient, caller: Caller, world: SimpleNamespace
) -> None:
    caller.be("staff-b", "admin", academy_id=B)
    assert client.post(DRAFT).status_code == 404
    assert client.post(REPLY, json={"subject": "s", "body": "b"}).status_code == 404
    assert world.llm.calls == 0 and world.emailer.sent == []


def test_wrong_persona_is_404(client: TestClient, caller: Caller, world: SimpleNamespace) -> None:
    for roles in (("coach",), ("parent",)):
        caller.be("someone", *roles)
        assert client.post(DRAFT).status_code == 404
        assert client.post(REPLY, json={"subject": "s", "body": "b"}).status_code == 404
    assert world.llm.calls == 0 and world.emailer.sent == []
