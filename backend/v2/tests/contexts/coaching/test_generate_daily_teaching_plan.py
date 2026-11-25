"""Use-case tests for GenerateDailyTeachingPlan (fake deps, no Mongo)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest
from backend.v2.contexts.coaching.application.use_cases.generate_daily_teaching_plan import (
    GenerateDailyTeachingPlan,
)
from backend.v2.contexts.student_progress.application.use_cases.get_teaching_focus import (
    GetTeachingFocus,
)
from backend.v2.contexts.student_progress.domain.models import (
    StudentLevelProgress,
    StudentSkillProgress,
)

NOW = datetime(2026, 6, 11, 9, 0, tzinfo=UTC)
ON_DATE = date(2026, 6, 11)
PROGRAM_ID = "prog-001"
PROGRAM_NAME = "Badminton Skill Pathway"
LEVEL_1 = "level-001"
LEVEL_2 = "level-002"
COACH_ID = "coach-001"
SESSION_ID = "session-001"


# ---------------------------------------------------------------------------
# Fakes for the student_progress repos (so we use the real GetTeachingFocus)
# ---------------------------------------------------------------------------


def _level_progress(student_id: str, level_id: str) -> StudentLevelProgress:
    return StudentLevelProgress(
        progress_id=f"lp-{student_id}",
        academy_id="test-academy",
        student_id=student_id,
        program_id=PROGRAM_ID,
        level_id=level_id,
        status="active",
        started_at=NOW,
        created_at=NOW,
    )


def _skill_progress(student_id: str, skill_id: str, status: str) -> StudentSkillProgress:
    return StudentSkillProgress(
        skill_progress_id=f"sp-{student_id}-{skill_id}",
        academy_id="test-academy",
        student_id=student_id,
        skill_id=skill_id,
        level_id=LEVEL_1,
        program_id=PROGRAM_ID,
        status=status,  # type: ignore[arg-type]
        last_updated_at=NOW,
        last_updated_by=COACH_ID,
    )


class _FakeLevelProgressRepo:
    def __init__(self, rows: list[StudentLevelProgress]) -> None:
        self._rows = rows

    async def get_active(self, student_id: str, program_id: str) -> StudentLevelProgress | None:
        for row in self._rows:
            if row.student_id == student_id and row.program_id == program_id:
                return row
        return None


class _FakeSkillProgressRepo:
    def __init__(self, rows: list[StudentSkillProgress]) -> None:
        self._rows = rows

    async def list_for_students(
        self, student_ids: list[str], level_id: str
    ) -> list[StudentSkillProgress]:
        return [r for r in self._rows if r.student_id in student_ids and r.level_id == level_id]


class _FakeSkillLookup:
    def __init__(self) -> None:
        self._levels = {
            LEVEL_1: SimpleNamespace(level_id=LEVEL_1, name="Grip and Control", sequence=1),
            LEVEL_2: SimpleNamespace(level_id=LEVEL_2, name="Rallying", sequence=2),
        }
        self._skills = {
            LEVEL_1: [
                SimpleNamespace(
                    skill_id="sk-a", name="Forehand grip", sequence=1, is_required=True
                ),
                SimpleNamespace(
                    skill_id="sk-b", name="Backhand grip", sequence=2, is_required=True
                ),
            ],
            LEVEL_2: [
                SimpleNamespace(skill_id="sk-c", name="Clear", sequence=1, is_required=True),
            ],
        }

    async def get_level(self, level_id: str) -> object | None:
        return self._levels.get(level_id)

    async def list_skills_for_level(self, level_id: str) -> list[object]:
        return self._skills.get(level_id, [])


# ---------------------------------------------------------------------------
# Fakes for occurrences / roster / curriculum readers
# ---------------------------------------------------------------------------


class _FakeOccurrences:
    def __init__(self, occurrences: list[object]) -> None:
        self._occurrences = occurrences

    async def execute(self, coach_id: str, on_date: date) -> list[object]:
        return list(self._occurrences)


class _FakeRoster:
    def __init__(self, roster_by_session: dict[str, list[object]]) -> None:
        self._roster = roster_by_session

    async def execute(self, session_id: str) -> list[object]:
        return self._roster.get(session_id, [])


class _FakeLessonCards:
    def __init__(self, cards: list[object]) -> None:
        self._cards = cards

    async def list_for_program(self, program_id: str) -> list[object]:
        return [c for c in self._cards if c.program_id == program_id]


class _FakeVideoRefs:
    def __init__(
        self, level_videos: dict[str, list[object]], skill_videos: dict[str, list[object]]
    ) -> None:
        self._level = level_videos
        self._skill = skill_videos

    async def list_for_level(self, level_id: str) -> list[object]:
        return self._level.get(level_id, [])

    async def list_for_skills(self, skill_ids: list[str]) -> list[object]:
        out: list[object] = []
        for sid in skill_ids:
            out.extend(self._skill.get(sid, []))
        return out


class _FakeCriteria:
    def __init__(self, by_skill: dict[str, list[str]]) -> None:
        self._by_skill = by_skill

    async def list_for_skill(self, skill_id: str) -> list[object]:
        return [SimpleNamespace(description=d) for d in self._by_skill.get(skill_id, [])]


def _occurrence(session_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        occurrence_id=f"occ-{session_id}",
        session_id=session_id,
        roster_session_id=session_id,
        title="U11 Beginners",
        location="Court 2",
        start_at=NOW,
        end_at=NOW,
        timezone="America/Chicago",
    )


def _roster_entry(student_id: str, name: str) -> SimpleNamespace:
    return SimpleNamespace(student_id=student_id, full_name=name, status="active")


def _card(
    card_id: str,
    *,
    level_id: str,
    skill_ids: list[str],
    lesson_number: int,
    display_order: int,
    is_active: bool = True,
) -> SimpleNamespace:
    return SimpleNamespace(
        card_id=card_id,
        program_id=PROGRAM_ID,
        level_id=level_id,
        skill_ids=skill_ids,
        slug=f"slug-{card_id}",
        lesson_number=lesson_number,
        title=f"Lesson {lesson_number}",
        goal_summary="Develop grip control",
        teaching_points=["Point A"],
        equipment=["Racket"],
        activity_summary="Drill",
        safety_notes=["Stay spaced"],
        source="BWF_SHUTTLE_TIME",
        module_name="Starter Lessons",
        lesson_range="1-2",
        page_hint="p.9-15",
        resource_links=[
            SimpleNamespace(kind="YOUTUBE", title="Grip demo", url="https://yt/x"),
            SimpleNamespace(kind="PDF_REFERENCE", title="Shuttle Time", url=None),
        ],
        content_hash="h",
        display_order=display_order,
        is_active=is_active,
    )


def _video(skill_id: str | None, level_id: str, title: str, url: str) -> SimpleNamespace:
    return SimpleNamespace(skill_id=skill_id, level_id=level_id, title=title, url=url)


def _make_use_case(
    *,
    occurrences: list[object],
    roster_by_session: dict[str, list[object]],
    level_rows: list[StudentLevelProgress],
    skill_rows: list[StudentSkillProgress],
    cards: list[object] | None = None,
    level_videos: dict[str, list[object]] | None = None,
    skill_videos: dict[str, list[object]] | None = None,
    criteria: dict[str, list[str]] | None = None,
    recaps: list[object] | None = None,
) -> GenerateDailyTeachingPlan:
    teaching_focus = GetTeachingFocus(
        level_progress=_FakeLevelProgressRepo(level_rows),
        skill_progress=_FakeSkillProgressRepo(skill_rows),
        skill_lookup=_FakeSkillLookup(),
    )
    return GenerateDailyTeachingPlan(
        occurrences=_FakeOccurrences(occurrences),
        get_roster=_FakeRoster(roster_by_session),
        teaching_focus=teaching_focus,
        lesson_cards=_FakeLessonCards(cards or []),
        video_refs=_FakeVideoRefs(level_videos or {}, skill_videos or {}),
        criteria=_FakeCriteria(criteria or {}),
        recap_history=_FakeRecapHistory(recaps or []),
        levels=_FakeLevels(),
    )


class _FakeRecapHistory:
    """Mirrors the Mongo read: this batch only, strictly before, newest first."""

    def __init__(self, recaps: list[object]) -> None:
        self._recaps = recaps
        self.calls = 0

    async def list_for_session_before(
        self, session_id: str, *, before: datetime, limit: int
    ) -> list[object]:
        self.calls += 1
        rows = [
            r
            for r in self._recaps
            if r.session_id == session_id and r.class_starts_at < before  # type: ignore[attr-defined]
        ]
        rows.sort(key=lambda r: r.class_starts_at, reverse=True)  # type: ignore[attr-defined]
        return rows[:limit]


class _FakeLevels:
    async def list_for_program(self, program_id: str) -> list[object]:
        return [
            SimpleNamespace(level_id=LEVEL_1, sequence=1, is_active=True),
            SimpleNamespace(level_id=LEVEL_2, sequence=2, is_active=True),
        ]


def _recap(day: int, lessons: dict[str, list[str]], session_id: str = SESSION_ID) -> object:
    return SimpleNamespace(
        session_id=session_id,
        class_starts_at=datetime(2026, 6, day, 9, 0, tzinfo=UTC),
        group_lessons=[
            SimpleNamespace(level_id=lid, skill_ids=tuple(sids)) for lid, sids in lessons.items()
        ],
    )


@pytest.mark.asyncio
async def test_plan_groups_students_by_level_with_lesson_card_and_focus() -> None:
    use_case = _make_use_case(
        occurrences=[_occurrence(SESSION_ID)],
        roster_by_session={SESSION_ID: [_roster_entry("stu-1", "Alice")]},
        level_rows=[_level_progress("stu-1", LEVEL_1)],
        skill_rows=[],  # → first required skill sk-a, NOT_STARTED
        cards=[
            _card("card-1", level_id=LEVEL_1, skill_ids=["sk-a"], lesson_number=1, display_order=1)
        ],
        level_videos={LEVEL_1: [_video(None, LEVEL_1, "Level 1 overview", "https://yt/lvl")]},
        skill_videos={"sk-a": [_video("sk-a", LEVEL_1, "Grip drill", "https://yt/sk")]},
        criteria={"sk-a": ["Hold V-grip", "Relaxed wrist"]},
    )

    plan = await use_case.execute(
        coach_id=COACH_ID, on_date=ON_DATE, program_id=PROGRAM_ID, program_name=PROGRAM_NAME
    )

    assert plan.date == "2026-06-11"
    assert plan.pathway_configured is True
    assert len(plan.sessions) == 1
    session = plan.sessions[0]
    assert session.session_id == SESSION_ID
    assert session.occurrence_id == f"occ-{SESSION_ID}"
    assert session.timezone == "America/Chicago"

    assert len(session.groups) == 1
    group = session.groups[0]
    assert group.level_id == LEVEL_1
    assert group.level_name == "Grip and Control"
    assert [v.url for v in group.youtube_links] == ["https://yt/lvl"]

    assert group.lesson_card is not None
    assert group.lesson_card.lesson_number == 1
    assert [rl.kind for rl in group.lesson_card.resource_links] == ["YOUTUBE", "PDF_REFERENCE"]

    student = group.students[0]
    assert student.focus == "practice"
    assert student.next_skill is not None
    assert student.next_skill.skill_id == "sk-a"
    assert student.next_skill.criteria == ["Hold V-grip", "Relaxed wrist"]
    assert [v.url for v in student.next_skill.youtube_links] == ["https://yt/sk"]


@pytest.mark.asyncio
async def test_ready_for_level_up_group_has_null_card() -> None:
    use_case = _make_use_case(
        occurrences=[_occurrence(SESSION_ID)],
        roster_by_session={SESSION_ID: [_roster_entry("stu-1", "Alice")]},
        level_rows=[_level_progress("stu-1", LEVEL_1)],
        skill_rows=[
            _skill_progress("stu-1", "sk-a", "PASSED"),
            _skill_progress("stu-1", "sk-b", "PASSED"),
        ],
        cards=[
            _card("card-1", level_id=LEVEL_1, skill_ids=["sk-a"], lesson_number=1, display_order=1)
        ],
    )
    plan = await use_case.execute(
        coach_id=COACH_ID, on_date=ON_DATE, program_id=PROGRAM_ID, program_name=PROGRAM_NAME
    )
    group = plan.sessions[0].groups[0]
    assert group.students[0].focus == "ready_for_level_up"
    assert group.students[0].next_skill is None
    assert group.lesson_card is None


@pytest.mark.asyncio
async def test_card_falls_back_to_level_card_when_skill_has_no_card() -> None:
    """Next skill is sk-a (no card maps to it) → use the level's card."""
    use_case = _make_use_case(
        occurrences=[_occurrence(SESSION_ID)],
        roster_by_session={SESSION_ID: [_roster_entry("stu-1", "Alice")]},
        level_rows=[_level_progress("stu-1", LEVEL_1)],
        skill_rows=[],  # next skill = sk-a
        cards=[
            # card maps only to sk-b, but lives on LEVEL_1
            _card("card-b", level_id=LEVEL_1, skill_ids=["sk-b"], lesson_number=2, display_order=2),
        ],
    )
    plan = await use_case.execute(
        coach_id=COACH_ID, on_date=ON_DATE, program_id=PROGRAM_ID, program_name=PROGRAM_NAME
    )
    group = plan.sessions[0].groups[0]
    assert group.lesson_card is not None
    assert group.lesson_card.card_id == "card-b"


