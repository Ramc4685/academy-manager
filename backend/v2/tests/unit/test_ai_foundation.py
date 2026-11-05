"""AI foundation plumbing (plan 2026-11-04 Phase 1): the gate, the adapter
request shape and cost, and the hard cap reservation (Phase 3 D1)."""

from __future__ import annotations

import importlib
import json
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest
from mongomock_motor import AsyncMongoMockClient
from pydantic import SecretStr

from backend.v2.composition.ai import AcademyAiCapLookup, compose_ai
from backend.v2.contexts.ai.application.use_cases.record_ai_call import (
    DEFAULT_MONTHLY_CALL_CAP,
    RecordAiCall,
)
from backend.v2.contexts.ai.domain.errors import (
    AiDailyCapReached,
    AiDisabled,
    AiMonthlyCapReached,
    AiProviderError,
)
from backend.v2.contexts.ai.domain.models import DEFAULT_MODEL, AiCallRecord, LlmResult
from backend.v2.contexts.ai.domain.prompts import PROMPTS
from backend.v2.contexts.ai.infrastructure.anthropic_llm_port import (
    AnthropicLlmPort,
    cost_cents,
)
from backend.v2.contexts.ai.infrastructure.disabled_llm_port import DisabledLlmPort
from backend.v2.shared.tenancy import TenantContextUnset, tenant_scope
from backend.v2.tests.fixtures.ai_counters import InMemoryAiCallCounters

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
    settings = SimpleNamespace(
        ai_enabled=enabled, anthropic_api_key=SecretStr(key) if key else None
    )
    db = AsyncMongoMockClient()["test_db"]
    assert type(compose_ai(db, settings=settings).llm) is expected


def test_prompt_registry_has_the_unused_placeholder() -> None:
    assert PROMPTS["placeholder"].version == "placeholder-v0"


def test_cost_rounds_up_to_a_whole_cent() -> None:
    assert cost_cents(DEFAULT_MODEL, 0, 0) == 0
    # 1 input token at $2/MTok is a fraction of a cent: still 1 cent.
    assert cost_cents(DEFAULT_MODEL, 1, 0) == 1
    # 1M in + 1M out = $2 + $10.
    assert cost_cents(DEFAULT_MODEL, 1_000_000, 1_000_000) == 1200


def test_anthropic_port_refuses_a_model_without_a_price_row() -> None:
    with pytest.raises(ValueError):
        AnthropicLlmPort(api_key="sk-ant-test", model="claude-unpriced")


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
    def __init__(self) -> None:
        self.recorded: list[AiCallRecord] = []

    async def count_since(self, since: datetime) -> int:
        return len(self.recorded)

    async def record(self, call: AiCallRecord) -> None:
        self.recorded.append(call)


class FakeCap:
    def __init__(self, cap: int, daily: dict[str, int] | None = None) -> None:
        self.cap = cap
        self.daily = daily or {}

    async def monthly_cap(self) -> int:
        return self.cap

    async def daily_cap(self, feature: str) -> int | None:
        return self.daily.get(feature)


def _record_ai_call(
    cap: FakeCap, counters: InMemoryAiCallCounters | None = None, now: datetime = NOW
) -> tuple[RecordAiCall, InMemoryAiCallCounters, FakeCalls]:
    counters = counters if counters is not None else InMemoryAiCallCounters()
    calls = FakeCalls()
    use_case = RecordAiCall(
        calls=calls, counters=counters, cap_source=cap, daily_caps=cap, clock=lambda: now
    )
    return use_case, counters, calls


async def test_record_ai_call_writes_the_audit_row() -> None:
    use_case, _, calls = _record_ai_call(FakeCap(2))

    async with use_case.reserve("placeholder"):
        pass
    record = await use_case.execute(
        feature="placeholder", prompt_version="placeholder-v0", result=RESULT, approver="u1"
    )

    assert calls.recorded == [record]
    assert record.model == DEFAULT_MODEL and record.approver == "u1" and record.created_at == NOW


async def test_reservation_at_the_cap_is_refused_before_any_call() -> None:
    use_case, counters, calls = _record_ai_call(FakeCap(2))
    for _ in range(2):
        async with use_case.reserve("placeholder"):
            pass

    with pytest.raises(AiMonthlyCapReached):
        async with use_case.reserve("placeholder"):
            pytest.fail("the block must not run at the cap")
    assert counters.counts == {"month:2026-11": 2}
    assert calls.recorded == []


async def test_a_zero_cap_refuses_the_first_call() -> None:
    use_case, counters, _ = _record_ai_call(FakeCap(0))
    with pytest.raises(AiMonthlyCapReached):
        async with use_case.reserve("placeholder"):
            pass
    assert counters.counts == {}


