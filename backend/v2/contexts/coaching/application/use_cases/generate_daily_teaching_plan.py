"""Use case: build the coach's daily teaching plan.

Cross-context orchestrator (coaching application layer). It composes, with no
new write paths:

* ``ListCoachOccurrencesForDate`` — the coach's sessions for a date,
* ``GetSessionRoster`` — students per session,
* ``GetTeachingFocus`` (student_progress) — the next skill per student,
* curriculum lesson cards + level/skill YouTube refs + skill criteria,

into the *Today's Teaching Plan* DTO (plan section 4). Pathway truth lives in
student_progress; teaching content lives in curriculum — nothing is duplicated
here. When no pathway/program is configured the plan still lists the coach's
sessions with every roster student ``unplaced`` and ``pathway_configured`` false
(never a 5xx).
"""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any, Protocol

from pydantic import BaseModel, Field

# This orchestrator deliberately imports NOTHING from other bounded contexts —
# all cross-context dependencies (teaching focus, lesson cards, video refs,
# criteria) are duck-typed Protocols wired in the composition root. This keeps
# the no-cross-context-imports rule (ADR-0005) intact while still composing
# student_progress + curriculum + enrollment behaviour.

# ---------------------------------------------------------------------------
# Dependency ports (duck-typed; real adapters wired in composition)
# ---------------------------------------------------------------------------


class OccurrenceLister(Protocol):
    async def execute(self, coach_id: str, on_date: date) -> list[Any]: ...


class RosterGetter(Protocol):
    async def execute(self, session_id: str) -> list[Any]: ...


class TeachingFocusGetter(Protocol):
    async def for_students(self, students: list[tuple[str, str]], program_id: str) -> Any: ...


class LessonCardReader(Protocol):
    async def list_for_program(self, program_id: str) -> list[Any]: ...


class VideoRefReader(Protocol):
    async def list_for_level(self, level_id: str) -> list[Any]: ...
    async def list_for_skills(self, skill_ids: list[str]) -> list[Any]: ...


class CriterionReader(Protocol):
    async def list_for_skill(self, skill_id: str) -> list[Any]: ...


# ---------------------------------------------------------------------------
# Response DTOs (plan section 4 shape)
# ---------------------------------------------------------------------------


class VideoLink(BaseModel):
    model_config = {"frozen": True}

    title: str
    url: str


class ResourceLinkView(BaseModel):
    model_config = {"frozen": True}

    kind: str
    title: str
    url: str | None = None


class LessonCardView(BaseModel):
    model_config = {"frozen": True}

    card_id: str
    lesson_number: int
    title: str
    goal_summary: str = ""
    teaching_points: list[str] = Field(default_factory=list)
    equipment: list[str] = Field(default_factory=list)
    activity_summary: str = ""
    safety_notes: list[str] = Field(default_factory=list)
    source: str = ""
    module_name: str = ""
    lesson_range: str = ""
    page_hint: str | None = None
    resource_links: list[ResourceLinkView] = Field(default_factory=list)


class NextSkillView(BaseModel):
    model_config = {"frozen": True}

    skill_id: str
    name: str
    sequence: int
    level_id: str
    status: str
    is_review: bool = False
    criteria: list[str] = Field(default_factory=list)
    youtube_links: list[VideoLink] = Field(default_factory=list)


class StudentFocusView(BaseModel):
    model_config = {"frozen": True}

    student_id: str
    student_name: str
    next_skill: NextSkillView | None = None
    focus: str


class UnplacedStudent(BaseModel):
    model_config = {"frozen": True}

    student_id: str
    student_name: str


class LevelTeachingGroup(BaseModel):
    model_config = {"frozen": True}

    level_id: str
    level_name: str
    level_sequence: int
    youtube_links: list[VideoLink] = Field(default_factory=list)
    lesson_card: LessonCardView | None = None
    students: list[StudentFocusView] = Field(default_factory=list)


class SessionGroups(BaseModel):
    """Groups + unplaced for one session (the per-session payload)."""

    model_config = {"frozen": True}

    groups: list[LevelTeachingGroup] = Field(default_factory=list)
    unplaced: list[UnplacedStudent] = Field(default_factory=list)


