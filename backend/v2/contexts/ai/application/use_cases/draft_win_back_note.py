"""B6 part 1: draft the personalised second paragraph of a win-back email.

The approval is the owner's standing one (``ai.win_back_personalised`` on the
academy document); the caller passes that owner's id as ``approver``. The
model sees exactly ``WinBackNoteInput`` and nothing else about the family.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Literal, Protocol

from pydantic import BaseModel, Field

from backend.v2.contexts.ai.application.json_answer import UNREADABLE, parse_json_answer
from backend.v2.contexts.ai.application.ports import AiEntitlement, LlmPort
from backend.v2.contexts.ai.application.use_cases.record_ai_call import RecordAiCall
from backend.v2.contexts.ai.domain.errors import AiNotEntitled, AiProviderError
from backend.v2.contexts.ai.domain.prompts import PROMPTS

FEATURE = "win_back_note"
MAX_TOKENS = 400
# Mail clients auto-link these even after html.escape, and the paragraph goes
# out under the standing approval with no per-message review.
_LINK_LIKE = re.compile(r"://|www\.|@|\.[a-z]{2,}", re.IGNORECASE)


class WinBackRecentWin(BaseModel):
    model_config = {"extra": "forbid", "frozen": True}

    skill_name: str = Field(min_length=1)
    when: str = Field(pattern=r"^\d{4}-\d{2}$")


class WinBackNoteInput(BaseModel):
    """Exactly what the model may see."""

    model_config = {"extra": "forbid", "frozen": True}

    child_first_name: str = Field(min_length=1)
    milestone_days: Literal[30, 60, 90]
    level_name: str | None
    recent_wins: list[WinBackRecentWin] = Field(max_length=3)
    academy_name: str = Field(min_length=1)


class WinBackNoteDraft(BaseModel):
    model_config = {"extra": "forbid"}

    paragraph: str = Field(min_length=1)


class DraftWinBackNote:
    def __init__(
        self, *, llm: LlmPort, record_ai_call: RecordAiCall, entitlement: AiEntitlement
    ) -> None:
        self._llm = llm
        self._record = record_ai_call
        self._entitlement = entitlement

    async def execute(self, data: WinBackNoteInput, *, approver: str | None) -> WinBackNoteDraft:
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
        draft = parse_json_answer(result.text, WinBackNoteDraft)
        words = draft.paragraph.split()
        digits_ok = all(d == str(data.milestone_days) for d in re.findall(r"\d+", draft.paragraph))
        if (
            len(words) > 80
            or data.child_first_name not in draft.paragraph
            or not digits_ok
            or _LINK_LIKE.search(draft.paragraph)
        ):
            raise AiProviderError(UNREADABLE)
        return draft


class WinBackPersonalisationSetting(Protocol):
    """``ai.win_back_personalised`` and ``..._by`` on the academy in scope."""

    async def get(self) -> tuple[bool, str | None]: ...


class WinBackFactsSource(Protocol):
    """Current level name and up to three recent passed skills for a student,
    implemented in composition over existing student_progress reads."""

    async def facts(self, student_id: str) -> tuple[str | None, list[WinBackRecentWin]]: ...


class AcademyNameSource(Protocol):
    async def get_academy_name(self, academy_id: str) -> str | None: ...


class PersonaliseWinBackParagraph:
    """The win-back notifier's hook: ``None`` when the owner has not turned the
    standing approval on (no model call); otherwise the drafted paragraph.
    Every AI error propagates so the notifier falls back to the template."""

    def __init__(
        self,
        *,
        setting: WinBackPersonalisationSetting,
        facts: WinBackFactsSource,
        academies: AcademyNameSource,
        draft: DraftWinBackNote,
        academy_id: Callable[[], str],
    ) -> None:
        self._setting = setting
        self._facts = facts
        self._academies = academies
        self._draft = draft
        self._academy_id = academy_id

    async def paragraph(
        self, *, student_id: str, child_first_name: str, milestone_days: int
    ) -> str | None:
        enabled, approver = await self._setting.get()
        if not enabled:
            return None
        level_name, wins = await self._facts.facts(student_id)
        academy_name = await self._academies.get_academy_name(self._academy_id()) or "the academy"
        draft = await self._draft.execute(
            WinBackNoteInput(
                child_first_name=child_first_name,
                milestone_days=milestone_days,
                level_name=level_name,
                recent_wins=wins[:3],
                academy_name=academy_name,
            ),
            approver=approver,
        )
        return draft.paragraph
