"""GET /api/v2/coach/academy — the coach shell's academy mark (row 14).

Deliberately the narrowest read in the coach BFF: name, logo and brand colour
only, for the request academy (`AuthClaims.academy_id`, stamped per-request
by `require_coach_surface`, never a boot-time tenant). Everything else about
the academy profile is admin/owner territory.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.v2.interfaces.coach.deps import CoachUseCases, get_coach_use_cases
from backend.v2.interfaces.coach.views import (
    CoachAcademyView,
    CoachPathwayLessonView,
    CoachPathwayLevelView,
    CoachPathwayProgramView,
    CoachPathwayResponse,
    CoachPathwaySkillView,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_coach_surface

router = APIRouter(tags=["coach.academy"])


@router.get(
    "/academy",
    response_model=CoachAcademyView,
    summary="The coach shell's academy mark (name, logo, brand colour)",
)
async def get_academy(
    claims: AuthClaims = Depends(require_coach_surface()),
    use_cases: CoachUseCases = Depends(get_coach_use_cases),
) -> CoachAcademyView:
    info = await use_cases.get_academy_info(academy_id=claims.academy_id)  # type: ignore[operator]
    return CoachAcademyView(**info)


def _video_url(card: object) -> str | None:
    for link in getattr(card, "resource_links", None) or []:
        if getattr(link, "url", None):
            return str(link.url)
    return None


@router.get(
    "/pathway",
    response_model=CoachPathwayResponse,
    summary="The academy's levels, skills and lesson plans (reference only)",
)
async def get_pathway(
    claims: AuthClaims = Depends(require_coach_surface()),
    use_cases: CoachUseCases = Depends(get_coach_use_cases),
) -> CoachPathwayResponse:
    """S68 "What we teach". Academy reference content for the request
    academy; no student or progress data. Retired levels, skills and cards are
    left out, and so are a card's citation fields."""
    curriculum = use_cases.curriculum
    if curriculum is None:
        return CoachPathwayResponse()
    programs: list[CoachPathwayProgramView] = []
    for program in await curriculum.list_programs.execute():
        pathway = await curriculum.get_full_pathway.execute(program.program_id)
        cards = [
            c for c in await curriculum.list_lesson_cards.execute(program.program_id) if c.is_active
        ]
        levels = []
        for entry in sorted(pathway.levels, key=lambda e: e.level.sequence):
            level = entry.level
            if not level.is_active:
                continue
            lessons = sorted(
                (c for c in cards if c.level_id == level.level_id),
                key=lambda c: (c.display_order, c.lesson_number),
            )
            levels.append(
                CoachPathwayLevelView(
                    level_id=level.level_id,
                    sequence=level.sequence,
                    name=level.name,
                    description=level.description,
                    skills=[
                        CoachPathwaySkillView(skill_id=s.skill.skill_id, name=s.skill.name)
                        for s in sorted(entry.skills, key=lambda s: s.skill.sequence)
                        if s.skill.is_active
                    ],
                    lessons=[
                        CoachPathwayLessonView(
                            card_id=c.card_id,
                            lesson_number=c.lesson_number,
                            title=c.title,
                            goal_summary=c.goal_summary,
                            teaching_points=list(c.teaching_points),
                            equipment=list(c.equipment),
                            safety_notes=list(c.safety_notes),
                            activity_summary=c.activity_summary,
                            video_url=_video_url(c),
                        )
                        for c in lessons
                    ],
                )
            )
        programs.append(
            CoachPathwayProgramView(program_id=program.program_id, name=program.name, levels=levels)
        )
    return CoachPathwayResponse(programs=programs)
