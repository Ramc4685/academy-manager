"""B1 skill-ladder generator wiring (AI strategy Phase 2, Track B).

Attached at ``app.state.ai_curriculum`` next to ``app.state.ai``. The ai
context never imports curriculum, so the program's sport reaches the route
through ``ProgramSportLookup``, implemented here over the tenant-scoped
program repository.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from backend.v2.composition.ai import AiComposition
from backend.v2.contexts.ai.application.use_cases.draft_skill_ladder import DraftSkillLadder
from backend.v2.contexts.ai.infrastructure.disabled_llm_port import DisabledLlmPort
from backend.v2.contexts.curriculum.infrastructure.mongo_program_repo import MongoProgramRepository


class ProgramSportLookup(Protocol):
    async def sport_of(self, program_id: str) -> str | None: ...


class CurriculumProgramSportLookup:
    def __init__(self, programs: MongoProgramRepository) -> None:
        self._programs = programs

    async def sport_of(self, program_id: str) -> str | None:
        program = await self._programs.get(program_id)
        return program.sport if program else None


@dataclass(frozen=True)
class AiCurriculumComposition:
    #: False while the disabled port is wired, so the frontend can hide AI buttons.
    enabled: bool
    program_sport: ProgramSportLookup
    draft_skill_ladder: DraftSkillLadder


def compose_ai_curriculum(db: Any, ai: AiComposition) -> AiCurriculumComposition:
    return AiCurriculumComposition(
        enabled=not isinstance(ai.llm, DisabledLlmPort),
        program_sport=CurriculumProgramSportLookup(MongoProgramRepository(db)),
        draft_skill_ladder=DraftSkillLadder(llm=ai.llm, record_ai_call=ai.record_ai_call),
    )
