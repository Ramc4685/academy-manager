"""``ai_calls`` and ``ai_call_counters`` on a real ``mongod``: tenant-scoped\nrows and the hard cap reservation (atomicity mongomock cannot prove)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from backend.v2.composition.ai import AcademyAiCapLookup
from backend.v2.contexts.ai.application.use_cases.record_ai_call import RecordAiCall
from backend.v2.contexts.ai.domain.errors import (
    AiDailyCapReached,
    AiMonthlyCapReached,
    AiProviderError,
)
from backend.v2.contexts.ai.domain.models import DEFAULT_MODEL, AiCallRecord, LlmResult
from backend.v2.contexts.ai.infrastructure.mongo_ai_call_counter_repo import (
    MongoAiCallCounterRepository,
)
from backend.v2.contexts.ai.infrastructure.mongo_ai_call_repo import MongoAiCallRepository
from backend.v2.contexts.identity.infrastructure.mongo_academy_repo import (
    MongoAcademyRepository,
)
from backend.v2.shared.tenancy import tenant_scope

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
MONTH_START = datetime(2026, 11, 1, tzinfo=UTC)
LAST_MONTH = datetime(2026, 10, 31, 23, 59, tzinfo=UTC)
RESULT = LlmResult(text="t", input_tokens=10, output_tokens=5, cost_cents=1, model=DEFAULT_MODEL)


def _row(when: datetime, feature: str = "placeholder") -> AiCallRecord:
    return AiCallRecord(
        feature=feature,
        prompt_version="placeholder-v0",
        model=DEFAULT_MODEL,
        input_tokens=10,
        output_tokens=5,
        cost_cents=1,
        approver="u1",
        created_at=when,
    )


class FixedCap:
    def __init__(self, cap: int) -> None:
        self.cap = cap

    async def monthly_cap(self) -> int:
        return self.cap


@pytest.mark.asyncio
async def test_rows_are_stamped_and_scoped_per_academy(real_db) -> None:
    repo = MongoAiCallRepository(real_db)
    with tenant_scope("acad-ai-a"):
        await repo.record(_row(NOW))
        await repo.record(_row(NOW))
    with tenant_scope("acad-ai-b"):
        await repo.record(_row(NOW))

    with tenant_scope("acad-ai-a"):
        assert await repo.count_since(MONTH_START) == 2
    with tenant_scope("acad-ai-b"):
        assert await repo.count_since(MONTH_START) == 1
    with tenant_scope("acad-ai-c"):
        assert await repo.count_since(MONTH_START) == 0

    stored = await real_db["ai_calls"].find_one({"academy_id": "acad-ai-b"})
    assert stored["feature"] == "placeholder"
    assert stored["prompt_version"] == "placeholder-v0"
    assert stored["model"] == DEFAULT_MODEL
    assert (stored["input_tokens"], stored["output_tokens"], stored["cost_cents"]) == (10, 5, 1)
    assert stored["approver"] == "u1"
    assert await real_db["ai_calls"].count_documents({"academy_id": "acad-ai-b"}) == 1


def _use_case(db, cap_source, *, now: datetime = NOW) -> RecordAiCall:
    return RecordAiCall(
        calls=MongoAiCallRepository(db),
        counters=MongoAiCallCounterRepository(db),
        cap_source=cap_source,
        daily_caps=cap_source if hasattr(cap_source, "daily_cap") else None,
        clock=lambda: now,
    )


@pytest.mark.asyncio
async def test_monthly_cap_is_per_academy_and_per_month(real_db) -> None:
    october = _use_case(real_db, FixedCap(2), now=LAST_MONTH)
    november = _use_case(real_db, FixedCap(2))
    with tenant_scope("acad-ai-cap"):
        async with october.reserve("placeholder"):
            pass
        for _ in range(2):
            async with november.reserve("placeholder"):
                pass
        with pytest.raises(AiMonthlyCapReached):
            async with november.reserve("placeholder"):
                pass
    # Another academy's month is untouched by the cap hit.
    with tenant_scope("acad-ai-other"):
        async with november.reserve("placeholder"):
            pass
    counts = {
        (d["academy_id"], d["key"]): d["count"]
        async for d in real_db["ai_call_counters"].find({}, {"_id": 0})
    }
    assert counts == {
        ("acad-ai-cap", "month:2026-10"): 1,
        ("acad-ai-cap", "month:2026-11"): 2,
        ("acad-ai-other", "month:2026-11"): 1,
    }


@pytest.mark.asyncio
async def test_reserve_at_the_cap_does_not_create_a_duplicate_counter(real_db) -> None:
    counters = MongoAiCallCounterRepository(real_db)
    with tenant_scope("acad-ai-dup"):
        assert await counters.reserve("month:2026-11", 1) is True
        # At the cap the $lt filter misses and the upsert hits the unique index.
        assert await counters.reserve("month:2026-11", 1) is False
        await counters.release("month:2026-11")
        await counters.release("month:2026-11")  # never below zero
        assert await counters.reserve("month:2026-11", 1) is True
    docs = await real_db["ai_call_counters"].find({"academy_id": "acad-ai-dup"}).to_list(None)
    assert [d["count"] for d in docs] == [1]


@pytest.mark.asyncio
@pytest.mark.parametrize("already_used", [0, 4])
async def test_concurrent_reservations_at_cap_minus_one_let_exactly_one_through(
    real_db, already_used: int
) -> None:
    # already_used=0 with cap 1 races the first-of-the-month upsert itself.
    cap = already_used + 1
    counters = MongoAiCallCounterRepository(real_db)
    with tenant_scope("acad-ai-race"):
        for _ in range(already_used):
            assert await counters.reserve("month:2026-11", cap)
        results = await asyncio.gather(*(counters.reserve("month:2026-11", cap) for _ in range(20)))
    assert results.count(True) == 1
    docs = await real_db["ai_call_counters"].find({"academy_id": "acad-ai-race"}).to_list(None)
    assert [d["count"] for d in docs] == [cap]


@pytest.mark.asyncio
async def test_concurrent_feature_calls_at_cap_minus_one_spend_one_model_call(real_db) -> None:
    use_case = _use_case(real_db, FixedCap(3))
    model_calls = 0

    async def one_call() -> bool:
        nonlocal model_calls
        try:
            async with use_case.reserve("placeholder"):
                model_calls += 1
                await asyncio.sleep(0)
        except AiMonthlyCapReached:
            return False
        await use_case.execute(
            feature="placeholder", prompt_version="placeholder-v0", result=RESULT, approver=None
        )
        return True

    with tenant_scope("acad-ai-feature-race"):
        for _ in range(2):
            async with use_case.reserve("placeholder"):
                pass
        results = await asyncio.gather(*(one_call() for _ in range(10)))
        assert await MongoAiCallRepository(real_db).count_since(MONTH_START) == 1
    assert results.count(True) == 1 and model_calls == 1


@pytest.mark.asyncio
async def test_cap_and_daily_ceiling_are_read_from_the_academy_document(real_db) -> None:
    await real_db["academies"].insert_one(
        {
            "academy_id": "acad-ai-doc",
            "display_name": "AI",
            "ai": {"monthly_call_cap": 3, "daily_call_cap": {"ask": 1}},
        }
    )
    use_case = _use_case(real_db, AcademyAiCapLookup(MongoAcademyRepository(real_db)))
    with tenant_scope("acad-ai-doc"):
        async with use_case.reserve("ask"):
            pass
        with pytest.raises(AiDailyCapReached):
            async with use_case.reserve("ask"):
                pass
        # A provider error inside the block gives both slots back.
        with pytest.raises(AiProviderError):
            async with use_case.reserve("skill_ladder"):
                raise AiProviderError("boom")
        for _ in range(2):
            async with use_case.reserve("skill_ladder"):
                pass
        with pytest.raises(AiMonthlyCapReached):
            async with use_case.reserve("skill_ladder"):
                pass
