"""Placement and progress engine over a REAL mongod (lane L5 part A, slice A1).

Regression tests for the November skill wipe and its neighbours: placement
must keep skills a student already earned, close the old level honestly,
withdraw a level-up it supersedes, and progress writes must land on the
student's active level only. Real Mongo because the unique and partial
indexes on these collections are what the code leans on.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from backend.v2.contexts.curriculum.infrastructure.mongo_level_repo import MongoLevelRepository
from backend.v2.contexts.curriculum.infrastructure.mongo_skill_repo import MongoSkillRepository
from backend.v2.contexts.student_progress.application.errors import (
    LevelNotConfigured,
    LevelUpInProgress,
    SkillNotOnCurrentLevel,
)
from backend.v2.contexts.student_progress.application.use_cases.mark_skill_mastered import (
    MarkSkillMastered,
    MarkSkillMasteredCommand,
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
from backend.v2.contexts.student_progress.application.use_cases.review_level_up import (
    ReviewLevelUpCommand,
    ReviewLevelUpRecommendation,
)
from backend.v2.contexts.student_progress.application.use_cases.unmark_skill_mastered import (
    UnmarkSkillMastered,
    UnmarkSkillMasteredCommand,
)
from backend.v2.contexts.student_progress.domain.models import LevelUpRecommendation
from backend.v2.contexts.student_progress.infrastructure.curriculum_lookup_adapter import (
    CurriculumSkillLookupAdapter,
)
from backend.v2.contexts.student_progress.infrastructure.mongo_certificate_repo import (
    MongoSkillCertificateRepository,
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
from backend.v2.shared.tenancy.context import tenant_scope

pytestmark = pytest.mark.asyncio

ACADEMY = "acad-l5"
AT = datetime(2026, 11, 2, 18, 0, tzinfo=UTC)


async def _seed_curriculum(db: Any) -> None:
    common = {
        "academy_id": ACADEMY,
        "program_id": "prog",
        "created_at": AT,
        "updated_at": AT,
        "created_by": "owner",
    }
    await db["skill_levels"].insert_many(
        [
            {**common, "level_id": "L1", "sequence": 1, "name": "One", "is_active": True},
            # L2 is retired: the next level after L1 is L3, not "none".
            {**common, "level_id": "L2", "sequence": 2, "name": "Two", "is_active": False},
            {**common, "level_id": "L3", "sequence": 3, "name": "Three", "is_active": True},
            {
                **common,
                "level_id": "OTHER",
                "program_id": "prog-2",
                "sequence": 1,
                "name": "Elsewhere",
                "is_active": True,
            },
        ]
    )
    await db["skills"].insert_many(
        [
            {
                **common,
                "skill_id": "s1",
                "level_id": "L1",
                "sequence": 1,
                "name": "Grip",
                "is_active": True,
            },
            {
                **common,
                "skill_id": "s2",
                "level_id": "L1",
                "sequence": 2,
                "name": "Serve",
                "is_active": True,
            },
            {
                **common,
                "skill_id": "t1",
                "level_id": "L3",
                "sequence": 1,
                "name": "Smash",
                "is_active": True,
            },
        ]
    )


class _Live:
    async def has_active_or_paused_enrollment(self, student_id: str) -> bool:
        return True

    async def students_with_active_or_paused_enrollment(self, student_ids: list[str]) -> set[str]:
        return set(student_ids)


def _wire(db: Any) -> dict[str, Any]:
    level_progress = MongoStudentLevelProgressRepository(db)
    skill_progress = MongoStudentSkillProgressRepository(db)
    recs = MongoLevelUpRecommendationRepository(db)
    lookup = CurriculumSkillLookupAdapter(
        skill_repo=MongoSkillRepository(db), level_repo=MongoLevelRepository(db)
    )
    return {
        "level_progress": level_progress,
        "skill_progress": skill_progress,
        "recs": recs,
        "lookup": lookup,
        "place": PlaceStudentInLevel(
            level_progress=level_progress,
            skill_progress=skill_progress,
            skill_lookup=lookup,
            recommendations=recs,
        ),
        "record": RecordTestAttempt(
            level_progress=level_progress,
            skill_progress=skill_progress,
            test_attempts=MongoTestAttemptRepository(db),
            skill_lookup=lookup,
        ),
        "review": ReviewLevelUpRecommendation(
            recommendations=recs,
            level_progress=level_progress,
            skill_progress=skill_progress,
            certificates=MongoSkillCertificateRepository(db),
            skill_lookup=lookup,
            enrollment_lookup=_Live(),
        ),
    }


def _place(level_id: str, program_id: str = "prog") -> PlaceStudentInLevelCommand:
    return PlaceStudentInLevelCommand(
        student_id="kid", program_id=program_id, level_id=level_id, placed_by="owner"
    )


async def _pass(w: dict[str, Any], skill_id: str) -> None:
    await w["record"].execute(
        RecordTestAttemptCommand(
            student_id="kid",
            skill_id=skill_id,
            program_id="prog",
            coach_id="coach",
            attempts_count=1,
            success_count=1,
        )
    )


async def _rec(w: dict[str, Any], status: str = "RECOMMENDED") -> None:
    await w["recs"].save(
        LevelUpRecommendation(
            rec_id="rec-1",
            academy_id=ACADEMY,
            student_id="kid",
            from_level_id="L1",
            to_level_id="L3",
            program_id="prog",
            status=status,  # type: ignore[arg-type]
            recommended_by="coach",
            recommended_at=AT,
        )
    )


async def test_replacement_keeps_skills_the_student_already_earned(real_db: Any) -> None:
    await _seed_curriculum(real_db)
    with tenant_scope(ACADEMY):
        w = _wire(real_db)
        await w["place"].execute(_place("L1"))
        await _pass(w, "s1")
        await w["place"].execute(_place("L3"))
        await w["place"].execute(_place("L1"))

        kept = await w["skill_progress"].get("kid", "s1")
        seeded = await w["skill_progress"].get("kid", "s2")
        history = await w["level_progress"].list_for_student("kid")

    assert kept is not None and kept.status == "PASSED"
    assert seeded is not None and seeded.status == "NOT_STARTED"
    # Left L1 unfinished, then L3 unfinished: neither is "completed".
    assert [(h.level_id, h.status) for h in history] == [
        ("L1", "withdrawn"),
        ("L3", "withdrawn"),
        ("L1", "active"),
    ]


async def test_moving_on_from_a_finished_level_closes_it_completed(real_db: Any) -> None:
    await _seed_curriculum(real_db)
    with tenant_scope(ACADEMY):
        w = _wire(real_db)
        await w["place"].execute(_place("L1"))
        await _pass(w, "s1")
        await _pass(w, "s2")
        await w["place"].execute(_place("L3"))
        history = await w["level_progress"].list_for_student("kid")

    assert [(h.level_id, h.status) for h in history] == [("L1", "completed"), ("L3", "active")]


async def test_placement_rejects_retired_missing_and_other_program_levels(real_db: Any) -> None:
    await _seed_curriculum(real_db)
    with tenant_scope(ACADEMY):
        w = _wire(real_db)
        for level_id in ("L2", "nope", "OTHER"):
            with pytest.raises(LevelNotConfigured):
                await w["place"].execute(_place(level_id))


async def test_placement_withdraws_the_pending_level_up(real_db: Any) -> None:
    await _seed_curriculum(real_db)
    with tenant_scope(ACADEMY):
        w = _wire(real_db)
        await w["place"].execute(_place("L1"))
        await _rec(w)
        await w["place"].execute(_place("L3"))
        rec = await w["recs"].get("rec-1")

    assert rec is not None
    assert rec.status == "REJECTED"
    assert rec.rejection_reason == "superseded_by_placement"


async def test_placement_refuses_while_an_approval_is_in_flight(real_db: Any) -> None:
    await _seed_curriculum(real_db)
    with tenant_scope(ACADEMY):
        w = _wire(real_db)
        await w["place"].execute(_place("L1"))
        await _rec(w, status="APPROVING")
        with pytest.raises(LevelUpInProgress):
            await w["place"].execute(_place("L3"))
        active = await w["level_progress"].get_active("kid", "prog")

    assert active is not None and active.level_id == "L1"


async def test_approval_after_a_replacement_closes_without_a_certificate(real_db: Any) -> None:
    await _seed_curriculum(real_db)
    await real_db["skill_levels"].insert_one(
        {
            "academy_id": ACADEMY,
            "program_id": "prog",
            "level_id": "L4",
            "sequence": 4,
            "name": "Four",
            "is_active": True,
            "created_at": AT,
            "updated_at": AT,
        }
    )
    with tenant_scope(ACADEMY):
        w = _wire(real_db)
        # The rec predates a by-hand move to L4 that went around the use case.
        await w["place"].execute(_place("L4"))
        await _rec(w)
        result = await w["review"].execute(
            ReviewLevelUpCommand(rec_id="rec-1", action="approve", reviewed_by="owner")
        )
        active = await w["level_progress"].get_active("kid", "prog")
        certs = await real_db["skill_certificates"].count_documents({})

    assert result.status == "REJECTED" and result.cert_id is None
    assert active is not None and active.level_id == "L4"
    assert certs == 0


async def test_next_level_skips_a_retired_level(real_db: Any) -> None:
    await _seed_curriculum(real_db)
    with tenant_scope(ACADEMY):
        nxt = await _wire(real_db)["lookup"].get_next_level("prog", 1)

    assert nxt is not None and nxt.level_id == "L3"


async def test_progress_writes_land_on_the_active_level_only(real_db: Any) -> None:
    await _seed_curriculum(real_db)
    with tenant_scope(ACADEMY):
        w = _wire(real_db)
        await w["place"].execute(_place("L1"))
        with pytest.raises(SkillNotOnCurrentLevel):
            await _pass(w, "t1")
        # A stale client level_id is ignored: the attempt lands on L1.
        await w["record"].execute(
            RecordTestAttemptCommand(
                student_id="kid",
                skill_id="s1",
                level_id="L3",
                program_id="prog",
                coach_id="coach",
                attempts_count=1,
                success_count=1,
            )
        )
        row = await w["skill_progress"].get("kid", "s1")
        attempt = await real_db["test_attempts"].find_one({"skill_id": "s1"})

    assert row is not None and row.level_id == "L1"
    assert attempt is not None and attempt["level_id"] == "L1"
    assert await real_db["test_attempts"].count_documents({"skill_id": "t1"}) == 0


# --- Slice A2: per-skill pass rule ------------------------------------------


async def _set_rule(db: Any, skill_id: str, rule: str, tries: int | None = None) -> None:
    await db["skills"].update_one(
        {"skill_id": skill_id}, {"$set": {"pass_rule": rule, "pass_tries": tries}}
    )


def _wire_tap(db: Any) -> dict[str, Any]:
    w = _wire(db)
    recommend = RecommendLevelUp(
        level_progress=w["level_progress"],
        skill_progress=w["skill_progress"],
        recommendations=w["recs"],
        skill_lookup=w["lookup"],
        enrollment_lookup=_Live(),
    )
    w["mark"] = MarkSkillMastered(
        level_progress=w["level_progress"],
        skill_progress=w["skill_progress"],
        skill_lookup=w["lookup"],
        record_test_attempt=w["record"],
        recommend_level_up=recommend,
    )
    w["unmark"] = UnmarkSkillMastered(
        level_progress=w["level_progress"],
        skill_progress=w["skill_progress"],
        recommendations=w["recs"],
        skill_lookup=w["lookup"],
    )
    return w


async def _tap(w: dict[str, Any], skill_id: str, *, lead: bool = True) -> Any:
    [outcome] = await w["mark"].execute(
        MarkSkillMasteredCommand(
            skill_id=skill_id,
            program_id="prog",
            student_ids=["kid"],
            coach_id="coach",
            can_sign_off=lead,
        )
    )
    return outcome


async def test_n_tries_passes_on_the_nth_tap_and_undo_takes_one_back(real_db: Any) -> None:
    await _seed_curriculum(real_db)
    await _set_rule(real_db, "s1", "N_TRIES", 3)
    with tenant_scope(ACADEMY):
        w = _wire_tap(real_db)
        await w["place"].execute(_place("L1"))
        first = await _tap(w, "s1")
        second = await _tap(w, "s1")
        practicing = await w["skill_progress"].get("kid", "s1")
        third = await _tap(w, "s1")
        passed = await w["skill_progress"].get("kid", "s1")
        await w["unmark"].execute(
            UnmarkSkillMasteredCommand(
                student_id="kid", skill_id="s1", program_id="prog", updated_by="coach"
            )
        )
        undone = await w["skill_progress"].get("kid", "s1")
        attempt = await real_db["test_attempts"].find_one({"skill_id": "s1"})

    assert (first.outcome, first.tries) == ("try_recorded", 1)
    assert (second.outcome, second.tries) == ("try_recorded", 2)
    assert practicing is not None and practicing.status == "PRACTICING"
    assert (third.outcome, third.tries) == ("mastered", 3)
    assert passed is not None and passed.status == "PASSED" and passed.tries == 3
    assert attempt is not None
    assert (attempt["attempts_count"], attempt["success_count"]) == (3, 3)
    # Undo drops the pass and one try: the next tap passes again.
    assert undone is not None and (undone.status, undone.tries) == ("PRACTICING", 2)


async def test_undo_of_a_try_below_n_takes_the_try_back(real_db: Any) -> None:
    await _seed_curriculum(real_db)
    await _set_rule(real_db, "s1", "N_TRIES", 3)
    with tenant_scope(ACADEMY):
        w = _wire_tap(real_db)
        await w["place"].execute(_place("L1"))
        await _tap(w, "s1")
        for _ in range(2):  # the second undo has nothing left and stays at 0
            await w["unmark"].execute(
                UnmarkSkillMasteredCommand(
                    student_id="kid", skill_id="s1", program_id="prog", updated_by="coach"
                )
            )
        row = await w["skill_progress"].get("kid", "s1")

    assert row is not None and row.tries == 0


async def test_lead_coach_skill_needs_a_lead_and_one_tap_is_unchanged(real_db: Any) -> None:
    await _seed_curriculum(real_db)
    await _set_rule(real_db, "s1", "LEAD_COACH")
    with tenant_scope(ACADEMY):
        w = _wire_tap(real_db)
        await w["place"].execute(_place("L1"))
        assistant = await _tap(w, "s1", lead=False)
        waiting = await w["skill_progress"].get("kid", "s1")
        lead = await _tap(w, "s1")
        one_tap = await _tap(w, "s2", lead=False)

    assert assistant.outcome == "needs_lead"
    assert waiting is not None and waiting.status == "NOT_STARTED"
    assert lead.outcome == "mastered"
    # A one-tap skill still passes for an assistant; it finishes L1 here.
    assert one_tap.outcome == "mastered" and one_tap.level_up_queued is True
