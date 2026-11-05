"""B5 month-close narrator: reducer, the never-computes-money check, gate
order, prompt content and the entitlement adapter."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest

from backend.v2.composition.ai import PlatformAiEntitlement
from backend.v2.contexts.ai.application.use_cases.narrate_month_close import (
    FEATURE,
    MAX_TOKENS,
    NarrateMonthClose,
    Narrative,
    check_narrative,
    parse_narrative,
    reduce_month_close_payload,
)
from backend.v2.contexts.ai.application.use_cases.record_ai_call import RecordAiCall
from backend.v2.contexts.ai.domain.errors import (
    AiMonthlyCapReached,
    AiNotEntitled,
    AiProviderError,
)
from backend.v2.contexts.ai.domain.models import AiCallRecord, LlmResult
from backend.v2.contexts.ai.domain.prompts import PROMPTS
from backend.v2.shared.tenancy import tenant_scope

PARENT_EMAIL = "dana.whitfield@example.com"
PARENT_PHONE = "+1 555 010 9988"


def payload() -> dict[str, Any]:
    """``build_month_close_view``'s shape, with forbidden data seeded next to
    the allowed fields."""
    items = [
        {
            "kind": "family",
            "id": f"par-{i}",
            "label": f"Whitfield family {i}",
            "href": f"/admin/families/par-{i}",
            "email": PARENT_EMAIL,
            "phone": PARENT_PHONE,
        }
        for i in range(8)
    ]
    return {
        "generated_at": "2026-09-20T15:00:00+00:00",
        "timezone": "America/Chicago",
        "period": "2026-09",
        "parent_email": PARENT_EMAIL,
        "invoices": {
            "generated": 12,
            "emailed": 4,
            "autopay_notices": 7,
            "not_sent": 1,
            "voided": 1,
            "voided_cents": 5_000,
            "void_reasons": [{"reason": f"duplicate for {PARENT_PHONE}", "count": 1}],
        },
        "money": {
            "billed_cents": 123_456,
            "collected_cents": 90_000,
            "outstanding_cents": 33_456,
            "collection_rate": 0.7291,
        },
        "autopay_run": {
            "charge_on": "2026-09-08",
            "charge_on_varies": False,
            "has_run": True,
            "scheduled": {"count": 7, "cents": 70_000},
            "succeeded": {"count": 5, "cents": 50_000},
            "failed": {"count": 2, "cents": 20_000},
            "pending": {"count": 0, "cents": 0},
        },
        "odd": [
            {"code": "autopay_no_card", "label": "No card", "count": 8, "items": items},
            {"code": "paused_family_invoiced", "label": "Paused", "count": 0, "items": []},
        ],
        "tuition_discounts": {"gross_cents": 1, "discount_cents": 2, "net_cents": 3},
        "warnings": ["attempts_unavailable"],
    }


# --------------------------------------------------------------------------- reducer


def test_reducer_keeps_only_the_allowed_facts_and_caps_items_at_five() -> None:
    inp = reduce_month_close_payload(payload())

    assert inp.period == "2026-09"
    assert inp.money.model_dump() == {
        "billed_cents": 123_456,
        "collected_cents": 90_000,
        "outstanding_cents": 33_456,
        "collection_rate": 0.7291,
    }
    assert inp.invoices.model_dump() == {
        "generated": 12,
        "emailed": 4,
        "autopay_notices": 7,
        "not_sent": 1,
        "voided": 1,
    }
    assert inp.autopay_run.model_dump() == {
        "has_run": True,
        "charge_on_varies": False,
        "scheduled": 7,
        "succeeded": 5,
        "failed": 2,
        "pending": 0,
    }
    assert inp.odd[0].count == 8
    assert len(inp.odd[0].items) == 5
    assert inp.odd[0].items[0].model_dump() == {
        "label": "Whitfield family 0",
        "href": "/admin/families/par-0",
    }
    dumped = json.dumps(inp.model_dump())
    for forbidden in (
        PARENT_EMAIL,
        PARENT_PHONE,
        '"id"',
        '"kind"',
        "void_reasons",
        "tuition",
        '"charge_on"',
    ):
        assert forbidden not in dumped


# --------------------------------------------------------------------------- numbers


def _narrative(summary: str, fixes: list[dict[str, str]] | None = None) -> Narrative:
    return Narrative(summary=summary, fix_first=fixes or [])


@pytest.mark.parametrize(
    "summary",
    [
        "September 2026: billed $1,234.56, collected 90000 cents, 33456 outstanding.",
        "Collected $900 of $1234 billed (73%, rate 0.7291); 12 invoices, 2 failed, 8 without a card.",
        "In 2026-09 autopay charged 5 of 7 and 1 invoice was not sent; 0 paused.",
    ],
)
def test_numbers_in_the_input_pass(summary: str) -> None:
    check_narrative(_narrative(summary), reduce_month_close_payload(payload()))


@pytest.mark.parametrize(
    "summary",
    [
        "Outstanding fell by $335.",  # invented
        "Average invoice $102.88.",  # computed
        "Collected 90,001 cents.",  # off by one
        "Collected $900.5 of billed.",  # not the two-decimal form
    ],
)
def test_a_number_not_in_the_input_is_a_provider_error(summary: str) -> None:
    with pytest.raises(AiProviderError):
        check_narrative(_narrative(summary), reduce_month_close_payload(payload()))


def test_digits_quoted_from_an_item_label_pass() -> None:
    body = payload()
    body["odd"][0]["items"][0]["label"] = "INV-2026-0042"
    check_narrative(
        _narrative("Fine.", [{"text": "Resend INV-2026-0042", "href": "/admin/payments"}]),
        reduce_month_close_payload(body),
    )


def test_a_number_in_a_fix_first_text_is_checked_too() -> None:
    with pytest.raises(AiProviderError):
        check_narrative(
            _narrative("Fine.", [{"text": "Chase 6 failed cards", "href": "/admin/payments"}]),
            reduce_month_close_payload(payload()),
        )


def test_hrefs_outside_the_payload_and_allowlist_are_refused() -> None:
    inp = reduce_month_close_payload(payload())
    check_narrative(
        _narrative(
            "Fine.",
            [
                {"text": "Add a card", "href": "/admin/families/par-0"},
                {"text": "Review dues", "href": "/admin/dues"},
            ],
        ),
        inp,
    )
    for href in ("/admin/families/par-7", "/admin/settings", "https://evil.example/x"):
        with pytest.raises(AiProviderError):
            check_narrative(_narrative("Fine.", [{"text": "Go", "href": href}]), inp)


def test_parse_strips_a_json_fence_and_refuses_junk() -> None:
    text = '```json\n{"summary": "ok", "fix_first": []}\n```'
    assert parse_narrative(text).summary == "ok"
    for junk in ("not json", '{"summary": "ok"}', '{"summary": "ok", "fix_first": [], "x": 1}'):
        with pytest.raises(AiProviderError):
            parse_narrative(junk)
    with pytest.raises(AiProviderError):
        parse_narrative(json.dumps({"summary": "w " * 121, "fix_first": []}))


# --------------------------------------------------------------------------- use case


class FakeLlm:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls: list[dict[str, Any]] = []

    async def complete(
        self, *, prompt_version: str, system: str, user: str, max_tokens: int
    ) -> LlmResult:
        self.calls.append(
            {
                "prompt_version": prompt_version,
                "system": system,
                "user": user,
                "max_tokens": max_tokens,
            }
        )
        return LlmResult(text=self.text, input_tokens=10, output_tokens=5, cost_cents=1, model="m")


class FakeEntitlement:
    def __init__(self, value: bool) -> None:
        self.value = value

    async def has_ai(self) -> bool:
        return self.value


class FakeCalls:
    def __init__(self, used: int = 0) -> None:
        self.used = used
        self.records: list[AiCallRecord] = []

    async def record(self, call: AiCallRecord) -> None:
        self.records.append(call)

    async def count_since(self, since: datetime) -> int:
        return self.used


class FakeCap:
    async def monthly_cap(self) -> int:
        return 5


class FakeSource:
    def __init__(self) -> None:
        self.periods: list[str | None] = []

    async def build(self, period: str | None = None) -> dict[str, Any]:
        self.periods.append(period)
        return payload()


GOOD = json.dumps(
    {
        "summary": "Billed $1234 and collected $900; 2 autopay charges failed and 8 families have no card.",
        "fix_first": [
            {"text": "Add a card for Whitfield family 0", "href": "/admin/families/par-0"}
        ],
    }
)


def _use_case(
    *, text: str = GOOD, entitled: bool = True, used: int = 0
) -> tuple[NarrateMonthClose, FakeLlm, FakeCalls, FakeSource]:
    llm, calls, source = FakeLlm(text), FakeCalls(used), FakeSource()
    uc = NarrateMonthClose(
        llm=llm,
        entitlement=FakeEntitlement(entitled),
        record_ai_call=RecordAiCall(calls=calls, cap_source=FakeCap()),
        source=source,
        clock=lambda: datetime(2026, 9, 30, tzinfo=UTC),
    )
    return uc, llm, calls, source


async def test_happy_path_records_the_call_with_the_owner_as_approver() -> None:
    uc, llm, calls, source = _use_case()

    out = await uc.execute(period="2026-09", approver="u-owner")

    assert out.prompt_version == "month-close-narrator-v1"
    assert out.fix_first[0].href == "/admin/families/par-0"
    assert out.generated_at == datetime(2026, 9, 30, tzinfo=UTC)
    assert source.periods == ["2026-09"]
    assert llm.calls[0]["max_tokens"] == MAX_TOKENS
    assert llm.calls[0]["system"] == PROMPTS[FEATURE].system_text
    assert [(r.feature, r.prompt_version, r.approver) for r in calls.records] == [
        (FEATURE, "month-close-narrator-v1", "u-owner")
    ]


async def test_not_entitled_is_403_before_any_read_or_call() -> None:
    uc, llm, calls, source = _use_case(entitled=False)
    with pytest.raises(AiNotEntitled):
        await uc.execute(period="2026-09", approver="u")
    assert llm.calls == [] and calls.records == [] and source.periods == []


async def test_at_cap_is_429_before_the_model_is_called() -> None:
    uc, llm, calls, source = _use_case(used=5)
    with pytest.raises(AiMonthlyCapReached):
        await uc.execute(period="2026-09", approver="u")
    assert llm.calls == [] and calls.records == [] and source.periods == []


@pytest.mark.parametrize(
    "text",
    [
        "I cannot help with that.",
        json.dumps({"summary": "Outstanding fell by $335.", "fix_first": []}),
        json.dumps({"summary": "ok", "fix_first": [{"text": "x", "href": "/admin/settings"}]}),
    ],
)
async def test_an_unreadable_or_invented_answer_is_recorded_then_502(text: str) -> None:
    uc, llm, calls, _ = _use_case(text=text)
    with pytest.raises(AiProviderError):
        await uc.execute(period="2026-09", approver="u")
    assert len(llm.calls) == 1
    assert len(calls.records) == 1


async def test_the_user_message_is_exactly_the_reduced_input() -> None:
    """Prompt-content: the model sees the allowed facts and nothing else."""
    uc, llm, _, _ = _use_case()
    await uc.execute(period="2026-09", approver="u")

    user = llm.calls[0]["user"]
    assert json.loads(user) == reduce_month_close_payload(payload()).model_dump()
    for fact in (
        "2026-09",
        "America/Chicago",
        "123456",
        "0.7291",
        "Whitfield family 4",
        "/admin/families/par-4",
        "attempts_unavailable",
    ):
        assert fact in user
    for forbidden in (
        PARENT_EMAIL,
        PARENT_PHONE,
        "Whitfield family 5",
        "par-5",
        "duplicate",
        "gross_cents",
        "2026-09-08",
        "voided_cents",
    ):
        assert forbidden not in user


def test_the_prompt_is_the_last_entry_and_says_the_rules() -> None:
    assert list(PROMPTS)[-1] == FEATURE
    text = PROMPTS[FEATURE].system_text
    assert PROMPTS[FEATURE].version == "month-close-narrator-v1"
    for phrase in ("JSON only", "Invent nothing", "untrusted", "/admin/billing-health"):
        assert phrase in text


# --------------------------------------------------------------------------- entitlement adapter


class FakeHasFeature:
    def __init__(self, value: bool) -> None:
        self.value = value
        self.calls: list[tuple[str, str]] = []

    async def execute(self, academy_id: str, feature: str) -> bool:
        self.calls.append((academy_id, feature))
        return self.value


async def test_platform_entitlement_is_false_when_nothing_is_wired() -> None:
    assert await PlatformAiEntitlement(None).has_ai() is False


async def test_platform_entitlement_reads_has_feature_for_the_academy_in_scope() -> None:
    has_feature = FakeHasFeature(True)
    with tenant_scope("acad-growth"):
        assert await PlatformAiEntitlement(has_feature).has_ai() is True
    assert has_feature.calls == [("acad-growth", "ai")]