class SessionTeachingPlan(BaseModel):
    model_config = {"frozen": True}

    session_id: str
    occurrence_id: str | None = None
    title: str = ""
    location: str = ""
    start_at: Any | None = None
    end_at: Any | None = None
    timezone: str | None = None
    groups: list[LevelTeachingGroup] = Field(default_factory=list)
    unplaced: list[UnplacedStudent] = Field(default_factory=list)


class DailyTeachingPlan(BaseModel):
    model_config = {"frozen": True}

    date: str
    program_id: str = ""
    program_name: str = ""
    pathway_configured: bool = False
    sessions: list[SessionTeachingPlan] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Use case
# ---------------------------------------------------------------------------


def _card_view(card: Any) -> LessonCardView:
    return LessonCardView(
        card_id=str(card.card_id),
        lesson_number=int(card.lesson_number),
        title=str(card.title),
        goal_summary=str(getattr(card, "goal_summary", "")),
        teaching_points=list(getattr(card, "teaching_points", [])),
        equipment=list(getattr(card, "equipment", [])),
        activity_summary=str(getattr(card, "activity_summary", "")),
        safety_notes=list(getattr(card, "safety_notes", [])),
        source=str(getattr(card, "source", "")),
        module_name=str(getattr(card, "module_name", "")),
        lesson_range=str(getattr(card, "lesson_range", "")),
        page_hint=getattr(card, "page_hint", None),
        resource_links=[
            ResourceLinkView(
                kind=str(link.kind),
                title=str(link.title),
                url=getattr(link, "url", None),
            )
            for link in getattr(card, "resource_links", [])
        ],
    )


