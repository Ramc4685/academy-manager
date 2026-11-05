"""B1 skill-ladder generator: what the model sees, how its answer is read,
and that every call is counted (plan 2026-11-04 Phase 2, Track B)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import get_args

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.v2.composition.ai import AiComposition, PlatformAiEntitlement
from backend.v2.composition.ai_curriculum import (
    CurriculumProgramSportLookup,
    compose_ai_curriculum,
)
from backend.v2.contexts.ai.application.use_cases.draft_skill_ladder import (
    FEATURE,
    MAX_TOKENS,
    DraftSkillLadder,
    SkillLadderInput,
    SkillScoringType,
)
from backend.v2.contexts.ai.application.use_cases.record_ai_call import RecordAiCall
from backend.v2.contexts.ai.domain.errors import AiDisabled, AiMonthlyCapReached, AiProviderError
from backend.v2.contexts.ai.domain.models import DEFAULT_MODEL, AiCallRecord, LlmResult
from backend.v2.contexts.ai.domain.prompts import PROMPTS
from backend.v2.contexts.ai.infrastructure.disabled_llm_port import DisabledLlmPort
from backend.v2.contexts.curriculum.domain.models import Program, ScoringType
from backend.v2.contexts.curriculum.infrastructure.mongo_program_repo import MongoProgramRepository
from backend.v2.shared.tenancy import tenant_scope

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
INPUT = SkillLadderInput(sport="badminton", age_band="8-10", level_count=2, notes="Fun first")


def _skill(name: str, scoring_type: str = "ATTEMPT_BASED") -> dict:
    return {
        "name": name,
        "description": "d",
        "scoring_type": scoring_type,
        "is_required": True,
        "criteria": ["Holds the racket with a relaxed grip"],
    }


def _answer(level_count: int = 2, scoring_type: str = "ATTEMPT_BASED") -> dict:
    return {
        "levels": [
            {
                "sequence": i,
                "name": f"Level {i}",
                "description": "",
                "skills": [_skill("Grip", scoring_type), _skill("Footwork")],
            }
            for i in range(1, level_count + 1)
        ]
    }


class FakeLlm:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls: list[dict] = []

    async def complete(
        self, *, prompt_version: str, system: str, user: str, max_tokens: int
    ) -> LlmResult:
        self.calls.append(
            {"prompt_version": prompt_version, "system": system, "user": user, "max": max_tokens}
        )
        return LlmResult(
            text=self.text, input_tokens=10, output_tokens=5, cost_cents=1, model=DEFAULT_MODEL
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
    def __init__(self, cap: int = 200) -> None:
        self.cap = cap

    async def monthly_cap(self) -> int:
        return self.cap


def _use_case(llm, *, used: int = 0, cap: int = 200) -> tuple[DraftSkillLadder, FakeCalls]:
    calls = FakeCalls(used)
    record = RecordAiCall(calls=calls, cap_source=FakeCap(cap), clock=lambda: NOW)
    return DraftSkillLadder(llm=llm, record_ai_call=record), calls


async def test_valid_json_becomes_a_draft_and_is_recorded() -> None:
    llm = FakeLlm(json.dumps(_answer()))
    use_case, calls = _use_case(llm)

    draft = await use_case.execute(INPUT, approver="u-admin")

    assert [level.name for level in draft.levels] == ["Level 1", "Level 2"]
    assert draft.levels[0].skills[0].criteria == ["Holds the racket with a relaxed grip"]
    assert len(calls.recorded) == 1
    row = calls.recorded[0]
    assert (row.feature, row.prompt_version, row.approver) == (
        FEATURE,
        "skill-ladder-v1",
        "u-admin",
    )
    assert llm.calls[0]["max"] == MAX_TOKENS


async def test_fenced_json_is_accepted() -> None:
    llm = FakeLlm("```json\n" + json.dumps(_answer()) + "\n```")
    use_case, _ = _use_case(llm)
    draft = await use_case.execute(INPUT, approver="u")
    assert len(draft.levels) == 2


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        json.dumps(_answer(scoring_type="VIBES")),
        json.dumps(_answer(level_count=3)),  # asked for 2
        json.dumps({"levels": [{"sequence": 1, "name": "x", "skills": [_skill("a")]}]}),
    ],
)
async def test_a_bad_answer_is_a_provider_error_and_still_counted(text: str) -> None:
    use_case, calls = _use_case(FakeLlm(text))
    with pytest.raises(AiProviderError):
        await use_case.execute(INPUT, approver="u")
    assert len(calls.recorded) == 1


async def test_disabled_port_propagates_and_records_nothing() -> None:
    use_case, calls = _use_case(DisabledLlmPort())
    with pytest.raises(AiDisabled):
        await use_case.execute(INPUT, approver="u")
    assert calls.recorded == []


async def test_cap_reached_refuses_before_the_model_is_called() -> None:
    llm = FakeLlm(json.dumps(_answer()))
    use_case, calls = _use_case(llm, used=2, cap=2)
    with pytest.raises(AiMonthlyCapReached):
        await use_case.execute(INPUT, approver="u")
    assert llm.calls == [] and calls.recorded == []


async def test_the_model_sees_exactly_the_allowed_facts() -> None:
    llm = FakeLlm(json.dumps(_answer()))
    use_case, _ = _use_case(llm)
    await use_case.execute(INPUT, approver="Pat Owner pat@example.test 555-0100")

    (call,) = llm.calls
    assert json.loads(call["user"]) == {
        "sport": "badminton",
        "age_band": "8-10",
        "level_count": 2,
        "notes": "Fun first",
    }
    for leaked in ("Pat", "example.test", "555"):
        assert leaked not in call["user"]
    assert call["prompt_version"] == "skill-ladder-v1"
    assert call["system"] == PROMPTS["skill_ladder"].system_text
    assert '"levels"' in call["system"] and '"criteria"' in call["system"]
    assert "JSON only" in call["system"]


def test_input_refuses_extra_fields() -> None:
    with pytest.raises(ValueError):
        SkillLadderInput(sport="s", age_band="a", student_name="Kit")  # type: ignore[call-arg]


def test_scoring_type_mirrors_the_curriculum_literal() -> None:
    assert set(get_args(SkillScoringType)) == set(get_args(ScoringType))


def _program(program_id: str, sport: str) -> Program:
    return Program(
        program_id=program_id,
        academy_id="",
        sport=sport,
        name="P",
        created_at=NOW,
        updated_at=NOW,
        created_by="u",
    )


async def test_sport_lookup_is_tenant_scoped() -> None:
    repo = MongoProgramRepository(AsyncMongoMockClient()["test_db"])
    lookup = CurriculumProgramSportLookup(repo)
    with tenant_scope("acad-a"):
        await repo.save(_program("prog-1", "badminton"))
        assert await lookup.sport_of("prog-1") == "badminton"
        assert await lookup.sport_of("missing") is None
    with tenant_scope("acad-b"):
        assert await lookup.sport_of("prog-1") is None


def test_compose_reports_enabled_only_off_the_disabled_port() -> None:
    db = AsyncMongoMockClient()["test_db"]
    record = RecordAiCall(calls=FakeCalls(), cap_source=FakeCap())
    off = compose_ai_curriculum(
        db,
        AiComposition(
            llm=DisabledLlmPort(), record_ai_call=record, entitlement=PlatformAiEntitlement(None)
        ),
    )
    on = compose_ai_curriculum(
        db,
        AiComposition(
            llm=FakeLlm("{}"), record_ai_call=record, entitlement=PlatformAiEntitlement(None)
        ),
    )
    assert (off.enabled, on.enabled) == (False, True)