@pytest.mark.asyncio
async def test_empty_day_returns_no_sessions() -> None:
    use_case = _make_use_case(
        occurrences=[],
        roster_by_session={},
        level_rows=[],
        skill_rows=[],
    )
    plan = await use_case.execute(
        coach_id=COACH_ID, on_date=ON_DATE, program_id=PROGRAM_ID, program_name=PROGRAM_NAME
    )
    assert plan.sessions == []
    assert plan.pathway_configured is True


@pytest.mark.asyncio
async def test_no_program_marks_pathway_unconfigured_and_all_unplaced() -> None:
    use_case = _make_use_case(
        occurrences=[_occurrence(SESSION_ID)],
        roster_by_session={SESSION_ID: [_roster_entry("stu-1", "Alice")]},
        level_rows=[_level_progress("stu-1", LEVEL_1)],
        skill_rows=[],
    )
    plan = await use_case.execute(
        coach_id=COACH_ID, on_date=ON_DATE, program_id=None, program_name=""
    )
    assert plan.pathway_configured is False
    session = plan.sessions[0]
    assert session.groups == []
    assert [u.student_id for u in session.unplaced] == ["stu-1"]


@pytest.mark.asyncio
async def test_build_session_groups_for_single_session() -> None:
    use_case = _make_use_case(
        occurrences=[],
        roster_by_session={SESSION_ID: [_roster_entry("stu-1", "Alice")]},
        level_rows=[_level_progress("stu-1", LEVEL_1)],
        skill_rows=[],
        cards=[
            _card("card-1", level_id=LEVEL_1, skill_ids=["sk-a"], lesson_number=1, display_order=1)
        ],
    )
    groups = await use_case.build_session_groups(session_id=SESSION_ID, program_id=PROGRAM_ID)
    assert len(groups.groups) == 1
    assert groups.groups[0].students[0].next_skill.skill_id == "sk-a"
    assert groups.unplaced == []


