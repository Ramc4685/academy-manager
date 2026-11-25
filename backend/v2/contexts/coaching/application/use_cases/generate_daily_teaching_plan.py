"""Use case: build the coach's daily teaching plan.

Cross-context orchestrator (coaching application layer). It composes, with no
new write paths:

* ``ListCoachOccurrencesForDate`` — the coach's sessions for a date,
* ``GetOccurrenceRoster`` — who is in the room for each class: make-up and
  trial children included, children on hold or with an absence notice left
  out (``GetSessionRoster``, the standing roster, when no occurrence roster
  is wired or for the per-session route),
* ``GetTeachingFocus`` (student_progress) — the next skill per student,
* curriculum lesson cards + level/skill YouTube refs + skill criteria,
* this batch's earlier class recaps — what each level group actually worked
  on — so each group's drill rotates from real delivery,

into the *Today's Teaching Plan* DTO (plan section 4). Pathway truth lives in
student_progress; teaching content lives in curriculum — nothing is duplicated
here. When no pathway/program is configured the plan still lists the coach's
sessions with every roster student ``unplaced`` and ``pathway_configured`` false
(never a 5xx).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, time
from typing import Any, Protocol

from pydantic import BaseModel, Field

from backend.v2.shared.time.mongo import ensure_utc

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

    async def execute_for_academy(self, on_date: date) -> list[Any]: ...


class RosterGetter(Protocol):
    async def execute(self, session_id: str) -> list[Any]: ...


class OccurrenceRosterGetter(Protocol):
    async def execute(self, *, session_id: str, occurrence_id: str) -> list[Any]: ...


def _in_the_room(row: Any) -> bool:
    if getattr(row, "expected_absence", False):
        return False
    # One-time (make-up / trial) rows have no enrollment status; an enrollment
    # row counts only while active (not held, not departed).
    return getattr(row, "entry_source", "enrollment") != "enrollment" or row.status == "active"


class TeachingFocusGetter(Protocol):
    async def for_students(self, students: list[tuple[str, str]], program_id: str) -> Any: ...


class LessonCardReader(Protocol):
    async def list_for_program(self, program_id: str) -> list[Any]: ...


class VideoRefReader(Protocol):
    async def list_for_level(self, level_id: str) -> list[Any]: ...
    async def list_for_skills(self, skill_ids: list[str]) -> list[Any]: ...


class CriterionReader(Protocol):
    async def list_for_skill(self, skill_id: str) -> list[Any]: ...


class RecapHistoryReader(Protocol):
    """Earlier class recaps of one batch, newest first."""

    async def list_for_session_before(
        self, session_id: str, *, before: datetime, limit: int
    ) -> list[Any]: ...


class LevelReader(Protocol):
    async def list_for_program(self, program_id: str) -> list[Any]: ...


#: Recaps read per batch to rank a group's drills (about a term of weekly classes).
HISTORY_DEPTH = 20


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


class StudentVariation(BaseModel):
    """A child in the group whose own next skill the drill does not cover."""

    model_config = {"frozen": True}

    student_id: str
    student_name: str
    skill_id: str
    skill_name: str


class TeachingAssignment(BaseModel):
    model_config = {"frozen": True}

    card: LessonCardView
    #: The first teaching point (or the goal) to say out loud.
    cue: str | None = None
    #: Children of the group whose next skill this drill covers.
    need_count: int = 0
    #: Start of the class at which this batch's group last worked on one of
    #: the drill's skills (an instant: render it in the session's timezone);
    #: None when never (or when there is no delivery history).
    last_taught_at: datetime | None = None
    #: Every drill for the group was just delivered: a deliberate repeat.
    is_repeat: bool = False
    variations: list[StudentVariation] = Field(default_factory=list)


class LevelTeachingGroup(BaseModel):
    model_config = {"frozen": True}

    level_id: str
    level_name: str
    level_sequence: int
    youtube_links: list[VideoLink] = Field(default_factory=list)
    #: The assignment's card (kept for older callers).
    lesson_card: LessonCardView | None = None
    students: list[StudentFocusView] = Field(default_factory=list)
    #: A recap of this batch recorded what this group worked on.
    history_known: bool = False
    assignment: TeachingAssignment | None = None
    #: For a group above the first level: a drill from the level below.
    reinforcement: TeachingAssignment | None = None


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
        occurrence_roster: OccurrenceRosterGetter | None = None,
        recap_history: RecapHistoryReader | None = None,
        levels: LevelReader | None = None,
    ) -> None:
        self._recap_history = recap_history
        self._levels = levels
        self._occurrence_roster = occurrence_roster
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
        academy_wide: bool = False,
    ) -> DailyTeachingPlan:
        # #1044: a coach supervisor plans the same academy-wide class set
        # Today shows them; an ordinary coach keeps assignment scope.
        occurrences = (
            await self._occurrences.execute_for_academy(on_date)
            if academy_wide
            else await self._occurrences.execute(coach_id, on_date)
        )
        cards_by_skill, cards_by_level = await self._card_maps(program_id)
        catalog = _Catalog(cards_by_skill, cards_by_level, await self._level_sequences(program_id))
        day_start = datetime.combine(on_date, time.min, tzinfo=UTC)

        sessions = await asyncio.gather(
            *[self._build_session(occ, program_id, catalog, day_start) for occ in occurrences]
        )
        return DailyTeachingPlan(
            date=on_date.isoformat(),
            program_id=program_id or "",
            program_name=program_name or "",
            pathway_configured=bool(program_id),
            sessions=list(sessions),
        )

    async def build_session_groups(
        self, *, session_id: str, program_id: str | None, before: datetime | None = None
    ) -> SessionGroups:
        """Groups + unplaced for a single session (per-session route). History
        stops at ``before`` (the class's start), else now."""
        cards_by_skill, cards_by_level = await self._card_maps(program_id)
        catalog = _Catalog(cards_by_skill, cards_by_level, await self._level_sequences(program_id))
        cutoff = ensure_utc(before) if before is not None else datetime.now(UTC)
        return await self._build_groups(session_id, program_id, catalog, cutoff)

    # -- internals ----------------------------------------------------------

    async def _level_sequences(self, program_id: str | None) -> dict[str, int]:
        if not program_id or self._levels is None:
            return {}
        return {
            str(level.level_id): int(level.sequence)
            for level in await self._levels.list_for_program(program_id)  # active only
        }

    async def _history(self, session_id: str, before: datetime) -> list[Any]:
        if self._recap_history is None or not session_id:
            return []
        return await self._recap_history.list_for_session_before(
            session_id, before=before, limit=HISTORY_DEPTH
        )

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
        catalog: _Catalog,
        day_start: datetime,
    ) -> SessionTeachingPlan:
        session_id = str(getattr(occurrence, "session_id", ""))
        occurrence_id = getattr(occurrence, "occurrence_id", None)
        roster = None
        if self._occurrence_roster is not None and occurrence_id:
            rows = await self._occurrence_roster.execute(
                session_id=str(getattr(occurrence, "roster_session_id", None) or session_id),
                occurrence_id=str(occurrence_id),
            )
            roster = [r for r in rows if _in_the_room(r)]
        starts = getattr(occurrence, "start_at", None)
        before = ensure_utc(starts) if isinstance(starts, datetime) else day_start
        groups = await self._build_groups(session_id, program_id, catalog, before, roster=roster)
        return SessionTeachingPlan(
            session_id=session_id,
            occurrence_id=occurrence_id,
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
        catalog: _Catalog,
        before: datetime,
        *,
        roster: list[Any] | None = None,
    ) -> SessionGroups:
        if roster is None:
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

        history = await self._history(session_id, before)
        groups = await asyncio.gather(
            *[self._enrich_group(g, catalog, history) for g in focus.groups]
        )
        unplaced = [
            UnplacedStudent(student_id=u.student_id, student_name=u.student_name)
            for u in focus.unplaced
        ]
        return SessionGroups(groups=list(groups), unplaced=unplaced)

    async def _enrich_group(
        self, group: Any, catalog: _Catalog, history: list[Any]
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

        delivered = _delivered(history, level_id)
        main_cards = _dedupe(
            [c for sid in next_skill_ids for c in catalog.by_skill.get(sid, [])]
            + catalog.by_level.get(level_id, [])
        )
        assignment = _assign(main_cards, delivered, group.students) if next_skill_ids else None
        lower = catalog.level_below(level_id, int(group.level_sequence))
        reinforcement = (
            _assign(catalog.by_level.get(lower, []), delivered, group.students)
            if lower and next_skill_ids
            else None
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
            lesson_card=assignment.card if assignment else None,
            students=students,
            history_known=bool(delivered),
            assignment=assignment,
            reinforcement=reinforcement,
        )


# ---------------------------------------------------------------------------
# Drill rotation (pure: the same inputs always give the same plan)
# ---------------------------------------------------------------------------


class _Catalog:
    def __init__(
        self,
        by_skill: dict[str, list[Any]],
        by_level: dict[str, list[Any]],
        sequences: dict[str, int],
    ) -> None:
        self.by_skill = by_skill
        self.by_level = by_level
        self._sequences = sequences

    def level_below(self, level_id: str, sequence: int) -> str | None:
        """The nearest active level below this one that has drills."""
        lower = [
            (seq, lid)
            for lid, seq in self._sequences.items()
            if seq < sequence and lid != level_id and self.by_level.get(lid)
        ]
        return max(lower)[1] if lower else None


def _delivered(history: list[Any], level_id: str) -> list[tuple[datetime, tuple[str, ...]]]:
    """``(class start, skills)`` this group worked on, newest first."""
    out: list[tuple[datetime, tuple[str, ...]]] = []
    for recap in history:
        for row in getattr(recap, "group_lessons", ()):
            if row.level_id == level_id:
                out.append((ensure_utc(recap.class_starts_at), tuple(row.skill_ids)))
    return out


def _dedupe(cards: list[Any]) -> list[Any]:
    seen: dict[str, Any] = {}
    for card in cards:
        seen.setdefault(str(card.card_id), card)
    return list(seen.values())


def _assign(
    cards: list[Any], delivered: list[tuple[datetime, tuple[str, ...]]], students: list[Any]
) -> TeachingAssignment | None:
    """Rank the group's drills: skip one that adds nothing to the last lesson
    (unless no other drill is for anyone in the group), then most children
    still needing it, then least recently taught (never first), then catalog
    order and id. A skipped drill picked anyway is a deliberate repeat."""
    if not cards:
        return None
    last_taught: dict[str, datetime] = {}
    for on, skills in delivered:  # newest first: keep the first date seen
        for sid in skills:
            last_taught.setdefault(sid, on)
    previous = set(delivered[0][1]) if delivered else set()
    needs = [s.next_skill.skill_id for s in students if s.next_skill is not None]

    def recency(card: Any) -> datetime | None:
        dates = [last_taught[sid] for sid in card.skill_ids if sid in last_taught]
        return max(dates) if dates else None

    def need(card: Any) -> int:
        return sum(1 for sid in needs if sid in set(card.skill_ids))

    def rank(card: Any) -> tuple[Any, ...]:
        last = recency(card)
        return (
            -need(card),
            last is not None,
            last or datetime.min.replace(tzinfo=UTC),
            int(card.display_order),
            int(card.lesson_number),
            str(card.card_id),
        )

    fresh = [c for c in cards if not (c.skill_ids and set(c.skill_ids) <= previous)]
    # Moving on to a drill nobody in the group needs is worse than a repeat.
    pool = fresh if any(need(c) for c in fresh) or not any(need(c) for c in cards) else cards
    chosen = min(pool or cards, key=rank)
    covered = set(chosen.skill_ids)
    last = recency(chosen)
    points = list(getattr(chosen, "teaching_points", []))
    return TeachingAssignment(
        card=_card_view(chosen),
        cue=points[0] if points else (str(getattr(chosen, "goal_summary", "")) or None),
        need_count=sum(1 for sid in needs if sid in covered),
        last_taught_at=last,
        is_repeat=chosen not in fresh,
        variations=[
            StudentVariation(
                student_id=s.student_id,
                student_name=s.student_name,
                skill_id=s.next_skill.skill_id,
                skill_name=s.next_skill.name,
            )
            for s in students
            if s.next_skill is not None and s.next_skill.skill_id not in covered
        ],
    )
