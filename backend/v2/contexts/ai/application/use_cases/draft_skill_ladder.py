"""B1: draft a skill ladder (levels, skills, observable criteria) from a sport
and an age band. Zero child data: the model sees exactly ``SkillLadderInput``.

Nothing here is saved. The route answers the draft; the owner edits it in the
curriculum editor and saves through the existing level/skill/criterion routes.
"""

from __future__ import annotations

import json
import re
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, ValidationError

from backend.v2.contexts.ai.application.ports import LlmPort
from backend.v2.contexts.ai.application.use_cases.record_ai_call import RecordAiCall
from backend.v2.contexts.ai.domain.errors import AiProviderError
from backend.v2.contexts.ai.domain.prompts import PROMPTS

FEATURE = "skill_ladder"
MAX_TOKENS = 4000

#: Mirror of ``contexts.curriculum.domain.models.ScoringType`` (contexts never
#: import each other); ``test_draft_skill_ladder`` pins the two in sync.
SkillScoringType = Literal[
    "ATTEMPT_BASED",
    "CHECKLIST_BASED",
    "COACH_APPROVAL",
    "RALLY_COUNT",
    "TIME_BASED",
    "POINTS_BASED",
]

_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


class SkillLadderInput(BaseModel):
    """Everything the model is allowed to see, and nothing else."""

    model_config = {"frozen": True, "extra": "forbid"}

    sport: str = Field(min_length=1, max_length=60)
    age_band: str = Field(min_length=1, max_length=30)
    level_count: int = Field(default=4, ge=2, le=6)
    notes: str = Field(default="", max_length=500)


class DraftSkill(BaseModel):
    model_config = {"frozen": True}

    name: str = Field(min_length=1, max_length=60)
    description: str = Field(default="", max_length=300)
    scoring_type: SkillScoringType
    is_required: bool = True
    criteria: list[Annotated[str, StringConstraints(min_length=1, max_length=200)]] = Field(
        min_length=1, max_length=5
    )


class DraftLevel(BaseModel):
    model_config = {"frozen": True}

    sequence: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=60)
    description: str = Field(default="", max_length=300)
    skills: list[DraftSkill] = Field(min_length=2, max_length=6)


class SkillLadderDraft(BaseModel):
    model_config = {"frozen": True}

    levels: list[DraftLevel] = Field(min_length=2, max_length=6)


def parse_skill_ladder(text: str, *, level_count: int) -> SkillLadderDraft:
    """Strict read of the model's answer; anything off is a 502, never a half ladder."""
    fenced = _FENCE.match(text)
    raw = fenced.group(1) if fenced else text
    try:
        draft = SkillLadderDraft.model_validate(json.loads(raw))
    except (ValueError, ValidationError) as exc:
        raise AiProviderError("the model's answer could not be read") from exc
    if [level.sequence for level in draft.levels] != list(range(1, level_count + 1)):
        raise AiProviderError("the model's answer could not be read")
    return draft


class DraftSkillLadder:
    prompt_version = PROMPTS[FEATURE].version

    def __init__(self, *, llm: LlmPort, record_ai_call: RecordAiCall) -> None:
        self._llm = llm
        self._record = record_ai_call

    async def execute(self, inp: SkillLadderInput, *, approver: str) -> SkillLadderDraft:
        await self._record.assert_under_cap()
        prompt = PROMPTS[FEATURE]
        result = await self._llm.complete(
            prompt_version=prompt.version,
            system=prompt.system_text,
            user=json.dumps(inp.model_dump(), sort_keys=True),
            max_tokens=MAX_TOKENS,
        )
        # Recorded before parsing so a malformed answer still counts.
        await self._record.execute(
            feature=FEATURE, prompt_version=prompt.version, result=result, approver=approver
        )
        return parse_skill_ladder(result.text, level_count=inp.level_count)