async def test_a_provider_error_releases_the_slot() -> None:
    use_case, counters, _ = _record_ai_call(FakeCap(1, daily={"placeholder": 1}))

    with pytest.raises(AiProviderError):
        async with use_case.reserve("placeholder"):
            raise AiProviderError("boom")
    assert counters.counts == {"month:2026-11": 0, "day:2026-11-04:placeholder": 0}

    # The freed slot is usable: one call goes through, the next is refused.
    async with use_case.reserve("placeholder"):
        pass
    with pytest.raises(AiMonthlyCapReached):
        async with use_case.reserve("placeholder"):
            pass


async def test_month_rollover_starts_a_new_counter() -> None:
    counters = InMemoryAiCallCounters()
    october, _, _ = _record_ai_call(
        FakeCap(1), counters, now=datetime(2026, 10, 31, 23, 59, tzinfo=UTC)
    )
    november, _, _ = _record_ai_call(FakeCap(1), counters, now=NOW)

    async with october.reserve("placeholder"):
        pass
    with pytest.raises(AiMonthlyCapReached):
        async with october.reserve("placeholder"):
            pass
    async with november.reserve("placeholder"):
        pass
    assert counters.counts == {"month:2026-10": 1, "month:2026-11": 1}


async def test_daily_ceiling_applies_per_feature() -> None:
    use_case, counters, _ = _record_ai_call(FakeCap(10, daily={"ask": 1}))

    async with use_case.reserve("ask"):
        pass
    with pytest.raises(AiDailyCapReached):
        async with use_case.reserve("ask"):
            pass
    # Another feature has no daily ceiling and still has month left.
    for _ in range(3):
        async with use_case.reserve("skill_ladder"):
            pass
    # The refused daily call gave its month slot back: 1 ask + 3 ladder.
    assert counters.counts == {"month:2026-11": 4, "day:2026-11-04:ask": 1}

    # The next UTC day the feature's ceiling starts over.
    tomorrow, _, _ = _record_ai_call(
        FakeCap(10, daily={"ask": 1}), counters, now=datetime(2026, 11, 5, 0, 1, tzinfo=UTC)
    )
    async with tomorrow.reserve("ask"):
        pass


async def test_no_daily_cap_source_means_no_daily_ceiling() -> None:
    counters = InMemoryAiCallCounters()
    use_case = RecordAiCall(
        calls=FakeCalls(), counters=counters, cap_source=FakeCap(5), clock=lambda: NOW
    )
    for _ in range(5):
        async with use_case.reserve("ask"):
            pass
    assert counters.counts == {"month:2026-11": 5}


async def test_execute_always_records_a_spent_call_even_past_the_cap() -> None:
    # The tokens are already spent when execute runs: refusing here would
    # drop the audit row, so only reserve refuses.
    use_case, _, calls = _record_ai_call(FakeCap(0))

    record = await use_case.execute(
        feature="placeholder", prompt_version="placeholder-v0", result=RESULT, approver=None
    )
    assert calls.recorded == [record]


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


async def test_academy_cap_lookup_needs_a_tenant_scope() -> None:
    with pytest.raises(TenantContextUnset):
        await AcademyAiCapLookup(FakeAcademies({"ai": {"monthly_call_cap": 7}})).monthly_cap()


@pytest.mark.parametrize(
    ("doc", "expected"),
    [
        (None, None),
        ({"ai": {}}, None),
        ({"ai": {"daily_call_cap": {"skill_ladder": 3}}}, None),
        ({"ai": {"daily_call_cap": {"ask": 50}}}, 50),
        ({"ai": {"daily_call_cap": {"ask": 0}}}, 0),
        ({"ai": {"daily_call_cap": {"ask": "many"}}}, None),
        ({"ai": {"daily_call_cap": {"ask": True}}}, None),
        ({"ai": {"daily_call_cap": 50}}, None),
    ],
)
async def test_academy_cap_lookup_reads_ai_daily_call_cap_per_feature(
    doc: dict | None, expected: int | None
) -> None:
    with tenant_scope("acad-ai"):
        assert await AcademyAiCapLookup(FakeAcademies(doc)).daily_cap("ask") == expected


_M0226 = importlib.import_module("backend.v2.migrations.0226_ai_call_counters")


async def test_migration_0226_builds_the_unique_counter_index_and_rerun_is_a_no_op() -> None:
    assert _M0226.version == "0226_ai_call_counters"
    db = AsyncMongoMockClient()["m0226"]
    await _M0226.up(db)
    await _M0226.up(db)
    info = await db["ai_call_counters"].index_information()
    index = info["ai_call_counters_academy_key_unique"]
    assert index["key"] == [("academy_id", 1), ("key", 1)]
    assert index["unique"] is True