class _FakeOccurrenceRoster:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows
        self.calls: list[tuple[str, str]] = []

    async def execute(self, *, session_id: str, occurrence_id: str) -> list[object]:
        self.calls.append((session_id, occurrence_id))
        return self._rows


@pytest.mark.asyncio
async def test_plan_uses_the_days_roster_not_the_standing_one() -> None:
    """Make-up and trial children are planned for; held children and those
    with an absence notice are not."""
    occurrence_roster = _FakeOccurrenceRoster(
        [
            SimpleNamespace(
                student_id="stu-1",
                full_name="Alice",
                status="active",
                entry_source="enrollment",
                expected_absence=False,
            ),
            SimpleNamespace(
                student_id="stu-held",
                full_name="Hal",
                status="held",
                entry_source="enrollment",
                expected_absence=False,
            ),
            SimpleNamespace(
                student_id="stu-away",
                full_name="Ava",
                status="active",
                entry_source="enrollment",
                expected_absence=True,
            ),
            SimpleNamespace(
                student_id="stu-makeup",
                full_name="Max",
                status=None,
                entry_source="makeup",
                expected_absence=False,
            ),
        ]
    )
    use_case = GenerateDailyTeachingPlan(
        occurrences=_FakeOccurrences([_occurrence(SESSION_ID)]),
        get_roster=_FakeRoster({SESSION_ID: [_roster_entry("stu-standing", "Standing")]}),
        teaching_focus=GetTeachingFocus(
            level_progress=_FakeLevelProgressRepo([]),
            skill_progress=_FakeSkillProgressRepo([]),
            skill_lookup=_FakeSkillLookup(),
        ),
        lesson_cards=_FakeLessonCards([]),
        video_refs=_FakeVideoRefs({}, {}),
        criteria=_FakeCriteria({}),
        occurrence_roster=occurrence_roster,
    )

    plan = await use_case.execute(coach_id=COACH_ID, on_date=ON_DATE, program_id=None)

    assert occurrence_roster.calls == [(SESSION_ID, f"occ-{SESSION_ID}")]
    assert [u.student_id for u in plan.sessions[0].unplaced] == ["stu-1", "stu-makeup"]


