"""B6 part 1 wiring: the owner's standing approval for AI win-back wording and
the personaliser the win-back notifier calls for its second paragraph.

Attached at ``app.state.ai_win_back`` after ``app.state.ai`` and
``app.state.win_back`` exist; the personaliser is hung on the already-built
``WinBackNotificationAdapter`` here, so ``compose_win_back`` stays unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.v2.composition.ai import AiComposition
from backend.v2.composition.win_back import WinBackComposition
from backend.v2.contexts.ai.application.use_cases.draft_win_back_note import (
    DraftWinBackNote,
    PersonaliseWinBackParagraph,
    WinBackRecentWin,
)
from backend.v2.contexts.curriculum.infrastructure.mongo_level_repo import MongoLevelRepository
from backend.v2.contexts.curriculum.infrastructure.mongo_skill_repo import MongoSkillRepository
from backend.v2.contexts.identity.infrastructure.mongo_academy_repo import (
    MongoAcademyRepository,
)
from backend.v2.contexts.student_progress.infrastructure.curriculum_lookup_adapter import (
    CurriculumSkillLookupAdapter,
)
from backend.v2.contexts.student_progress.infrastructure.mongo_level_progress_repo import (
    MongoStudentLevelProgressRepository,
)
from backend.v2.contexts.student_progress.infrastructure.mongo_skill_progress_repo import (
    MongoStudentSkillProgressRepository,
)
from backend.v2.shared.tenancy import current_academy_id


class AcademyAiWinBackSetting:
    """``ai.win_back_personalised`` (default off) and ``ai.win_back_personalised_by``
    on the academy document, read and written for the academy in scope."""

    def __init__(self, academies: Any) -> None:
        self._academies = academies

    async def get(self) -> tuple[bool, str | None]:
        doc = await self._academies.find_by_id(current_academy_id())
        ai = (doc or {}).get("ai") if isinstance(doc, dict) else None
        if not isinstance(ai, dict) or ai.get("win_back_personalised") is not True:
            return False, None
        by = ai.get("win_back_personalised_by")
        return True, str(by) if by else None

    async def set(self, *, enabled: bool, user_id: str) -> bool:
        await self._academies.update_by_id(
            current_academy_id(),
            {
                "ai.win_back_personalised": enabled,
                "ai.win_back_personalised_by": user_id if enabled else None,
            },
        )
        return enabled


class StudentProgressWinBackFacts:
    """``WinBackFactsSource`` over the student's active level and recent PASSED
    skills (the same reads the passport and recent-updates views use)."""

    def __init__(self, *, level_progress: Any, skill_progress: Any, skill_lookup: Any) -> None:
        self._level_progress = level_progress
        self._skill_progress = skill_progress
        self._skill_lookup = skill_lookup

    async def facts(self, student_id: str) -> tuple[str | None, list[WinBackRecentWin]]:
        level_name: str | None = None
        for row in await self._level_progress.list_for_student(student_id):
            if row.status == "active":
                level = await self._skill_lookup.get_level(row.level_id)
                level_name = str(getattr(level, "name", "") or "") or None
                break
        wins: list[WinBackRecentWin] = []
        for row in await self._skill_progress.list_recent_for_student(student_id, limit=10):
            if row.status != "PASSED":
                continue
            skill = await self._skill_lookup.get_skill(row.skill_id)
            name = str(getattr(skill, "name", "") or "")
            if name:
                wins.append(
                    WinBackRecentWin(skill_name=name, when=row.last_updated_at.strftime("%Y-%m"))
                )
            if len(wins) == 3:
                break
        return level_name, wins


@dataclass(frozen=True)
class AiWinBackComposition:
    setting: AcademyAiWinBackSetting
    personaliser: PersonaliseWinBackParagraph


def compose_ai_win_back(
    db: Any, ai: AiComposition, win_back: WinBackComposition
) -> AiWinBackComposition:
    academies = MongoAcademyRepository(db)
    setting = AcademyAiWinBackSetting(academies)
    personaliser = PersonaliseWinBackParagraph(
        setting=setting,
        facts=StudentProgressWinBackFacts(
            level_progress=MongoStudentLevelProgressRepository(db),
            skill_progress=MongoStudentSkillProgressRepository(db),
            skill_lookup=CurriculumSkillLookupAdapter(
                skill_repo=MongoSkillRepository(db), level_repo=MongoLevelRepository(db)
            ),
        ),
        academies=academies,
        draft=DraftWinBackNote(
            llm=ai.llm, record_ai_call=ai.record_ai_call, entitlement=ai.entitlement
        ),
        academy_id=current_academy_id,
    )
    win_back.notifier.personaliser = personaliser
    return AiWinBackComposition(setting=setting, personaliser=personaliser)
