"""Class recap repositories over a real mongod (migration 0243 applied).

The claims the fakes in tests/unit/test_class_recap.py rely on: one recap per
occurrence (a second first write is refused by the unique index), the
revision compare-and-set refuses a stale write, per-child practice round
trips, reports are insert-only per academy, the owner's handoff list holds
only unresolved owner reports, and the parent read sees only present/late
marks. Tenancy: another academy's rows are invisible.
"""

from __future__ import annotations

import importlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from backend.v2.composition.class_recap import (
    ActiveLevelGroups,
    CurriculumRecapSkills,
    SkillProgressPasses,
)
from backend.v2.contexts.coaching.domain.class_recap import (
    ChildPass,
    ChildPractice,
    ClassRecap,
    ClassReport,
    GroupLesson,
)
from backend.v2.contexts.coaching.infrastructure.mongo_class_recap_repo import (
    MongoClassRecapRepository,
    MongoClassReportRepository,
    StudentConfirmedAttendance,
)
from backend.v2.contexts.curriculum.domain.models import Level
from backend.v2.contexts.curriculum.infrastructure.mongo_level_repo import MongoLevelRepository
from backend.v2.contexts.curriculum.infrastructure.mongo_skill_repo import MongoSkillRepository
from backend.v2.contexts.student_progress.domain.models import StudentLevelProgress
from backend.v2.contexts.student_progress.infrastructure.mongo_level_progress_repo import (
    MongoStudentLevelProgressRepository,
)
from backend.v2.contexts.student_progress.infrastructure.mongo_skill_progress_repo import (
    MongoStudentSkillProgressRepository,
)
from backend.v2.contexts.student_progress.infrastructure.mongo_test_attempt_repo import (
    MongoTestAttemptRepository,
)
from backend.v2.shared.tenancy import tenant_scope

pytestmark = pytest.mark.asyncio

ACADEMY, OTHER = "acad-recap", "acad-other"
NOW = datetime(2026, 11, 18, 20, 0, tzinfo=UTC)


def _recap(revision: int, **kw: Any) -> ClassRecap:
    base: dict[str, Any] = {
        "recap_id": "rc-1",
        "academy_id": ACADEMY,
        "occurrence_id": "occ-1",
        "session_id": "sess-1",
        "class_starts_at": NOW,
        "taught_skill_ids": ("skill-a", "skill-b"),
        "practice": (
            ChildPractice(student_id="maya", skill_ids=("skill-a",)),
            ChildPractice(student_id="leo", skill_ids=("skill-b",)),
        ),
        "revision": revision,
        "updated_by": "coach-1",
        "updated_at": NOW,
    }
    return ClassRecap(**{**base, **kw})


def _report(report_id: str, outcome: str = "sent_to_owner") -> ClassReport:
    return ClassReport(
        report_id=report_id,
        academy_id=ACADEMY,
        occurrence_id="occ-1",
        class_starts_at=NOW,
        author_id="coach-1",
        text="private words",
        submitted_at=NOW,
        outcome=outcome,  # type: ignore[arg-type]
    )


async def test_one_recap_per_occurrence_with_revision_cas(real_db: Any) -> None:
    repo = MongoClassRecapRepository(real_db)
    with tenant_scope(ACADEMY):
        assert await repo.save(_recap(1), expected_revision=0)
        assert not await repo.save(_recap(1, recap_id="rc-dup"), expected_revision=0)
        stored = await repo.get("occ-1")
        assert stored is not None and stored.practiced_by("leo") == ("skill-b",)
        assert await repo.save(_recap(2, practice=()), expected_revision=1)
        assert not await repo.save(_recap(2), expected_revision=1)  # stale
        assert (await repo.get("occ-1")).practice == ()  # type: ignore[union-attr]
        assert [
            r.occurrence_id
            for r in await repo.page_for_occurrences(["occ-1", "x"], before=None, limit=5)
        ] == ["occ-1"]
        # Same start time: the occurrence id breaks the tie, and the cursor
        # resumes strictly after it.
        await repo.save(_recap(1, recap_id="rc-0", occurrence_id="occ-0"), expected_revision=0)
        await repo.save(
            _recap(
                1, recap_id="rc-9", occurrence_id="occ-9", class_starts_at=NOW - timedelta(days=1)
            ),
            expected_revision=0,
        )
        ids = ["occ-0", "occ-1", "occ-9"]
        first = await repo.page_for_occurrences(ids, before=None, limit=2)
        assert [r.occurrence_id for r in first] == ["occ-1", "occ-0"]
        rest = await repo.page_for_occurrences(ids, before=(NOW, "occ-0"), limit=2)
        assert [r.occurrence_id for r in rest] == ["occ-9"]
    with tenant_scope(OTHER):
        assert await repo.get("occ-1") is None
        assert await repo.save(_recap(1, academy_id=OTHER), expected_revision=0)


