"""A pass recorded in a dated class, over a real mongod (validators applied).

``ProgressClassDemonstrations`` is the composition adapter behind
``RecordClassDemonstration``: the program comes from the skill, the pass rule
from student_progress's one writer. Mixed levels in one class: a Level 1
child may pass a Level 3 skill, which counts on Level 3 only. It never
completes, queues or certifies anything, and the child's badge stays put.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest

from backend.v2.composition.class_recap import ProgressClassDemonstrations
from backend.v2.contexts.curriculum.infrastructure.mongo_level_repo import MongoLevelRepository
from backend.v2.contexts.curriculum.infrastructure.mongo_skill_repo import MongoSkillRepository
from backend.v2.contexts.student_progress.application.use_cases.mark_skill_mastered import (
    MarkSkillMastered,
)
from backend.v2.contexts.student_progress.application.use_cases.place_student import (
    PlaceStudentInLevel,
    PlaceStudentInLevelCommand,
)
from backend.v2.contexts.student_progress.application.use_cases.recommend_level_up import (
    RecommendLevelUp,
)
from backend.v2.contexts.student_progress.application.use_cases.record_test_attempt import (
    RecordTestAttempt,
    RecordTestAttemptCommand,
)
from backend.v2.contexts.student_progress.infrastructure.curriculum_lookup_adapter import (
    CurriculumSkillLookupAdapter,
)
from backend.v2.contexts.student_progress.infrastructure.mongo_level_progress_repo import (
    MongoStudentLevelProgressRepository,
)
from backend.v2.contexts.student_progress.infrastructure.mongo_recommendation_repo import (
    MongoLevelUpRecommendationRepository,
)
from backend.v2.contexts.student_progress.infrastructure.mongo_skill_progress_repo import (
    MongoStudentSkillProgressRepository,
)
from backend.v2.contexts.student_progress.infrastructure.mongo_test_attempt_repo import (
    MongoTestAttemptRepository,
)
from backend.v2.shared.events import MongoOutbox
from backend.v2.shared.tenancy.context import tenant_scope

pytestmark = pytest.mark.asyncio

ACADEMY = "acad-demo"
AT = datetime(2026, 11, 2, 18, 0, tzinfo=UTC)
CLASS_AT = datetime(2026, 11, 20, 17, 0, tzinfo=UTC)


class _Live:
    async def has_active_or_paused_enrollment(self, student_id: str) -> bool:
        return True

    async def student_exists(self, student_id: str) -> bool:
        return True

    async def students_with_active_or_paused_enrollment(self, student_ids: list[str]) -> set[str]:
        return set(student_ids)


class _Crash(Exception):
    """A process dying part way through a save."""


class _CrashingAttempts(MongoTestAttemptRepository):
    crash_on: set[str]

    async def insert_observation(self, attempt: Any) -> bool:
        stored = await super().insert_observation(attempt)
        if "after_attempt" in self.crash_on:
            self.crash_on.discard("after_attempt")
            raise _Crash
        return stored

    async def mark_effects_done(self, attempt_id: str, *, at: datetime) -> None:
        if "before_done" in self.crash_on:
            self.crash_on.discard("before_done")
            raise _Crash
        await super().mark_effects_done(attempt_id, at=at)


class _CrashingProgress(MongoStudentSkillProgressRepository):
    crash_on: set[str]

    async def add_try_once(self, student_id: str, skill_id: str, contribution_id: str) -> int:
        tries = await super().add_try_once(student_id, skill_id, contribution_id)
        if "after_increment" in self.crash_on:
            self.crash_on.discard("after_increment")
            raise _Crash
        return tries


class _Events:
    def __init__(self, db: Any) -> None:
        self._db = db

    async def count(self, name: str) -> int:
        return await self._db["outbox_events"].count_documents(
            {"academy_id": ACADEMY, "name": f"StudentProgress.{name}"}
        )


async def _seed(db: Any) -> None:
    common = {"academy_id": ACADEMY, "created_at": AT, "updated_at": AT, "created_by": "owner"}
    levels = [
        ("L1", "prog", 1, True),
        ("L2", "prog", 2, False),  # retired
        ("L3", "prog", 3, True),
        ("X1", "prog-2", 1, True),  # another program
    ]
    await db["skill_levels"].insert_many(
        [
            {
                **common,
                "level_id": lid,
                "program_id": pid,
                "sequence": seq,
                "name": lid,
                "is_active": active,
            }
            for lid, pid, seq, active in levels
        ]
    )
    skills = [
        ("grip", "L1", "prog", "ONE_TAP", True),
        ("serve", "L1", "prog", "ONE_TAP", True),
        ("clear", "L3", "prog", "ONE_TAP", True),  # L3's only required skill
        ("drop", "L3", "prog", "N_TRIES", True),
        ("lead", "L3", "prog", "LEAD_COACH", True),
        ("old", "L2", "prog", "ONE_TAP", True),
        ("gone", "L3", "prog", "ONE_TAP", False),
        ("far", "X1", "prog-2", "ONE_TAP", True),
    ]
    await db["skills"].insert_many(
        [
            {
                **common,
                "skill_id": sid,
                "level_id": lid,
                "program_id": pid,
                "sequence": i,
                "name": sid,
                "is_active": active,
                "pass_rule": rule,
                "pass_tries": 2 if rule == "N_TRIES" else None,
                "is_required": sid in {"grip", "serve", "clear"},
            }
            for i, (sid, lid, pid, rule, active) in enumerate(skills, start=1)
        ]
    )


def _wire(db: Any) -> dict[str, Any]:
    level_progress = MongoStudentLevelProgressRepository(db)
    skill_progress = _CrashingProgress(db)
    skill_progress.crash_on = set()
    attempts = _CrashingAttempts(db)
    attempts.crash_on = set()
    recs = MongoLevelUpRecommendationRepository(db)
    lookup = CurriculumSkillLookupAdapter(
        skill_repo=MongoSkillRepository(db), level_repo=MongoLevelRepository(db)
    )
    # No idempotency store: a class observation must not lean on a cache
    # that expires; the stored attempt is what makes it replayable.
    record = RecordTestAttempt(
        level_progress=level_progress,
        skill_progress=skill_progress,
        test_attempts=attempts,
        skill_lookup=lookup,
        outbox=MongoOutbox(db),
    )
    mark = MarkSkillMastered(
        level_progress=level_progress,
        skill_progress=skill_progress,
        skill_lookup=lookup,
        record_test_attempt=record,
        recommend_level_up=RecommendLevelUp(
            level_progress=level_progress,
            skill_progress=skill_progress,
            recommendations=recs,
            skill_lookup=lookup,
            enrollment_lookup=_Live(),
        ),
    )
    return {
        "place": PlaceStudentInLevel(
            level_progress=level_progress,
            skill_progress=skill_progress,
            skill_lookup=lookup,
            recommendations=recs,
            enrollment_lookup=_Live(),
        ),
        "class": ProgressClassDemonstrations(
            skills=MongoSkillRepository(db),
            mark_mastered=mark,
            attempts=attempts,
            progress=skill_progress,
        ),
        "record": record,
        "level_progress": level_progress,
        "skill_progress": skill_progress,
        "attempts": attempts,
        "recs": recs,
        "events": _Events(db),
    }


async def _place(w: dict[str, Any], kid: str, level_id: str) -> None:
    await w["place"].execute(
        PlaceStudentInLevelCommand(
            student_id=kid, program_id="prog", level_id=level_id, placed_by="owner"
        )
    )


async def _record(
    w: dict[str, Any], skill_id: str, kids: list[str], *, occ: str = "occ-1", sign: bool = True
) -> dict[str, Any]:
    out = await w["class"].record(
        skill_id=skill_id,
        student_ids=kids,
        coach_id="sub-coach",
        can_sign_off=sign,
        session_id="sess-1",
        occurrence_id=occ,
        observed_at=CLASS_AT,
    )
    return {o.student_id: o for o in out}


async def test_level_one_child_passes_a_level_three_skill_without_moving(real_db: Any) -> None:
    await _seed(real_db)
    with tenant_scope(ACADEMY):
        w = _wire(real_db)
        await _place(w, "maya", "L1")
        await _place(w, "leo", "L3")

        out = await _record(w, "clear", ["maya", "leo"])

        assert (out["maya"].outcome, out["maya"].off_level) == ("mastered", True)
        assert out["maya"].level_up_queued is False
        # Leo is on L3: the same tap completes his level the usual way.
        assert (out["leo"].outcome, out["leo"].off_level) == ("mastered", False)
        assert out["leo"].level_up_queued is True
        progress = await w["skill_progress"].get("maya", "clear")
        assert progress.status == "PASSED" and progress.level_id == "L3"
        active = await w["level_progress"].get_active("maya", "prog")
        assert active.level_id == "L1"  # the badge stays Level 1
        assert await w["recs"].list_recommended_for_student("maya") == []
        assert len(await w["recs"].list_recommended_for_student("leo")) == 1
        # One LevelCompleted only: Leo's. Maya's off-level pass completed nothing.
        assert await w["events"].count("LevelCompleted") == 1
        (attempt,) = await w["attempts"].list_for_student_skill("maya", "clear")
        assert attempt.level_id == "L3" and attempt.occurrence_id == "occ-1"
        assert attempt.observed_at.replace(tzinfo=UTC) == CLASS_AT
        assert attempt.tested_at.replace(tzinfo=UTC) > CLASS_AT  # entered after
        assert attempt.coach_id == "sub-coach" and attempt.signed_off_by == "sub-coach"


async def test_an_earlier_pass_is_preserved(real_db: Any) -> None:
    await _seed(real_db)
    with tenant_scope(ACADEMY):
        w = _wire(real_db)
        await _place(w, "maya", "L1")
        await _record(w, "clear", ["maya"])
        again = await _record(w, "clear", ["maya"], occ="occ-2")
        assert again["maya"].outcome == "already_mastered"
        assert (await w["skill_progress"].get("maya", "clear")).status == "PASSED"
        assert len(await w["attempts"].list_for_student_skill("maya", "clear")) == 1


async def test_n_tries_counts_once_per_retry_and_lead_skill_needs_a_signer(
    real_db: Any,
) -> None:
    await _seed(real_db)
    with tenant_scope(ACADEMY):
        w = _wire(real_db)
        await _place(w, "maya", "L1")
        first = await _record(w, "drop", ["maya"])
        retry = await _record(w, "drop", ["maya"])
        assert (first["maya"].outcome, first["maya"].tries) == ("try_recorded", 1)
        assert retry["maya"].tries == 1  # same class: one observation, no second try
        second = await _record(w, "drop", ["maya"], occ="occ-2")
        assert second["maya"].outcome == "mastered"

        unsigned = await _record(w, "lead", ["maya"], sign=False)
        assert unsigned["maya"].outcome == "needs_lead"
        assert await w["skill_progress"].get("maya", "lead") is None


@pytest.mark.parametrize(
    ("skill_id", "outcome"),
    [
        ("old", "not_on_level"),
        ("gone", "not_on_level"),
        ("far", "not_placed"),
        ("nope", "not_on_level"),
    ],
)
async def test_retired_foreign_or_unknown_skills_write_nothing(
    real_db: Any, skill_id: str, outcome: str
) -> None:
    await _seed(real_db)
    with tenant_scope(ACADEMY):
        w = _wire(real_db)
        await _place(w, "maya", "L1")
        out = await _record(w, skill_id, ["maya"])
        assert out["maya"].outcome == outcome
        assert await w["attempts"].list_for_student_skill("maya", skill_id) == []
        assert await real_db["outbox_events"].count_documents({}) == 0


async def test_another_academy_cannot_see_the_skill(real_db: Any) -> None:
    await _seed(real_db)
    with tenant_scope("acad-other"):
        w = _wire(real_db)
        out = await _record(w, "clear", ["maya"])
        assert out["maya"].outcome == "not_on_level"


# --- step 3: one save, recoverable -----------------------------------------


@pytest.mark.parametrize("crash", ["after_attempt", "before_done"])
async def test_an_interrupted_pass_resumes_to_one_pass_and_one_event(
    real_db: Any, crash: str
) -> None:
    await _seed(real_db)
    with tenant_scope(ACADEMY):
        w = _wire(real_db)
        await _place(w, "maya", "L1")
        w["attempts"].crash_on = {crash}
        with pytest.raises(_Crash):
            await _record(w, "clear", ["maya"])
        assert (await w["class"].receipts("occ-1", [("maya", "clear")]))[
            ("maya", "clear")
        ] == "in_progress"

        out = await _record(w, "clear", ["maya"])

        assert out["maya"].outcome == "mastered"
        assert len(await w["attempts"].list_for_student_skill("maya", "clear")) == 1
        assert await w["events"].count("SkillPassed") == 1
        assert await w["events"].count("SkillTestAttempted") == 1
        receipts = await w["class"].receipts("occ-1", [("maya", "clear"), ("maya", "grip")])
        assert receipts == {("maya", "clear"): "recorded", ("maya", "grip"): "not_recorded"}


async def test_interrupted_after_the_try_counts_it_once(real_db: Any) -> None:
    await _seed(real_db)
    with tenant_scope(ACADEMY):
        w = _wire(real_db)
        await _place(w, "maya", "L1")
        await _record(w, "drop", ["maya"])  # try 1 of 2, class one
        w["skill_progress"].crash_on = {"after_increment"}
        with pytest.raises(_Crash):
            await _record(w, "drop", ["maya"], occ="occ-2")
        out = await _record(w, "drop", ["maya"], occ="occ-2")
        late = await _record(w, "drop", ["maya"])  # a stale retry of class one
        assert out["maya"].outcome == "mastered" and out["maya"].tries == 2
        assert (late["maya"].outcome, late["maya"].tries) == ("try_recorded", 1)
        assert (await w["skill_progress"].get("maya", "drop")).tries == 2
        assert await w["events"].count("SkillPassed") == 1  # one genuine transition


async def test_two_writers_store_one_observation(real_db: Any) -> None:
    await _seed(real_db)
    with tenant_scope(ACADEMY):
        w, other = _wire(real_db), _wire(real_db)
        await _place(w, "maya", "L1")
        await asyncio.gather(_record(w, "drop", ["maya"]), _record(other, "drop", ["maya"]))
        assert len(await w["attempts"].list_for_student_skill("maya", "drop")) == 1
        assert (await w["skill_progress"].get("maya", "drop")).tries == 1


async def test_formal_tests_still_repeat(real_db: Any) -> None:
    await _seed(real_db)
    with tenant_scope(ACADEMY):
        w = _wire(real_db)
        await _place(w, "maya", "L1")
        for _ in range(2):
            await w["record"].execute(
                RecordTestAttemptCommand(
                    student_id="maya",
                    skill_id="grip",
                    program_id="prog",
                    coach_id="coach",
                    can_sign_off=True,
                    attempts_count=5,
                    success_count=1,
                )
            )
        assert len(await w["attempts"].list_for_student_skill("maya", "grip")) == 2


async def test_an_undone_try_is_not_counted_toward_the_pass(real_db: Any) -> None:
    await _seed(real_db)
    with tenant_scope(ACADEMY):
        w = _wire(real_db)
        await _place(w, "maya", "L1")
        await _record(w, "drop", ["maya"])  # try 1 of 2
        assert await w["skill_progress"].increment_tries("maya", "drop", -1) == 0  # undo
        out = await _record(w, "drop", ["maya"], occ="occ-2")
        assert (out["maya"].outcome, out["maya"].tries) == ("try_recorded", 1)
        plain = await w["skill_progress"].increment_tries("maya", "drop", 1)  # a plain tap
        replay = await _record(w, "drop", ["maya"], occ="occ-2")
        assert plain == 2 and replay["maya"].tries == 1  # the replay keeps its own count
        assert await w["events"].count("SkillPassed") == 0


async def test_resuming_a_landed_pass_does_not_announce_it_again(real_db: Any) -> None:
    await _seed(real_db)
    with tenant_scope(ACADEMY):
        w = _wire(real_db)
        await _place(w, "maya", "L1")
        w["attempts"].crash_on = {"before_done"}
        with pytest.raises(_Crash):
            await _record(w, "clear", ["maya"])
        first = (await w["skill_progress"].get("maya", "clear")).last_updated_at
        await _record(w, "clear", ["maya"])
        assert (await w["skill_progress"].get("maya", "clear")).last_updated_at == first
