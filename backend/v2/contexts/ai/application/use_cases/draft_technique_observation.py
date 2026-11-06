"""B6 part 2: map a coach's typed observation to one criterion of the child's
current level and phrase it for the parent. Text only, no audio or video.

The approval is the existing skill-note save; this use case stores nothing
but the ``ai_calls`` row (``approver`` = the coach asking for the draft).
"""

from __future__ import annotations

import json
import re
from typing import Protocol

from pydantic import BaseModel, Field

from backend.v2.contexts.ai.application.json_answer import UNREADABLE, parse_json_answer
from backend.v2.contexts.ai.application.ports import AiEntitlement, LlmPort
from backend.v2.contexts.ai.application.use_cases.record_ai_call import RecordAiCall
from backend.v2.contexts.ai.domain.errors import AiNotEntitled, AiProviderError
from backend.v2.contexts.ai.domain.prompts import PROMPTS
from backend.v2.shared.http.errors import DomainError

FEATURE = "technique_observation"
MAX_TOKENS = 400
OBSERVATION_MAX_CHARS = 500


class TechniqueCandidate(BaseModel):
    model_config = {"extra": "forbid", "frozen": True}

    criterion_id: str = Field(min_length=1)
    skill_id: str = Field(min_length=1)
    skill_name: str = Field(min_length=1)
    description: str = Field(min_length=1)


class TechniqueObservationInput(BaseModel):
    """Exactly what the model may see. ``observation`` is the coach's own
    text, quoted to the model as untrusted data."""

    model_config = {"extra": "forbid", "frozen": True}

    child_first_name: str = Field(min_length=1)
    observation: str = Field(min_length=1, max_length=OBSERVATION_MAX_CHARS)
    candidate_criteria: list[TechniqueCandidate] = Field(min_length=1, max_length=40)


class TechniqueObservationDraft(BaseModel):
    model_config = {"extra": "forbid"}

    criterion_id: str
    skill_id: str
    parent_sentence: str = Field(min_length=1)
    coach_summary: str = Field(min_length=1)


class DraftTechniqueObservation:
    def __init__(
        self, *, llm: LlmPort, record_ai_call: RecordAiCall, entitlement: AiEntitlement
    ) -> None:
        self._llm = llm
        self._record = record_ai_call
        self._entitlement = entitlement

    async def execute(
        self, data: TechniqueObservationInput, *, approver: str
    ) -> TechniqueObservationDraft:
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
        draft = parse_json_answer(result.text, TechniqueObservationDraft)
        chosen = next(
            (c for c in data.candidate_criteria if c.criterion_id == draft.criterion_id), None
        )
        if (
            chosen is None
            or chosen.skill_id != draft.skill_id
            or len(draft.parent_sentence.split()) > 40
            or re.search(r"\d", draft.parent_sentence)
            or len(draft.coach_summary.split()) > 20
        ):
            raise AiProviderError(UNREADABLE)
        return draft


class TechniqueNoCandidates(DomainError):
    """The student has no current level with skill criteria to map onto."""

    code = "Ai.TechniqueNoCandidates"
    status_code = 409


class TechniqueFacts(BaseModel):
    model_config = {"frozen": True}

    child_first_name: str
    candidates: list[TechniqueCandidate]


class TechniqueCandidateSource(Protocol):
    """The student's first name and the criteria of their CURRENT level,
    implemented in composition over existing student_progress reads."""

    async def candidates(self, student_id: str) -> TechniqueFacts: ...


class TechniqueObservationSuggestion(TechniqueObservationDraft):
    skill_name: str


class DraftTechniqueObservationForStudent:
    def __init__(self, *, source: TechniqueCandidateSource, draft: DraftTechniqueObservation):
        self._source = source
        self._draft = draft

    async def execute(
        self, *, student_id: str, observation: str, approver: str
    ) -> TechniqueObservationSuggestion:
        facts = await self._source.candidates(student_id)
        if not facts.candidates:
            raise TechniqueNoCandidates("student has no current level with criteria")
        draft = await self._draft.execute(
            TechniqueObservationInput(
                child_first_name=facts.child_first_name,
                observation=observation,
                candidate_criteria=facts.candidates[:40],
            ),
            approver=approver,
        )
        chosen = next(c for c in facts.candidates if c.criterion_id == draft.criterion_id)
        return TechniqueObservationSuggestion(**draft.model_dump(), skill_name=chosen.skill_name)
