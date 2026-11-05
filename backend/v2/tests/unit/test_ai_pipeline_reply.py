"""B3: the AI-drafted pipeline reply (AI strategy Phase 2, Track B, paid).

Order inside the use case (entitlement, cap, model, record, parse), the
audit row with the staff approver, a malformed answer still counted, and the
prompt-content test: the model sees exactly the allowed facts and none of
the parent's name, email, phone, child name or another family's message.
"""

from __future__ import annotations

import asyncio
import importlib
import json
from datetime import UTC, datetime
from typing import Any

import pytest

from backend.v2.composition.ai import PlatformAiEntitlement
from backend.v2.composition.ai_pipeline import CrmInquirySource, class_line
from backend.v2.contexts.ai.application.use_cases.draft_pipeline_reply import (
    FEATURE,
    MAX_TOKENS,
    DraftPipelineReply,
    InquiryFacts,
    InquiryNotFound,
    PipelineReplyInput,
    ReplyContext,
    parse_reply_draft,
)
from backend.v2.contexts.ai.application.use_cases.record_ai_call import RecordAiCall
from backend.v2.contexts.ai.domain.errors import AiMonthlyCapReached, AiNotEntitled, AiProviderError
from backend.v2.contexts.ai.domain.models import DEFAULT_MODEL, AiCallRecord, LlmResult
from backend.v2.contexts.ai.domain.prompts import PROMPTS
from backend.v2.contexts.crm.domain.models import ContactConsent, CrmContact
from backend.v2.contexts.crm.infrastructure.mongo_crm_contact_repo import (
    MongoCrmContactRepository,
)
from backend.v2.contexts.enrollment.application.use_cases.public_catalog import (
    PublicClassView,
    PublicPrice,
)
from backend.v2.shared.tenancy import tenant_scope

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
GOOD = json.dumps(
    {
        "subject": "About classes at Riverside",
        "body": "Hi, thanks for asking. Our Juniors class meets on Saturdays. See https://riverside.courtmastr.test for details. Sam",
        "key_points": ["Juniors Saturday", "free trial open"],
    }
)
CONTEXT = ReplyContext(
    academy_name="Riverside Shuttle Club",
    public_page_url="https://riverside.courtmastr.test",
    trial_offer="Free trial classes are open; the academy confirms a date and time.",
    class_context=("Juniors (Sat 09:00-10:00); USD 120.00 per month",),
)


class FakeLlm:
    def __init__(self, text: str = GOOD) -> None:
        self.text = text
        self.calls: list[dict[str, Any]] = []

    async def complete(self, *, prompt_version: str, system: str, user: str, max_tokens: int):
        self.calls.append(
            {"prompt_version": prompt_version, "system": system, "user": user, "max": max_tokens}
        )
        return LlmResult(
            text=self.text, input_tokens=100, output_tokens=50, cost_cents=1, model=DEFAULT_MODEL
        )


class FakeCalls:
    def __init__(self, used: int = 0) -> None:
        self.used = used
        self.recorded: list[AiCallRecord] = []

    async def count_since(self, since: datetime) -> int:
        return self.used

    async def record(self, call: AiCallRecord) -> None:
        self.recorded.append(call)


class FakeCap:
    async def monthly_cap(self) -> int:
        return 5


class FakeEntitlement:
    def __init__(self, entitled: bool = True) -> None:
        self.entitled = entitled

    async def has_ai(self) -> bool:
        return self.entitled


class FakeInquiries:
    def __init__(self, facts: InquiryFacts | None) -> None:
        self.facts = facts

    async def inquiry_facts(self, contact_id: str) -> InquiryFacts | None:
        return self.facts


class FakeContext:
    async def reply_context(self) -> ReplyContext:
        return CONTEXT


class FakeStaff:
    async def first_name(self, user_id: str) -> str | None:
        return "Sam"


FACTS = InquiryFacts(
    inquiry_message="Hi, my 9 year old wants to try badminton on Saturdays.",
    child_ages=("9",),
    interest="Juniors Saturday",
)


def _use_case(
    *,
    llm: FakeLlm | None = None,
    calls: FakeCalls | None = None,
    entitled: bool = True,
    inquiries: Any = None,
) -> tuple[DraftPipelineReply, FakeLlm, FakeCalls]:
    llm = llm or FakeLlm()
    calls = calls or FakeCalls()
    use_case = DraftPipelineReply(
        llm=llm,
        record_ai_call=RecordAiCall(calls=calls, cap_source=FakeCap(), clock=lambda: NOW),
        entitlement=FakeEntitlement(entitled),
        inquiries=inquiries or FakeInquiries(FACTS),
        context=FakeContext(),
        staff=FakeStaff(),
    )
    return use_case, llm, calls


