"""AI usage meter (plan 2026-11-04 Phase 2, slice A3): the plan decides the
cap, the free cap is a soft prompt at the boundary, only this UTC month
counts, and one academy's rows never count for another."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.v2.composition.ai_usage import ScopedHasFeature, compose_ai_usage
from backend.v2.contexts.ai.application.use_cases.get_ai_usage import (
    FREE_TIER_MONTHLY_DRAFTS,
    GetAiUsage,
    GetAiUsageForAcademy,
)
from backend.v2.contexts.ai.domain.errors import AiAcademyNotFound
from backend.v2.contexts.ai.domain.models import DEFAULT_MODEL, AiCallRecord
from backend.v2.contexts.ai.infrastructure.mongo_ai_call_repo import MongoAiCallRepository
from backend.v2.shared.tenancy import tenant_scope

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
LAST_MONTH = datetime(2026, 10, 31, 23, 59, tzinfo=UTC)


class _Calls:
    def __init__(self, stamps: list[datetime]) -> None:
        self.stamps = stamps

    async def record(self, call: AiCallRecord) -> None:
        self.stamps.append(call.created_at)

    async def count_since(self, since: datetime) -> int:
        return sum(1 for s in self.stamps if s >= since)


class _Cap:
    async def monthly_cap(self) -> int:
        return 200


class _Entitled:
    def __init__(self, ai: bool) -> None:
        self.ai = ai

    async def has_feature(self, feature: str) -> bool:
        assert feature == "ai"
        return self.ai


def _usage(stamps: list[datetime], *, ai: bool) -> GetAiUsage:
    return GetAiUsage(
        calls=_Calls(stamps), cap_source=_Cap(), entitlements=_Entitled(ai), clock=lambda: NOW
    )


@pytest.mark.asyncio
async def test_free_tier_caps_at_twenty_and_prompts_only_at_the_boundary() -> None:
    assert FREE_TIER_MONTHLY_DRAFTS == 20
    below = await _usage([NOW] * 19, ai=False).execute()
    assert (below.used, below.cap, below.tier, below.upgrade_suggested) == (19, 20, "free", False)
    at = await _usage([NOW] * 20, ai=False).execute()
    assert (at.used, at.upgrade_suggested) == (20, True)
    over = await _usage([NOW] * 21, ai=False).execute()
    assert (over.used, over.upgrade_suggested) == (21, True)
    assert over.month == "2026-11"


@pytest.mark.asyncio
async def test_growth_tier_uses_the_academy_cap_and_never_prompts() -> None:
    usage = await _usage([NOW] * 25, ai=True).execute()
    assert (usage.used, usage.cap, usage.tier, usage.upgrade_suggested) == (
        25,
        200,
        "growth",
        False,
    )


@pytest.mark.asyncio
async def test_only_this_utc_month_counts() -> None:
    usage = await _usage([LAST_MONTH] * 30 + [NOW] * 2, ai=False).execute()
    assert (usage.used, usage.upgrade_suggested) == (2, False)


def _row(when: datetime) -> AiCallRecord:
    return AiCallRecord(
        feature="placeholder",
        prompt_version="placeholder-v0",
        model=DEFAULT_MODEL,
        input_tokens=1,
        output_tokens=1,
        cost_cents=1,
        created_at=when,
    )


class _HasFeature:
    def __init__(self, entitled: set[str]) -> None:
        self.entitled = entitled

    async def execute(self, academy_id: str, feature: str) -> bool:
        return feature == "ai" and academy_id in self.entitled


@pytest.mark.asyncio
async def test_calls_for_one_academy_are_not_counted_for_another() -> None:
    db = AsyncMongoMockClient()["test_db"]
    await db["academies"].insert_many([{"academy_id": "acad-a"}, {"academy_id": "acad-b"}])
    repo = MongoAiCallRepository(db)
    with tenant_scope("acad-a"):
        for _ in range(20):
            await repo.record(_row(NOW))
    with tenant_scope("acad-b"):
        await repo.record(_row(NOW))

    wiring = compose_ai_usage(db, _HasFeature({"acad-b"}))
    a = await wiring.get_ai_usage_for_academy.execute("acad-a")
    b = await wiring.get_ai_usage_for_academy.execute("acad-b")
    assert (a.used, a.tier, a.upgrade_suggested) == (20, "free", True)
    assert (b.used, b.cap, b.tier, b.upgrade_suggested) == (1, 200, "growth", False)
    with tenant_scope("acad-a"):
        assert (await wiring.get_ai_usage.execute()).used == 20
    with pytest.raises(AiAcademyNotFound):
        await wiring.get_ai_usage_for_academy.execute("acad-missing")


@pytest.mark.asyncio
async def test_scoped_has_feature_asks_for_the_academy_in_scope() -> None:
    source = ScopedHasFeature(_HasFeature({"acad-b"}))
    with tenant_scope("acad-a"):
        assert await source.has_feature("ai") is False
    with tenant_scope("acad-b"):
        assert await source.has_feature("ai") is True


@pytest.mark.asyncio
async def test_platform_view_enters_the_academy_scope() -> None:
    seen: list[str] = []

    class _Scoped:
        async def execute(self):  # type: ignore[no-untyped-def]
            from backend.v2.shared.tenancy import current_academy_id

            seen.append(current_academy_id())
            return "usage"

    async def exists(academy_id: str) -> bool:
        return True

    use_case = GetAiUsageForAcademy(usage=_Scoped(), academy_exists=exists)  # type: ignore[arg-type]
    assert await use_case.execute("acad-x") == "usage"
    assert seen == ["acad-x"]