class GenerateDailyTeachingPlan:
    def __init__(
        self,
        *,
        occurrences: OccurrenceLister,
        get_roster: RosterGetter,
        teaching_focus: TeachingFocusGetter,
        lesson_cards: LessonCardReader,
        video_refs: VideoRefReader,
        criteria: CriterionReader,
    ) -> None:
        self._occurrences = occurrences
        self._get_roster = get_roster
        self._teaching_focus = teaching_focus
        self._lesson_cards = lesson_cards
        self._video_refs = video_refs
        self._criteria = criteria

    async def execute(
        self,
        *,
        coach_id: str,
        on_date: date,
        program_id: str | None,
        program_name: str = "",
    ) -> DailyTeachingPlan:
        occurrences = await self._occurrences.execute(coach_id, on_date)
        cards_by_skill, cards_by_level = await self._card_maps(program_id)

        sessions = await asyncio.gather(
            *[
                self._build_session(occ, program_id, cards_by_skill, cards_by_level)
                for occ in occurrences
            ]
        )
        return DailyTeachingPlan(
            date=on_date.isoformat(),
            program_id=program_id or "",
            program_name=program_name or "",
            pathway_configured=bool(program_id),
            sessions=list(sessions),
        )

    async def build_session_groups(
        self, *, session_id: str, program_id: str | None
    ) -> SessionGroups:
        """Groups + unplaced for a single session (per-session route)."""
        cards_by_skill, cards_by_level = await self._card_maps(program_id)
        return await self._build_groups(session_id, program_id, cards_by_skill, cards_by_level)

    # -- internals ----------------------------------------------------------

    async def _card_maps(
        self, program_id: str | None
    ) -> tuple[dict[str, list[Any]], dict[str, list[Any]]]:
        cards_by_skill: dict[str, list[Any]] = {}
        cards_by_level: dict[str, list[Any]] = {}
        if not program_id:
            return cards_by_skill, cards_by_level
        for card in await self._lesson_cards.list_for_program(program_id):
            if not bool(getattr(card, "is_active", True)):
                continue
            cards_by_level.setdefault(card.level_id, []).append(card)
            for skill_id in getattr(card, "skill_ids", []):
                cards_by_skill.setdefault(skill_id, []).append(card)
        return cards_by_skill, cards_by_level

    async def _build_session(
        self,
        occurrence: Any,
        program_id: str | None,
        cards_by_skill: dict[str, list[Any]],
        cards_by_level: dict[str, list[Any]],
    ) -> SessionTeachingPlan:
        session_id = str(getattr(occurrence, "session_id", ""))
        groups = await self._build_groups(session_id, program_id, cards_by_skill, cards_by_level)
        return SessionTeachingPlan(
            session_id=session_id,
            occurrence_id=getattr(occurrence, "occurrence_id", None),
            title=str(getattr(occurrence, "title", "")),
            location=str(getattr(occurrence, "location", "")),
            start_at=getattr(occurrence, "start_at", None),
            end_at=getattr(occurrence, "end_at", None),
            timezone=getattr(occurrence, "timezone", None),
            groups=groups.groups,
            unplaced=groups.unplaced,
        )

    async def _build_groups(
        self,
        session_id: str,
        program_id: str | None,
        cards_by_skill: dict[str, list[Any]],
        cards_by_level: dict[str, list[Any]],
    ) -> SessionGroups:
        roster = await self._get_roster.execute(session_id)

        if not program_id:
            return SessionGroups(
                groups=[],
                unplaced=[
                    UnplacedStudent(student_id=str(e.student_id), student_name=str(e.full_name))
                    for e in roster
                ],
            )

        students_arg = [(str(e.student_id), str(e.full_name)) for e in roster]
        focus = await self._teaching_focus.for_students(students_arg, program_id)

        groups = await asyncio.gather(
            *[self._enrich_group(g, cards_by_skill, cards_by_level) for g in focus.groups]
        )
        unplaced = [
            UnplacedStudent(student_id=u.student_id, student_name=u.student_name)
            for u in focus.unplaced
        ]
        return SessionGroups(groups=list(groups), unplaced=unplaced)

    async def _enrich_group(
        self,
        group: Any,
        cards_by_skill: dict[str, list[Any]],
        cards_by_level: dict[str, list[Any]],
    ) -> LevelTeachingGroup:
        level_id = group.level_id

        level_videos = await self._video_refs.list_for_level(level_id)
        level_youtube = [VideoLink(title=str(v.title), url=str(v.url)) for v in level_videos]

        next_skill_ids = [s.next_skill.skill_id for s in group.students if s.next_skill]
        distinct_skill_ids = list(dict.fromkeys(next_skill_ids))

        videos_by_skill: dict[str, list[VideoLink]] = {}
        if distinct_skill_ids:
            for ref in await self._video_refs.list_for_skills(distinct_skill_ids):
                videos_by_skill.setdefault(str(ref.skill_id), []).append(
                    VideoLink(title=str(ref.title), url=str(ref.url))
                )

        criteria_by_skill: dict[str, list[str]] = {}
        if distinct_skill_ids:
            crit_lists = await asyncio.gather(
                *[self._criteria.list_for_skill(sid) for sid in distinct_skill_ids]
            )
            for skill_id, crits in zip(distinct_skill_ids, crit_lists, strict=False):
                criteria_by_skill[skill_id] = [str(c.description) for c in crits]

        lesson_card = self._pick_group_card(
            level_id, next_skill_ids, cards_by_skill, cards_by_level
        )

        students: list[StudentFocusView] = []
        for student in group.students:
            next_skill_view: NextSkillView | None = None
            if student.next_skill is not None:
                sk = student.next_skill
                next_skill_view = NextSkillView(
                    skill_id=sk.skill_id,
                    name=sk.name,
                    sequence=sk.sequence,
                    level_id=sk.level_id,
                    status=sk.status,
                    is_review=sk.is_review,
                    criteria=criteria_by_skill.get(sk.skill_id, []),
                    youtube_links=videos_by_skill.get(sk.skill_id, []),
                )
            students.append(
                StudentFocusView(
                    student_id=student.student_id,
                    student_name=student.student_name,
                    next_skill=next_skill_view,
                    focus=student.focus,
                )
            )

        return LevelTeachingGroup(
            level_id=level_id,
            level_name=group.level_name,
            level_sequence=group.level_sequence,
            youtube_links=level_youtube,
            lesson_card=lesson_card,
            students=students,
        )

    @staticmethod
    def _pick_group_card(
        level_id: str,
        next_skill_ids: list[str],
        cards_by_skill: dict[str, list[Any]],
        cards_by_level: dict[str, list[Any]],
    ) -> LessonCardView | None:
        # No next skills (e.g. everyone is ready for level-up) → no card.
        if not next_skill_ids:
            return None

        skill_cards: list[Any] = []
        seen: set[str] = set()
        for skill_id in next_skill_ids:
            for card in cards_by_skill.get(skill_id, []):
                if card.card_id not in seen:
                    seen.add(card.card_id)
                    skill_cards.append(card)

        candidates = skill_cards or cards_by_level.get(level_id, [])
        if not candidates:
            return None
        chosen = min(candidates, key=lambda c: (int(c.display_order), int(c.lesson_number)))
        return _card_view(chosen)