def test_prompt_registry_ends_with_pipeline_reply_v1() -> None:
    assert PROMPTS[FEATURE].version == "pipeline-reply-v1"
    assert "JSON only" in PROMPTS[FEATURE].system_text
    assert "untrusted data" in PROMPTS[FEATURE].system_text


async def test_entitled_under_cap_drafts_and_records_with_the_staff_approver() -> None:
    use_case, llm, calls = _use_case()

    result = await use_case.execute(contact_id="c1", staff_user_id="staff-1")

    assert result.prompt_version == "pipeline-reply-v1"
    assert result.draft.subject == "About classes at Riverside"
    assert result.draft.key_points == ["Juniors Saturday", "free trial open"]
    assert llm.calls[0]["max"] == MAX_TOKENS
    assert llm.calls[0]["system"] == PROMPTS[FEATURE].system_text
    [row] = calls.recorded
    assert (row.feature, row.prompt_version, row.approver) == (
        FEATURE,
        "pipeline-reply-v1",
        "staff-1",
    )


async def test_not_entitled_refuses_before_the_port_is_called() -> None:
    use_case, llm, calls = _use_case(entitled=False)
    with pytest.raises(AiNotEntitled):
        await use_case.execute(contact_id="c1", staff_user_id="staff-1")
    assert llm.calls == [] and calls.recorded == []


async def test_cap_refuses_before_the_port_is_called() -> None:
    use_case, llm, calls = _use_case(calls=FakeCalls(used=5))
    with pytest.raises(AiMonthlyCapReached):
        await use_case.execute(contact_id="c1", staff_user_id="staff-1")
    assert llm.calls == [] and calls.recorded == []


async def test_unknown_contact_is_404_before_anything_else() -> None:
    use_case, llm, calls = _use_case(inquiries=FakeInquiries(None), entitled=False)
    with pytest.raises(InquiryNotFound):
        await use_case.execute(contact_id="nope", staff_user_id="staff-1")
    assert llm.calls == [] and calls.recorded == []


@pytest.mark.parametrize(
    "text",
    [
        "Sure! Here is a reply.",
        json.dumps({"subject": "x" * 91, "body": "ok", "key_points": []}),
        json.dumps({"subject": "ok", "body": "ok", "key_points": [], "extra": 1}),
        json.dumps({"subject": "ok", "body": "see https://evil.example/x", "key_points": []}),
    ],
)
async def test_malformed_answer_is_502_after_the_call_was_recorded(text: str) -> None:
    use_case, _llm, calls = _use_case(llm=FakeLlm(text))
    with pytest.raises(AiProviderError):
        await use_case.execute(contact_id="c1", staff_user_id="staff-1")
    assert len(calls.recorded) == 1


def test_parse_strips_a_json_fence_and_allows_only_the_public_url() -> None:
    draft = parse_reply_draft(f"```json\n{GOOD}\n```", allowed_url=CONTEXT.public_page_url)
    assert draft.subject == "About classes at Riverside"
    with pytest.raises(AiProviderError):
        parse_reply_draft(GOOD, allowed_url=None)


def _body(text: str) -> str:
    return json.dumps({"subject": "ok", "body": text, "key_points": []})


@pytest.mark.parametrize(
    "text",
    [
        "Visit www.evil.example today.",
        "Write to mailto:coach@evil.example please.",
        "See HTTPS://EVIL.EXAMPLE/offer for details.",
        "Book at evil.example/book now.",
        "Our friends at other-academy.com can help.",
        "See evil.courtmastr.test for more.",
        "Try https://academy.courtmastr.test.evil.example/x today.",
    ],
)
def test_parse_rejects_bare_domain_and_mailto_links(text: str) -> None:
    with pytest.raises(AiProviderError):
        parse_reply_draft(_body(text), allowed_url=CONTEXT.public_page_url)


def test_parse_accepts_the_public_url_with_or_without_a_trailing_slash() -> None:
    url = CONTEXT.public_page_url
    assert url is not None
    parse_reply_draft(_body(f"See {url}/."), allowed_url=url)
    parse_reply_draft(_body(f"See {url}."), allowed_url=url + "/")


# --- prompt content ---------------------------------------------------------------

