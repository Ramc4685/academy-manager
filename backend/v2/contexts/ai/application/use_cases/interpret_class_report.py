"""Read a coach's after-class report into claims over local aliases.

The model sees only what Coaching already redacted and aliased: the report
with names replaced by ``S<n>`` and contact details removed, the bare student
aliases (no names, ids or attendance), and the academy's skills as ``K<n>``
with their curriculum names. Every claim must quote the report words it
rests on; Coaching checks those quotes deterministically before anything is
applied, so this use case only reads and drops aliases it was never given.
The coach's explicit "read with AI" submit is the instruction and the
approver of the one recorded ``ai_calls`` row.
"""

from __future__ import annotations

import json
import re
from typing import Literal

from pydantic import BaseModel, Field

from backend.v2.contexts.ai.application.json_answer import parse_json_answer
from backend.v2.contexts.ai.application.ports import AiEntitlement, LlmPort
from backend.v2.contexts.ai.application.use_cases.record_ai_call import RecordAiCall
from backend.v2.contexts.ai.domain.errors import AiNotEntitled
from backend.v2.contexts.ai.domain.prompts import PROMPTS

FEATURE = "class_report"
MAX_TOKENS = 800
REPORT_MAX_CHARS = 2400  # the coach's 2,000 chars plus alias/redaction tokens
MAX_QUESTIONS = 3
UNMATCHED = "Part of the report named a student or skill I could not match. Who or what was it?"


class ReportSkillRow(BaseModel):
    model_config = {"extra": "forbid", "frozen": True}

    alias: str = Field(pattern=r"^K\d+$")
    name: str = Field(min_length=1, max_length=120)


class ClassReportInput(BaseModel):
    """Exactly what the model may see."""

    model_config = {"extra": "forbid", "frozen": True}

    report: str = Field(min_length=1, max_length=REPORT_MAX_CHARS)
    students: list[str] = Field(max_length=100)
    skills: list[ReportSkillRow] = Field(min_length=1, max_length=200)


class ReadTaught(BaseModel):
    model_config = {"extra": "forbid", "frozen": True}

    skills: list[str] = Field(min_length=1, max_length=30)
    evidence: str = Field(min_length=1, max_length=400)


class ReadPractice(BaseModel):
    model_config = {"extra": "forbid", "frozen": True}

    who: Literal["group", "listed"]
    students: list[str] = Field(default_factory=list, max_length=100)
    except_students: list[str] = Field(default_factory=list, max_length=100)
    skills: list[str] = Field(min_length=1, max_length=30)
    evidence: str = Field(min_length=1, max_length=400)


class ReadPass(BaseModel):
    model_config = {"extra": "forbid", "frozen": True}

    student: str
    skill: str
    evidence: str = Field(min_length=1, max_length=400)


class ClassReportReading(BaseModel):
    model_config = {"extra": "forbid", "frozen": True}

    taught: list[ReadTaught] = Field(default_factory=list, max_length=20)
    practice: list[ReadPractice] = Field(default_factory=list, max_length=20)
    passes: list[ReadPass] = Field(default_factory=list, max_length=50)
    # Parsed loosely so a chatty model does not fail the call; ground() keeps MAX_QUESTIONS.
    questions: list[str] = Field(default_factory=list, max_length=20)


class InterpretClassReport:
    def __init__(
        self, *, llm: LlmPort, record_ai_call: RecordAiCall, entitlement: AiEntitlement
    ) -> None:
        self._llm = llm
        self._record = record_ai_call
        self._entitlement = entitlement

    async def execute(self, data: ClassReportInput, *, approver: str) -> ClassReportReading:
        if not await self._entitlement.has_ai():
            raise AiNotEntitled("this academy's plan does not include AI features")
        async with self._record.reserve(FEATURE):
            prompt = PROMPTS[FEATURE]
            result = await self._llm.complete(
                prompt_version=prompt.version,
                system=prompt.system_text,
                user=json.dumps(data.model_dump(), ensure_ascii=False),
                max_tokens=MAX_TOKENS,
            )
        await self._record.execute(
            feature=FEATURE, prompt_version=prompt.version, result=result, approver=approver
        )
        return ground(parse_json_answer(result.text, ClassReportReading), data)


def ground(reading: ClassReportReading, data: ClassReportInput) -> ClassReportReading:
    """Drop every claim that uses an alias the model was not given; a dropped
    claim becomes a question rather than a silent guess."""
    students = set(data.students)
    skills = {s.alias for s in data.skills}
    unmatched = False

    def known(ids: list[str], allowed: set[str]) -> bool:
        nonlocal unmatched
        ok = all(i in allowed for i in ids)
        unmatched = unmatched or not ok
        return ok

    taught = [c for c in reading.taught if known(c.skills, skills)]
    practice = [
        c
        for c in reading.practice
        if known(c.skills, skills)
        and known(c.students, students)
        and known(c.except_students, students)
    ]
    passes = [
        p for p in reading.passes if known([p.student], students) and known([p.skill], skills)
    ]
    skill_names = {s.alias: s.name for s in data.skills}

    def tidy(question: str) -> str:
        # One line, no codes the coach never wrote: K<n> becomes the skill's
        # name, an S<n> the model was not given becomes "a student".
        line = " ".join(question.split())[:200]
        line = re.sub(r"(?<!\w)K\d+(?!\w)", lambda m: skill_names.get(m[0], "a skill"), line)
        return re.sub(
            r"(?<!\w)S\d+(?!\w)", lambda m: m[0] if m[0] in students else "a student", line
        )

    questions = [UNMATCHED] if unmatched else []  # first, so the cap never drops it
    questions += [tidy(q) for q in reading.questions if q.strip()]
    return ClassReportReading(
        taught=taught,
        practice=practice,
        passes=passes,
        questions=list(dict.fromkeys(questions))[:MAX_QUESTIONS],
    )
