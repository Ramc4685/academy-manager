"""Month-dates helper: read a pasted rental agreement or a typed note and
propose which of the month's class dates have NO class, with a reason.

The model sees only the pasted text (cut to :data:`MAX_TEXT_CHARS`) and the
month's class dates with their weekday: no student, family or class names.
Nothing is written but the ``ai_calls`` row; the admin page pre-ticks the
suggested dates and the existing "Call off dates" button stays the only
write path.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.v2.contexts.ai.application.ports import LlmPort
from backend.v2.contexts.ai.application.use_cases.record_ai_call import RecordAiCall
from backend.v2.contexts.ai.domain.errors import AiProviderError
from backend.v2.contexts.ai.domain.prompts import PROMPTS

FEATURE: Final = "schedule_dates"
MAX_TOKENS: Final = 1200
MAX_TEXT_CHARS: Final = 8000
MAX_DATES: Final = 62

_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$")


class NoClassDate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: date
    reason: str = Field(default="", max_length=200)


class NoClassDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    no_class: list[NoClassDate]
    notes: str = Field(default="", max_length=500)


@dataclass(frozen=True)
class SuggestNoClassDatesResult:
    draft: NoClassDraft
    prompt_version: str


def user_message(text: str, class_dates: list[date]) -> str:
    facts = {
        "class_dates": [{"date": d.isoformat(), "weekday": d.strftime("%A")} for d in class_dates],
        "pasted_text": text[:MAX_TEXT_CHARS],
    }
    return json.dumps(facts, ensure_ascii=False, indent=1)


def parse_draft(answer: str, *, class_dates: list[date]) -> NoClassDraft:
    """Strict: the exact JSON shape, every date one of the class dates, each
    at most once. Anything else is a provider error (502)."""
    try:
        draft = NoClassDraft.model_validate(json.loads(_FENCE.sub("", answer)))
    except (ValueError, ValidationError) as exc:
        raise AiProviderError("the model's answer could not be read") from exc
    picked = [d.date for d in draft.no_class]
    if len(set(picked)) != len(picked) or not set(picked) <= set(class_dates):
        raise AiProviderError("the model's answer could not be read")
    return draft


class SuggestNoClassDates:
    def __init__(self, *, llm: LlmPort, record_ai_call: RecordAiCall) -> None:
        self._llm = llm
        self._record = record_ai_call

    async def execute(
        self, *, text: str, class_dates: list[date], approver: str
    ) -> SuggestNoClassDatesResult:
        dates = sorted(set(class_dates))
        prompt = PROMPTS[FEATURE]
        async with self._record.reserve(FEATURE):
            result = await self._llm.complete(
                prompt_version=prompt.version,
                system=prompt.system_text,
                user=user_message(text, dates),
                max_tokens=MAX_TOKENS,
            )
        # Recorded before parsing so a malformed answer is still counted.
        await self._record.execute(
            feature=FEATURE, prompt_version=prompt.version, result=result, approver=approver
        )
        return SuggestNoClassDatesResult(
            draft=parse_draft(result.text, class_dates=dates), prompt_version=prompt.version
        )