async def test_settling_passes_keeps_the_revision_and_skips_a_stale_one(real_db: Any) -> None:
    repo = MongoClassRecapRepository(real_db)
    passes = tuple(
        ChildPass(student_id=sid, skill_id="skill-a", added_revision=1) for sid in ("maya", "leo")
    )
    with tenant_scope(ACADEMY):
        assert await repo.save(_recap(1, passes=passes), expected_revision=0)
        await repo.settle_passes("occ-1", revision=1, pairs=[("maya", "skill-a")])
        stored = await repo.get("occ-1")
        assert stored is not None and stored.revision == 1
        assert [p.settled for p in stored.passes] == [True, False]
        await repo.settle_passes("occ-1", revision=0, pairs=[("leo", "skill-a")])  # stale
        assert [p.settled for p in (await repo.get("occ-1")).passes] == [True, False]  # type: ignore[union-attr]


async def test_reports_are_insert_only_and_handoffs_close_once(real_db: Any) -> None:
    repo = MongoClassReportRepository(real_db)
    with tenant_scope(ACADEMY):
        assert await repo.insert(_report("r-1"))
        assert not await repo.insert(_report("r-1"))
        assert await repo.insert(_report("r-2", outcome="applied"))
        assert [r.report_id for r in await repo.list_open_handoffs(limit=10)] == ["r-1"]
        closed = await repo.resolve("r-1", by="owner-1", at=NOW)
        assert closed is not None and closed.resolved_by == "owner-1"
        assert await repo.resolve("r-1", by="owner-1", at=NOW) is None
        assert await repo.list_open_handoffs(limit=10) == []
    with tenant_scope(OTHER):
        assert await repo.get("r-1") is None
        assert await repo.insert(_report("r-1"))  # unique per academy only


async def test_a_report_being_read_is_finished_once_and_hidden_from_handoffs(real_db: Any) -> None:
    repo = MongoClassReportRepository(real_db)
    now = datetime.now(UTC)
    with tenant_scope(ACADEMY):
        live = _report("r-live").model_copy(update={"processing_until": now + timedelta(minutes=5)})
        stale = _report("r-stale").model_copy(
            update={"processing_until": now - timedelta(minutes=1)}
        )
        assert await repo.insert(live) and await repo.insert(stale)
        assert await repo.insert(_report("r-plain"))
        # Live reads are not handoffs; an interrupted one (lease over) is.
        open_ids = {r.report_id for r in await repo.list_open_handoffs(limit=10)}
        assert open_ids == {"r-stale", "r-plain"}
        done = live.model_copy(
            update={"outcome": "applied", "ai_used": True, "applied_revision": 3}
        )
        assert await repo.finish(done)
        assert not await repo.finish(done)  # finished once
        stored = await repo.get("r-live")
        assert stored is not None and stored.processing_until is None
        assert (stored.outcome, stored.applied_revision, stored.text) == (
            "applied",
            3,
            "private words",
        )
        assert not await repo.finish(_report("r-plain"))  # never claimed


async def test_parent_attendance_read_counts_present_and_late_only(real_db: Any) -> None:
    rows = [("occ-1", "present"), ("occ-2", "late"), ("occ-3", "absent"), ("occ-4", "voided")]
    for i, (occurrence_id, status) in enumerate(rows):
        await real_db["attendance"].insert_one(
            {
                "academy_id": ACADEMY,
                "attendance_id": f"a-{i}",
                "occurrence_id": occurrence_id,
                "session_id": "sess-1",
                "student_id": "maya",
                "status": status,
                "marked_by": "coach-1",
                "marked_at": datetime(2026, 11, 1 + i, tzinfo=UTC),
            }
        )
    with tenant_scope(ACADEMY):
        ids = await StudentConfirmedAttendance(real_db).confirmed_occurrence_ids("maya", limit=10)
    assert ids == ["occ-2", "occ-1"]
    with tenant_scope(OTHER):
        assert (
            await StudentConfirmedAttendance(real_db).confirmed_occurrence_ids("maya", limit=10)
            == []
        )


