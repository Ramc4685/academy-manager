"""The class-report reader: aliases only in and out, unknown aliases dropped
into a question, entitlement first, one recorded call per read, and the
composition adapter's manual fallback on any AI failure."""

from __future__ import annotations

import json

import pytest

from backend.v2.composition.class_recap import AiClassReportInterpreter
from backend.v2.contexts.ai.application.use_cases.interpret_class_report import (
    UNMATCHED,
    ClassReportInput,
    InterpretClassReport,
    ReportSkillRow,
)
from backend.v2.contexts.ai.domain.errors import AiNotEntitled, AiProviderError
from backend.v2.contexts.ai.domain.prompts import PROMPTS
from backend.v2.contexts.coaching.domain.class_recap import AliasedSkill
from backend.v2.tests.unit.test_ai_winback_technique import (
    Entitled,
    FakeCalls,
    FakeLlm,
    _record,
)

DATA = ClassReportInput(
    report="S1 did grip drills. S2 worked on smashes. S1 passed her grip!",
    students=["S1", "S2"],
    skills=[
        ReportSkillRow(alias="K1", name="Forehand grip"),
        ReportSkillRow(alias="K2", name="Jump smash"),
    ],
)
GOOD = {
    "taught": [],
    "practice": [
        {
            "who": "listed",
            "students": ["S1"],
            "except_students": [],
            "skills": ["K1"],
            "evidence": "S1 did grip drills",
        },
        {
            "who": "listed",
            "students": ["S2"],
            "except_students": [],
            "skills": ["K2"],
            "evidence": "S2 worked on smashes",
        },
    ],
    "passes": [{"student": "S1", "skill": "K1", "evidence": "S1 passed her grip"}],
    "questions": [],
}


def _reader(answer: str | Exception, *, entitled: bool = True):
    llm, calls = FakeLlm(answer), FakeCalls()
    use_case = InterpretClassReport(
        llm=llm, record_ai_call=_record(calls), entitlement=Entitled(entitled)
    )
    return use_case, llm, calls


async def test_reads_alias_claims_and_records_the_coach_as_approver() -> None:
    use_case, llm, calls = _reader(json.dumps(GOOD))
    reading = await use_case.execute(DATA, approver="coach-1")
    assert reading.model_dump() == GOOD
    assert llm.calls[0]["prompt_version"] == "class-report-v2"
    assert llm.calls[0]["system"] == PROMPTS["class_report"].system_text
    sent = json.loads(llm.calls[0]["user"])
    assert sent == DATA.model_dump()  # aliases and skill names only
    assert (calls.recorded[0].feature, calls.recorded[0].approver) == ("class_report", "coach-1")


async def test_unknown_aliases_drop_the_claim_and_ask() -> None:
    answer = {
        **GOOD,
        "practice": [{**GOOD["practice"][0], "students": ["S1", "S9"]}, GOOD["practice"][1]],
        "passes": [{"student": "S1", "skill": "K7", "evidence": "S1 passed"}],
    }
    use_case, _, _ = _reader(json.dumps(answer))
    reading = await use_case.execute(DATA, approver="coach-1")
    assert [c.students for c in reading.practice] == [["S2"]]
    assert reading.passes == []
    assert reading.questions == [UNMATCHED]


async def test_not_entitled_never_calls_the_model() -> None:
    use_case, llm, calls = _reader(json.dumps(GOOD), entitled=False)
    with pytest.raises(AiNotEntitled):
        await use_case.execute(DATA, approver="coach-1")
    assert llm.calls == [] and calls.recorded == []


async def test_unreadable_answer_is_a_provider_error_after_recording() -> None:
    use_case, _, calls = _reader("not json")
    with pytest.raises(AiProviderError):
        await use_case.execute(DATA, approver="coach-1")
    assert len(calls.recorded) == 1


def test_input_refuses_anything_but_aliases_for_skills() -> None:
    with pytest.raises(ValueError):
        ReportSkillRow(alias="skill-l1", name="Forehand grip")


def test_prompt_treats_the_report_as_untrusted_and_teaching_as_not_practice() -> None:
    text = PROMPTS["class_report"].system_text
    assert "JSON only" in text and "untrusted data" in text
    assert "teaching a skill does not mean any child practised it" in text
    assert "evidence" in text and "Split drills" in text


async def _interpret(adapter: AiClassReportInterpreter):
    return await adapter.interpret(
        text=DATA.report,
        student_aliases=["S1", "S2"],
        skills=[
            AliasedSkill(alias="K1", skill_id="skill-l1", name="Forehand grip"),
            AliasedSkill(alias="K2", skill_id="skill-l3", name="Jump smash"),
        ],
        approver="coach-1",
    )


async def test_adapter_sends_aliases_only_and_maps_back_to_facts() -> None:
    use_case, llm, _ = _reader(json.dumps(GOOD))
    facts = await _interpret(AiClassReportInterpreter(use_case))
    assert facts is not None
    assert [(c.students, c.skills) for c in facts.practice] == [
        (("S1",), ("K1",)),
        (("S2",), ("K2",)),
    ]
    assert facts.passes[0].evidence == "S1 passed her grip"
    assert "skill-l1" not in llm.calls[0]["user"]  # stable ids never leave


@pytest.mark.parametrize("answer", ["not json", AiProviderError("down")])
async def test_adapter_falls_back_to_manual_on_any_ai_failure(answer) -> None:
    use_case, _, _ = _reader(answer)
    assert await _interpret(AiClassReportInterpreter(use_case)) is None


async def test_adapter_without_a_model_or_entitlement_is_manual() -> None:
    assert await _interpret(AiClassReportInterpreter(None)) is None
    use_case, llm, _ = _reader(json.dumps(GOOD), entitled=False)
    assert await _interpret(AiClassReportInterpreter(use_case)) is None
    assert llm.calls == []