_M0192 = importlib.import_module("backend.v2.migrations.0192_crm_contacts")


class _Sessions:
    async def get(self, session_id: str) -> Any:
        from types import SimpleNamespace

        return SimpleNamespace(title="Juniors Saturday") if session_id == "sess-1" else None


def _contact(**overrides: Any) -> CrmContact:
    fields: dict[str, Any] = {
        "contact_id": "contact-1",
        "academy_id": "acad-a",
        "name": "Jamie Testparent",
        "email": "jamie.testparent@example.test",
        "phone_digits": "5550102030",
        "source": "website",
        "child_name": "Secretchild",
        "child_age": "9",
        "requested_session_id": "sess-1",
        "message": "My 9 year old wants to try badminton on Saturdays.",
        "consent": ContactConsent(contact_about_request=True, captured_at=NOW),
        "created_at": NOW,
        "updated_at": NOW,
    }
    fields.update(overrides)
    return CrmContact(**fields)


@pytest.fixture
def db() -> Any:
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["ai-pipeline-reply"]
    asyncio.run(_M0192.up(db))
    return db


async def test_the_model_sees_exactly_the_allowed_facts_and_no_personal_data(db: Any) -> None:
    repo = MongoCrmContactRepository(db)
    with tenant_scope("acad-a"):
        await repo.add_if_absent(_contact())
        await repo.add_if_absent(
            _contact(
                contact_id="contact-2",
                name="Other Family",
                email="other@example.test",
                message="Other family card 4242 4242 4242 4242, 12 Elm Street",
            )
        )
        use_case, llm, _calls = _use_case(inquiries=CrmInquirySource(repo, _Sessions()))
        await use_case.execute(contact_id="contact-1", staff_user_id="staff-1")

    [call] = llm.calls
    sent = json.loads(call["user"])
    assert set(sent) == set(PipelineReplyInput.model_fields)
    assert sent == {
        "academy_name": "Riverside Shuttle Club",
        "staff_first_name": "Sam",
        "inquiry_message": "My 9 year old wants to try badminton on Saturdays.",
        "child_ages": ["9"],
        "interest": "Juniors Saturday",
        "class_context": list(CONTEXT.class_context),
        "trial_offer": CONTEXT.trial_offer,
        "public_page_url": CONTEXT.public_page_url,
    }
    everything = call["system"] + call["user"]
    for forbidden in (
        "Testparent",
        "Jamie",
        "jamie.testparent@example.test",
        "5550102030",
        "Secretchild",
        "Other Family",
        "other@example.test",
        "4242",
        "Elm Street",
        "academy_id",
        "contact-1",
    ):
        assert forbidden not in everything, forbidden


async def test_another_academys_contact_is_not_found(db: Any) -> None:
    repo = MongoCrmContactRepository(db)
    with tenant_scope("acad-b"):
        await repo.add_if_absent(_contact(academy_id="acad-b"))
    with tenant_scope("acad-a"):
        use_case, llm, _calls = _use_case(inquiries=CrmInquirySource(repo, _Sessions()))
        with pytest.raises(InquiryNotFound):
            await use_case.execute(contact_id="contact-1", staff_user_id="staff-1")
    assert llm.calls == []


# --- composition adapters ------------------------------------------------------


class _HasFeature:
    def __init__(self, answer: bool) -> None:
        self.answer = answer
        self.asked: list[tuple[str, str]] = []

    async def execute(self, academy_id: str, feature: str) -> bool:
        self.asked.append((academy_id, feature))
        return self.answer


async def test_platform_entitlement_is_false_without_has_feature_and_follows_it_otherwise() -> None:
    assert await PlatformAiEntitlement(None).has_ai() is False
    has_feature = _HasFeature(True)
    with tenant_scope("acad-a"):
        assert await PlatformAiEntitlement(has_feature).has_ai() is True
    assert has_feature.asked == [("acad-a", "ai")]


def test_class_line_names_schedule_and_price_only_when_shown() -> None:
    view = PublicClassView(
        public_id="p1",
        title="Juniors",
        days_of_week=("Sat",),
        start_time="09:00",
        end_time="10:00",
        price=PublicPrice(amount_cents=12000, period="month"),
    )
    assert (
        class_line(view, program="Beginners", currency="USD")
        == "Beginners: Juniors (Sat 09:00-10:00); USD 120.00 per month"
    )
    hidden = view.model_copy(update={"price": None, "days_of_week": (), "start_time": None})
    assert class_line(hidden, program=None, currency="USD") == "Juniors"