async def test_parent_adapters_read_in_bulk_per_academy_and_skip_silent_passes(
    real_db: Any,
) -> None:
    """Skill names and passes for the parent read come from one tenant-scoped
    query each; a silent placement credit is not a pass."""
    for sequence, (academy, skill_id, active) in enumerate(
        ((ACADEMY, "s-live", True), (ACADEMY, "s-retired", False), (OTHER, "s-other", True)),
        start=1,
    ):
        await real_db["skills"].insert_one(
            {
                "academy_id": academy,
                "skill_id": skill_id,
                "level_id": "lvl-1",
                "program_id": "prog-1",
                "sequence": sequence,
                "name": f"Name {skill_id}",
                "is_active": active,
                "created_at": NOW,
                "updated_at": NOW,
            }
        )
    later = NOW + timedelta(days=7)
    for academy, skill_id, status, silent, passed_at in (
        (ACADEMY, "s-live", "PASSED", False, NOW),
        (ACADEMY, "s-retired", "PASSED", True, NOW),  # placement credit
        (ACADEMY, "s-learning", "LEARNING", False, NOW),
        (ACADEMY, "s-retest", "PASSED", False, later),  # re-earned by a later formal test
        (OTHER, "s-other", "PASSED", False, later),
    ):
        await real_db["student_skill_progress"].insert_one(
            {
                "academy_id": academy,
                "skill_progress_id": f"p-{academy}-{skill_id}",
                "student_id": "maya",
                "skill_id": skill_id,
                "level_id": "lvl-1",
                "program_id": "prog-1",
                "status": status,
                "last_updated_at": passed_at,
                "last_updated_by": "coach-1",
                "silent": silent,
            }
        )
    catalog = CurriculumRecapSkills(
        skills=MongoSkillRepository(real_db), levels=None, resolve_default_program=None
    )
    for academy, attempt_id, skill_id, occ, earned, at in (
        (ACADEMY, "t-1", "s-live", "occ-1", True, NOW),
        (ACADEMY, "t-2", "s-learning", "occ-1", True, NOW),  # pass since taken back
        (ACADEMY, "t-3", "s-live", "occ-2", False, NOW),  # a try, not the pass
        (ACADEMY, "t-6", "s-retest", "occ-1", True, NOW),  # lost, then re-earned elsewhere
        (OTHER, "t-4", "s-other", "occ-1", True, NOW),
        (OTHER, "t-5", "s-other", "occ-3", True, later),  # taken back, re-earned later
    ):
        await real_db["test_attempts"].insert_one(
            {
                "academy_id": academy,
                "attempt_id": attempt_id,
                "student_id": "maya",
                "skill_id": skill_id,
                "occurrence_id": occ,
                "observation_key": f"{occ}:maya:{skill_id}",
                "effects_done_at": at,
                "earned_pass": earned,
                "level_id": "lvl-1",
                "program_id": "prog-1",
                "coach_id": "coach-1",
                "scoring_type": "COACH_APPROVAL",
                "attempts_count": 1,
                "success_count": 1,
                "score": 100.0,
                "passed": True,
                "tested_at": at,
            }
        )
    passes = SkillProgressPasses(
        MongoStudentSkillProgressRepository(real_db), MongoTestAttemptRepository(real_db)
    )
    ids = ["s-live", "s-retired", "s-other", "s-learning"]
    with tenant_scope(ACADEMY):
        assert await catalog.names(ids, active_only=False) == {
            "s-live": "Name s-live",
            "s-retired": "Name s-retired",
        }
        assert await catalog.names(ids, active_only=True) == {"s-live": "Name s-live"}
        assert await passes.earned_at("maya", ["occ-1", "occ-2"]) == {"occ-1": {"s-live"}}
    with tenant_scope(OTHER):
        assert await passes.earned_at("maya", ["occ-1", "occ-2"]) == {}  # only the re-earn shows
        assert await passes.earned_at("maya", ["occ-3"]) == {"occ-3": {"s-other"}}


async def test_migration_0243_indexes_back_the_repository_claims(real_db: Any) -> None:
    migration = importlib.import_module("backend.v2.migrations.0243_class_recaps_indexes")
    await migration.up(real_db)  # re-running is a no-op
    recaps = await real_db["class_recaps"].index_information()
    assert recaps["class_recaps_occurrence_uq"]["key"] == [("academy_id", 1), ("occurrence_id", 1)]
    assert recaps["class_recaps_occurrence_uq"]["unique"] is True
    reports = await real_db["class_recap_reports"].index_information()
    assert reports["class_recap_reports_report_uq"]["unique"] is True
    assert reports["class_recap_reports_handoff_idx"]["key"] == [
        ("academy_id", 1),
        ("outcome", 1),
        ("resolved_at", 1),
        ("submitted_at", -1),
    ]


async def test_coach_today_recap_lookup_counts_only_recaps_with_a_taught_skill(
    real_db: Any,
) -> None:
    from backend.v2.composition.coach import _recapped_occurrence_ids

    repo = MongoClassRecapRepository(real_db)
    lookup = _recapped_occurrence_ids(real_db)
    with tenant_scope(ACADEMY):
        assert await repo.save(_recap(1), expected_revision=0)
        assert await repo.save(
            _recap(1, recap_id="rc-2", occurrence_id="occ-2", taught_skill_ids=(), practice=()),
            expected_revision=0,
        )
        assert await lookup(["occ-1", "occ-2", "occ-3"]) == {"occ-1"}
    with tenant_scope(OTHER):
        assert await lookup(["occ-1"]) == set()