# ---------------------------------------------------------------------------
# Drill rotation from this batch's delivery history (skills-first step 5)
# ---------------------------------------------------------------------------

_ROTATION_CARDS = [
    _card("l1-a", level_id=LEVEL_1, skill_ids=["sk-a"], lesson_number=1, display_order=1),
    _card("l1-a2", level_id=LEVEL_1, skill_ids=["sk-a"], lesson_number=2, display_order=2),
    _card("l1-b", level_id=LEVEL_1, skill_ids=["sk-b"], lesson_number=3, display_order=3),
    _card("l2-c", level_id=LEVEL_2, skill_ids=["sk-c"], lesson_number=1, display_order=1),
    _card("l2-c2", level_id=LEVEL_2, skill_ids=["sk-c"], lesson_number=2, display_order=2),
]


def _class_on(day: int) -> SimpleNamespace:
    occ = _occurrence(SESSION_ID)
    occ.start_at = datetime(2026, 6, day, 9, 0, tzinfo=UTC)
    occ.occurrence_id = f"occ-{day}"
    return occ


def _rotation_case(
    day: int, recaps: list[object], *, bo_passed_grip: bool = True
) -> GenerateDailyTeachingPlan:
    return _make_use_case(
        occurrences=[_class_on(day)],
        roster_by_session={
            SESSION_ID: [
                _roster_entry("stu-1", "Alice Fake"),
                _roster_entry("stu-2", "Bo Fake"),
                _roster_entry("stu-3", "Cy Fake"),
            ]
        },
        # Beginners: Alice is on sk-a, Bo (grip passed) on sk-b. Cy rallies on sk-c.
        level_rows=[
            _level_progress("stu-1", LEVEL_1),
            _level_progress("stu-2", LEVEL_1),
            _level_progress("stu-3", LEVEL_2),
        ],
        skill_rows=[_skill_progress("stu-2", "sk-a", "PASSED")] if bo_passed_grip else [],
        cards=_ROTATION_CARDS,
        recaps=recaps,
    )


