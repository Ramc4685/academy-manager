"""AI foundation plumbing (plan 2026-11-04 Phase 1): the gate, the adapter
request shape and cost, and the monthly cap arithmetic."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.v2.composition.ai import AcademyAiCapLookup, compose_ai
from backend.v2.contexts.ai.application.use_cases.record_ai_call import (
    DEFAULT_MONTHLY_CALL_CAP,
    RecordAiCall,
)
from backend.v2.contexts.ai.domain.errors import AiDisabled, AiMonthlyCapReached, AiProviderError
from backend.v2.contexts.ai.domain.models import DEFAULT_MODEL, AiCallRecord, LlmResult
from backend.v2.contexts.ai.domain.prompts import PROMPTS
from backend.v2.contexts.ai.infrastructure.anthropic_llm_port import (
    AnthropicLlmPort,
    cost_cents,
)
from backend.v2.contexts.ai.infrastructure.disabled_llm_port import DisabledLlmPort
from backend.v2.shared.tenancy import tenant_scope

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
RESULT = LlmResult(text="hi", input_tokens=10, output_tokens=5, cost_cents=1, model=DEFAULT_MODEL)


async def test_disabled_port_raises() -> None:
    with pytest.raises(AiDisabled):
        await DisabledLlmPort().complete(
            prompt_version="placeholder-v0", system="s", user="u", max_tokens=10
        )


@pytest.mark.parametrize(
    ("enabled", "key", "expected"),
    [
        (False, None, DisabledLlmPort),
        (False, "sk-ant-x", DisabledLlmPort),
        (True, None, DisabledLlmPort),
        (True, "sk-ant-x", AnthropicLlmPort),
    ],
)
def test_compose_ai_wires_the_real_port_only_when_enabled_with_a_key(
    enabled: bool, key: str | None, expected: type
) -> None:
    settings = SimpleNamespace(ai_enabled=enabled, anthropic_api_key=key)
    db = AsyncMongoMockClient()["test_db"]
    assert type(compose_ai(db, settings=settings).llm) is expected


def test_prompt_registry_has_the_unused_placeholder() -> None:
    assert PROMPTS["placeholder"].version == "placeholder-v0"


def test_cost_rounds_up_to_a_whole_cent() -> None:
    assert cost_cents(DEFAULT_MODEL, 0, 0) == 0
    # 1 input token at $3/MTok is a fraction of a cent: still 1 cent.
    assert cost_cents(DEFAULT_MODEL, 1, 0) == 1
    # 1M in + 1M out = $3 + $15.
    assert cost_cents(DEFAULT_MODEL, 1_000_000, 1_000_000) == 1800


async def test_anthropic_port_sends_messages_request_and_parses_usage() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "model": DEFAULT_MODEL,
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": "Hello"}, {"type": "text", "text": "!"}],
                "usage": {"input_tokens": 12, "output_tokens": 3},
            },
        )

    port = AnthropicLlmPort(api_key="sk-ant-test", transport=httpx.MockTransport(handler))
    result = await port.complete(
        prompt_version="placeholder-v0", system="sys", user="usr", max_tokens=64
    )

    assert seen["url"] == "https://api.anthropic.com/v1/messages"
    assert seen["headers"]["x-api-key"] == "sk-ant-test"
    assert seen["headers"]["anthropic-version"] == "2023-06-01"
    assert seen["body"] == {
        "model": DEFAULT_MODEL,
        "max_tokens": 64,
        "system": "sys",
        "messages": [{"role": "user", "content": "usr"}],
    }
    assert result == LlmResult(
        text="Hello!", input_tokens=12, output_tokens=3, cost_cents=1, model=DEFAULT_MODEL
    )


async def test_anthropic_port_raises_provider_error_on_4xx() -> None:
    port = AnthropicLlmPort(
        api_key="bad",
        transport=httpx.MockTransport(lambda _r: httpx.Response(401, json={"error": {}})),
    )
    with pytest.raises(AiProviderError):
        await port.complete(prompt_version="v", system="s", user="u", max_tokens=1)


class FakeCalls:
    def __init__(self, used: int) -> None:
        self.used = used
        self.recorded: list[AiCallRecord] = []

    async def count_since(self, since: datetime) -> int:
        assert since == datetime(2026, 11, 1, tzinfo=UTC)
        return self.used

    async def record(self, call: AiCallRecord) -> None:
        self.recorded.append(call)


class FakeCap:
    def __init__(self, cap: int) -> None:
        self.cap = cap

    async def monthly_cap(self) -> int:
        return self.cap


async def test_record_ai_call_writes_under_the_cap() -> None:
    calls = FakeCalls(used=1)
    use_case = RecordAiCall(calls=calls, cap_source=FakeCap(2), clock=lambda: NOW)

    record = await use_case.execute(
        feature="placeholder", prompt_version="placeholder-v0", result=RESULT, approver="u1"
    )

    assert calls.recorded == [record]
    assert record.model == DEFAULT_MODEL and record.approver == "u1" and record.created_at == NOW


async def test_record_ai_call_refuses_at_the_cap() -> None:
    calls = FakeCalls(used=2)
    use_case = RecordAiCall(calls=calls, cap_source=FakeCap(2), clock=lambda: NOW)

    with pytest.raises(AiMonthlyCapReached):
        await use_case.execute(
            feature="placeholder", prompt_version="placeholder-v0", result=RESULT, approver=None
        )
    assert calls.recorded == []


class FakeAcademies:
    def __init__(self, doc: dict | None) -> None:
        self.doc = doc

    async def find_by_id(self, academy_id: str) -> dict | None:
        return self.doc


@pytest.mark.parametrize(
    ("doc", "expected"),
    [
        (None, DEFAULT_MONTHLY_CALL_CAP),
        ({"ai": {"monthly_call_cap": 7}}, 7),
        ({"ai": {"monthly_call_cap": 0}}, 0),
        ({"ai": {"monthly_call_cap": "many"}}, DEFAULT_MONTHLY_CALL_CAP),
        ({"ai": {"monthly_call_cap": True}}, DEFAULT_MONTHLY_CALL_CAP),
    ],
)
async def test_academy_cap_lookup_reads_ai_monthly_call_cap(
    doc: dict | None, expected: int
) -> None:
    with tenant_scope("acad-ai"):
        assert await AcademyAiCapLookup(FakeAcademies(doc)).monthly_cap() == expected