async def test_group_lessons_round_trip_and_a_batch_reads_its_earlier_recaps(
    real_db: Any,
) -> None:
    """The teaching plan's history read: one batch, strictly before the
    class, newest first, capped, tenant scoped; group lessons persist."""
    repo = MongoClassRecapRepository(real_db)
    lessons = (
        GroupLesson(level_id="lvl-1", skill_ids=("skill-a",)),
        GroupLesson(level_id="lvl-2", skill_ids=("skill-b",)),
    )
    with tenant_scope(ACADEMY):
        for day in range(4):
            await repo.save(
                _recap(
                    1,
                    recap_id=f"rc-{day}",
                    occurrence_id=f"occ-{day}",
                    class_starts_at=NOW - timedelta(days=day),
                    group_lessons=lessons if day == 1 else (),
                ),
                expected_revision=0,
            )
        await repo.save(
            _recap(1, recap_id="rc-x", occurrence_id="occ-x", session_id="sess-2"),
            expected_revision=0,
        )
        assert (await repo.get("occ-1")).group_lessons == lessons  # type: ignore[union-attr]
        earlier = await repo.list_for_session_before("sess-1", before=NOW, limit=2)
        assert [r.occurrence_id for r in earlier] == ["occ-1", "occ-2"]
        assert earlier[0].group_lessons == lessons
    with tenant_scope(OTHER):
        assert await repo.list_for_session_before("sess-1", before=NOW, limit=5) == []


async def test_migration_0248_backs_the_batch_history_read(real_db: Any) -> None:
    migration = importlib.import_module("backend.v2.migrations.0248_class_recaps_session_index")
    await migration.up(real_db)  # re-running is a no-op
    await migration.up(real_db)
    index = (await real_db["class_recaps"].index_information())["class_recaps_session_idx"]
    assert index["key"] == [("academy_id", 1), ("session_id", 1), ("class_starts_at", -1)]
    plan = (
        await real_db["class_recaps"]
        .find({"academy_id": ACADEMY, "session_id": "sess-1", "class_starts_at": {"$lt": NOW}})
        .sort([("class_starts_at", -1)])
        .explain()
    )
    assert "class_recaps_session_idx" in str(plan["queryPlanner"]["winningPlan"])


async def test_recap_groups_are_the_childrens_active_levels_lowest_first(real_db: Any) -> None:
    levels, progress = MongoLevelRepository(real_db), MongoStudentLevelProgressRepository(real_db)
    with tenant_scope(ACADEMY):
        for seq, level_id, active in ((2, "lvl-2", True), (1, "lvl-1", True), (3, "lvl-3", False)):
            await levels.save(
                Level(
                    level_id=level_id,
                    program_id="prog-1",
                    academy_id=ACADEMY,
                    sequence=seq,
                    name=f"Level {seq}",
                    is_active=active,
                    created_at=NOW,
                    updated_at=NOW,
                    created_by="owner",
                )
            )
        for student, level_id, status in (
            ("maya", "lvl-2", "active"),
            ("leo", "lvl-1", "active"),
            ("ada", "lvl-1", "active"),
            ("old", "lvl-1", "completed"),  # moved on: no longer in that group
            ("ret", "lvl-3", "active"),  # retired level: no group
            ("new", "lvl-1", "active"),  # not in this class
        ):
            await progress.save(
                StudentLevelProgress(
                    progress_id=f"lp-{student}",
                    academy_id=ACADEMY,
                    student_id=student,
                    program_id="prog-1",
                    level_id=level_id,
                    status=status,  # type: ignore[arg-type]
                    started_at=NOW,
                    created_at=NOW,
                )
            )

        class _Program:
            async def execute(self) -> Any:
                return SimpleNamespace(program_id="prog-1")

        groups = await ActiveLevelGroups(
            level_progress=progress, levels=levels, resolve_default_program=_Program()
        ).for_students(["maya", "leo", "ada", "old", "ret"])
    assert [(g.level_id, g.name, g.student_ids) for g in groups] == [
        ("lvl-1", "Level 1", ["ada", "leo"]),
        ("lvl-2", "Level 2", ["maya"]),
    ]
    with tenant_scope(OTHER):
        assert (
            await ActiveLevelGroups(
                level_progress=progress, levels=levels, resolve_default_program=_Program()
            ).for_students(["maya"])
            == []
        )