async def _groups(use_case: GenerateDailyTeachingPlan, day: int, coach: str = COACH_ID) -> dict:
    plan = await use_case.execute(coach_id=coach, on_date=date(2026, 6, day), program_id=PROGRAM_ID)
    return {g.level_id: g for g in plan.sessions[0].groups}


@pytest.mark.asyncio
async def test_two_consecutive_classes_rotate_each_group_and_a_substitute_sees_the_same() -> None:
    day1 = await _groups(_rotation_case(10, []), 10)
    assert day1[LEVEL_1].assignment.card.card_id == "l1-a"
    assert day1[LEVEL_2].assignment.card.card_id == "l2-c"
    assert day1[LEVEL_1].history_known is False

    # The coach recorded what each group worked on in the day-10 recap.
    recaps = [_recap(10, {LEVEL_1: ["sk-a"], LEVEL_2: ["sk-c"]})]
    regular = await _groups(_rotation_case(11, recaps), 11)
    substitute = await _groups(_rotation_case(11, recaps), 11, coach="coach-sub")

    beginners, rallying = regular[LEVEL_1].assignment, regular[LEVEL_2].assignment
    # The grip drills only repeat the last lesson, so the beginners move on to
    # Bo's sk-b drill and Alice is flagged as the variation.
    assert beginners.card.card_id == "l1-b"
    assert beginners.need_count == 1 and beginners.is_repeat is False
    assert [v.student_name for v in beginners.variations] == ["Alice Fake"]
    # The rallying group has only sk-c drills: a deliberate repeat.
    assert rallying.card.card_id == "l2-c"
    assert rallying.is_repeat is True
    assert rallying.last_taught_at == datetime(2026, 6, 10, 9, 0, tzinfo=UTC)
    assert {k: v.model_dump() for k, v in substitute.items()} == {
        k: v.model_dump() for k, v in regular.items()
    }


