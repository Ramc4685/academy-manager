"""B4: draft the parent progress narrative (one paid model call).

Order, pinned by ``tests/unit/test_progress_narrative.py``: entitlement (403)
-> monthly cap (429) -> ``llm.complete`` -> ``record_ai_call.execute`` before
any parsing (a malformed answer is still a spent call) -> strict parse (502).
The model sees exactly ``ProgressNarrativeInput``: first name, level, program,
today's skills with their criteria and the coach's words, and the two counts.
"""

from __future__ import annotations

import json
import re

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.v2.contexts.ai.application.ports import AiEntitlement, LlmPort
from backend.v2.contexts.ai.application.use_cases.record_ai_call import RecordAiCall
from backend.v2.contexts.ai.domain.errors import AiNotEntitled, AiProviderError
from backend.v2.contexts.ai.domain.models import AiCallRecord
from backend.v2.contexts.ai.domain.prompts import PROMPTS

FEATURE = "progress_narrative"
MAX_TOKENS = 400
MAX_WORDS = 70
_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


class SkillMasteredToday(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    skill_name: str
    #: The skill's observable criteria (the coach's quick-tags).
    criteria: list[str]
    #: The coach's note on this win, if any.
    coach_words: str | None = None


class ProgressNarrativeInput(BaseModel):
    """Everything the model may see. ``extra="forbid"`` keeps it that way."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    child_first_name: str
    level_name: str
    program_name: str
    skills_mastered_today: list[SkillMasteredToday] = Field(min_length=1)
    passed_in_level: int = Field(ge=0)
    total_in_level: int = Field(ge=0)
    finished_level: bool


class NarrativeDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str = Field(min_length=1, max_length=500)
    #: The skill names the model says it cited; each must be an input skill.
    skills_mentioned: list[str] = Field(default_factory=list)


def parse_narrative(raw: str, data: ProgressNarrativeInput) -> NarrativeDraft:
    """Strict parse of the model's answer; any doubt is ``AiProviderError``."""
    match = _FENCE.match(raw)
    try:
        draft = NarrativeDraft.model_validate(json.loads(match.group(1) if match else raw))
    except (ValueError, ValidationError) as exc:
        raise AiProviderError("the model's answer could not be read") from exc
    text = " ".join(draft.text.split())
    skill_names = {s.skill_name for s in data.skills_mastered_today}
    # The two counts, plus any number that is part of a given name ("Level 2").
    allowed_numbers = {str(data.passed_in_level), str(data.total_in_level)} | set(
        re.findall(r"\d+", " ".join([data.level_name, data.program_name, *skill_names]))
    )
    if (
        len(text.split()) > MAX_WORDS
        or any(n not in allowed_numbers for n in re.findall(r"\d+", text))
        or any(
            name not in skill_names or name.lower() not in text.lower()
            for name in draft.skills_mentioned
        )
    ):
        raise AiProviderError("the model's answer could not be read")
    return draft.model_copy(update={"text": text})


class DraftProgressNarrative:
    def __init__(
        self, *, llm: LlmPort, record_ai_call: RecordAiCall, entitlement: AiEntitlement
    ) -> None:
        self._llm = llm
        self._record = record_ai_call
        self._entitlement = entitlement

    async def execute(self, data: ProgressNarrativeInput) -> tuple[NarrativeDraft, AiCallRecord]:
        if not await self._entitlement.has_ai():
            raise AiNotEntitled("AI notes are part of the Growth plan")
        await self._record.assert_under_cap()
        prompt = PROMPTS[FEATURE]
        result = await self._llm.complete(
            prompt_version=prompt.version,
            system=prompt.system_text,
            user=data.model_dump_json(),
            max_tokens=MAX_TOKENS,
        )
        call = await self._record.execute(
            feature=FEATURE, prompt_version=prompt.version, result=result, approver=None
        )
        return parse_narrative(result.text, data), call
