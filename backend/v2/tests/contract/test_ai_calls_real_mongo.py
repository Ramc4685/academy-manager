"""``ai_calls`` on a real ``mongod``: tenant-scoped rows and the monthly cap."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.composition.ai import AcademyAiCapLookup
from backend.v2.contexts.ai.application.use_cases.record_ai_call import RecordAiCall
from backend.v2.contexts.ai.domain.errors import AiMonthlyCapReached
from backend.v2.contexts.ai.domain.models import DEFAULT_MODEL, AiCallRecord, LlmResult
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


@pytest.mark.asyncio
async def test_monthly_cap_counts_only_this_month(real_db) -> None:
    repo = MongoAiCallRepository(real_db)
    use_case = RecordAiCall(calls=repo, cap_source=FixedCap(2), clock=lambda: NOW)
    with tenant_scope("acad-ai-cap"):
        await repo.record(_row(LAST_MONTH))
        await repo.record(_row(MONTH_START))
        # 1 this month + this one = 2 <= cap.
        await use_case.execute(
            feature="placeholder", prompt_version="placeholder-v0", result=RESULT, approver=None
        )
        with pytest.raises(AiMonthlyCapReached):
            await use_case.execute(
                feature="placeholder", prompt_version="placeholder-v0", result=RESULT, approver=None
            )
        assert await repo.count_since(MONTH_START) == 2
    # Another academy's month is untouched by the cap hit.
    with tenant_scope("acad-ai-other"):
        record = await use_case.execute(
            feature="placeholder", prompt_version="placeholder-v0", result=RESULT, approver=None
        )
        assert record.created_at == NOW


@pytest.mark.asyncio
async def test_cap_is_read_from_the_academy_document(real_db) -> None:
    await real_db["academies"].insert_one(
        {"academy_id": "acad-ai-doc", "display_name": "AI", "ai": {"monthly_call_cap": 1}}
    )
    use_case = RecordAiCall(
        calls=MongoAiCallRepository(real_db),
        cap_source=AcademyAiCapLookup(MongoAcademyRepository(real_db)),
        clock=lambda: NOW,
    )
    with tenant_scope("acad-ai-doc"):
        await use_case.execute(
            feature="placeholder", prompt_version="placeholder-v0", result=RESULT, approver=None
        )
        with pytest.raises(AiMonthlyCapReached):
            await use_case.execute(
                feature="placeholder", prompt_version="placeholder-v0", result=RESULT, approver=None
            )