@pytest.mark.asyncio
async def test_changing_the_delivered_lesson_changes_the_next_pick() -> None:
    after_a = await _groups(_rotation_case(11, [_recap(10, {LEVEL_1: ["sk-b"]})]), 11)
    after_b = await _groups(_rotation_case(11, [_recap(10, {LEVEL_1: ["sk-a"]})]), 11)
    assert after_a[LEVEL_1].assignment.card.card_id == "l1-a"
    assert after_b[LEVEL_1].assignment.card.card_id == "l1-b"


@pytest.mark.asyncio
async def test_unchanged_inputs_give_the_same_plan() -> None:
    recaps = [_recap(8, {LEVEL_1: ["sk-b"]}), _recap(10, {LEVEL_1: ["sk-a"]})]
    first = await _groups(_rotation_case(11, recaps), 11)
    second = await _groups(_rotation_case(11, list(reversed(recaps))), 11)
    assert {k: v.model_dump() for k, v in first.items()} == {
        k: v.model_dump() for k, v in second.items()
    }


@pytest.mark.asyncio
async def test_missing_history_reads_as_unknown_not_as_never_taught_wrongly() -> None:
    groups = await _groups(_rotation_case(11, []), 11)
    beginners = groups[LEVEL_1]
    assert beginners.history_known is False
    assert beginners.assignment.last_taught_at is None
    assert beginners.assignment.is_repeat is False
    # Equal need (one child each): catalog order breaks the tie.
    assert beginners.assignment.card.card_id == "l1-a"
    assert beginners.assignment.need_count == 1
    assert beginners.assignment.cue == "Point A"


@pytest.mark.asyncio
async def test_least_recently_taught_wins_among_equal_need() -> None:
    # l1-a (sk-a) was taught on the 8th; the 10th was sk-b. Both sk-a cards
    # share the date, so catalog order still picks l1-a over l1-a2.
    recaps = [_recap(8, {LEVEL_1: ["sk-a"]}), _recap(10, {LEVEL_1: ["sk-b"]})]
    beginners = (await _groups(_rotation_case(11, recaps), 11))[LEVEL_1].assignment
    assert beginners.card.card_id == "l1-a"
    assert beginners.last_taught_at == datetime(2026, 6, 8, 9, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_an_exhausted_catalog_is_a_deliberate_repeat() -> None:
    recaps = [_recap(10, {LEVEL_2: ["sk-c"]})]
    rallying = (await _groups(_rotation_case(11, recaps), 11))[LEVEL_2]
    assert rallying.assignment.is_repeat is True
    assert rallying.assignment.card.card_id == "l2-c"
    assert rallying.assignment.last_taught_at == datetime(2026, 6, 10, 9, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_a_drill_nobody_needs_never_replaces_a_repeat() -> None:
    # Both beginners still need sk-a, done last class; the sk-b drill would
    # be for nobody, so the plan repeats a grip drill on purpose.
    recaps = [_recap(10, {LEVEL_1: ["sk-a"]})]
    case = _rotation_case(11, recaps, bo_passed_grip=False)
    beginners = (await _groups(case, 11))[LEVEL_1].assignment
    assert beginners.card.card_id == "l1-a"
    assert beginners.need_count == 2
    assert beginners.is_repeat is True


@pytest.mark.asyncio
async def test_an_advanced_station_never_excludes_a_beginner_drill() -> None:
    # The rallying group warmed up on the beginners' grip skill.
    recaps = [_recap(10, {LEVEL_2: ["sk-a"]})]
    beginners = (await _groups(_rotation_case(11, recaps), 11))[LEVEL_1]
    assert beginners.history_known is False
    assert beginners.assignment.card.card_id == "l1-a"
    assert beginners.assignment.is_repeat is False


@pytest.mark.asyncio
async def test_a_higher_group_gets_a_reinforcement_drill_from_the_level_below() -> None:
    groups = await _groups(_rotation_case(11, []), 11)
    assert groups[LEVEL_1].reinforcement is None
    reinforcement = groups[LEVEL_2].reinforcement
    assert reinforcement is not None
    assert reinforcement.card.card_id in {"l1-a", "l1-a2", "l1-b"}
    assert reinforcement.need_count == 0


@pytest.mark.asyncio
async def test_history_is_read_once_per_class_and_never_includes_the_class_itself() -> None:
    use_case = _rotation_case(11, [_recap(11, {LEVEL_1: ["sk-a"]})])
    beginners = (await _groups(use_case, 11))[LEVEL_1]
    assert beginners.history_known is False
    assert use_case._recap_history.calls == 1  # type: ignore[union-attr]
