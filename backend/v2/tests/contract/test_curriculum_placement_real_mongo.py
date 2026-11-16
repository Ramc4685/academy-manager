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
    PassNeedsLeadCoach,
    SkillAlreadyPassed,
    SkillNotOnCurrentLevel,
    StudentNotFound,
)
from backend.v2.contexts.student_progress.application.use_cases.auto_approve_level_ups import (
    AutoApproveLevelUps,
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
from backend.v2.contexts.student_progress.application.use_cases.update_skill_status import (
    UpdateSkillStatus,
    UpdateSkillStatusCommand,
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
from backend.v2.tests.fixtures.certificate_fakes import SequentialCertNumbers

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
    """Every student attends; only ``unknown`` ids are missing from the academy."""

    def __init__(self, unknown: frozenset[str] = frozenset()) -> None:
        self.unknown = unknown

    async def has_active_or_paused_enrollment(self, student_id: str) -> bool:
        return True

    async def student_exists(self, student_id: str) -> bool:
        return student_id not in self.unknown

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
            enrollment_lookup=_Live(),
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
            cert_numbers=SequentialCertNumbers(),
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
            can_sign_off=True,
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
                can_sign_off=True,
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
                can_sign_off=True,
                student_id="kid",
                skill_id="s1",
                program_id="prog",
                updated_by="coach",
            )
        )
        undone = await w["skill_progress"].get("kid", "s1")
        attempts = await real_db["test_attempts"].count_documents({"skill_id": "s1"})

    assert (first.outcome, first.tries) == ("try_recorded", 1)
    assert (second.outcome, second.tries) == ("try_recorded", 2)
    assert practicing is not None and practicing.status == "PRACTICING"
    assert (third.outcome, third.tries) == ("mastered", 3)
    assert passed is not None and passed.status == "PASSED" and passed.tries == 3
    assert attempts == 3  # one 1-of-1 attempt per tap: the audit trail shows each try
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
                    can_sign_off=True,
                    student_id="kid",
                    skill_id="s1",
                    program_id="prog",
                    updated_by="coach",
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


# --- Slice A3: place and credit ---------------------------------------------


def _credit(
    level_id: str, skills: list[str], *, notify: bool = False
) -> PlaceStudentInLevelCommand:
    return PlaceStudentInLevelCommand(
        student_id="kid",
        program_id="prog",
        level_id=level_id,
        placed_by="owner",
        credited_skill_ids=skills,
        notify_parents=notify,
    )


async def test_credits_pass_quietly_and_never_queue_a_level_up(real_db: Any) -> None:
    await _seed_curriculum(real_db)
    with tenant_scope(ACADEMY):
        w = _wire(real_db)
        await w["place"].execute(_credit("L1", ["s1", "s2"]))
        rows = [await w["skill_progress"].get("kid", s) for s in ("s1", "s2")]
        wins = await w["skill_progress"].list_passed_between(
            datetime(2000, 1, 1, tzinfo=UTC), datetime(2100, 1, 1, tzinfo=UTC)
        )
        rec = await w["recs"].get_active_for_student("kid", "prog")

    assert all(r is not None and r.status == "PASSED" and r.silent for r in rows)
    assert wins == []  # quiet credits stay out of the parents' evening wins
    assert rec is None


async def test_credits_apply_on_the_same_level_and_can_be_announced(real_db: Any) -> None:
    await _seed_curriculum(real_db)
    with tenant_scope(ACADEMY):
        w = _wire(real_db)
        first = await w["place"].execute(_place("L1"))
        again = await w["place"].execute(_credit("L1", ["s1"], notify=True))
        row = await w["skill_progress"].get("kid", "s1")
        wins = await w["skill_progress"].list_passed_between(
            datetime(2000, 1, 1, tzinfo=UTC), datetime(2100, 1, 1, tzinfo=UTC)
        )

    assert again.progress_id == first.progress_id
    assert row is not None and row.status == "PASSED" and not row.silent
    assert [w_.skill_id for w_ in wins] == ["s1"]


async def test_a_credit_from_another_level_refuses_the_whole_placement(real_db: Any) -> None:
    await _seed_curriculum(real_db)
    with tenant_scope(ACADEMY):
        w = _wire(real_db)
        with pytest.raises(SkillNotOnCurrentLevel):
            await w["place"].execute(_credit("L1", ["s1", "t1"]))
        active = await w["level_progress"].get_active("kid", "prog")

    assert active is None
    assert await real_db["student_skill_progress"].count_documents({}) == 0


async def test_a_real_pass_announces_a_quiet_credit(real_db: Any) -> None:
    await _seed_curriculum(real_db)
    with tenant_scope(ACADEMY):
        w = _wire(real_db)
        await w["place"].execute(_place("L1"))
        await w["place"].execute(_credit("L1", ["s1"]))
        await _pass(w, "s1")
        row = await w["skill_progress"].get("kid", "s1")

    assert row is not None and not row.silent


async def test_a_detailed_test_cannot_pass_a_lead_coach_skill_for_an_assistant(
    real_db: Any,
) -> None:
    """Security: the test route goes through the same predicate as the tap."""
    await _seed_curriculum(real_db)
    await _set_rule(real_db, "s1", "LEAD_COACH")
    with tenant_scope(ACADEMY):
        w = _wire(real_db)
        await w["place"].execute(_place("L1"))
        test = RecordTestAttemptCommand(
            student_id="kid",
            skill_id="s1",
            program_id="prog",
            coach_id="helper",
            can_sign_off=False,
            attempts_count=5,
            success_count=5,
        )
        with pytest.raises(PassNeedsLeadCoach):
            await w["record"].execute(test)
        refused = await w["skill_progress"].get("kid", "s1")
        # A failing attempt is still the assistant's to record.
        await w["record"].execute(test.model_copy(update={"success_count": 0}))
        lead = await w["record"].execute(test.model_copy(update={"can_sign_off": True}))

    assert refused is not None and refused.status == "NOT_STARTED"
    assert lead.passed and lead.skill_status == "PASSED"


async def test_a_detailed_test_counts_one_try_on_an_n_tries_skill(real_db: Any) -> None:
    await _seed_curriculum(real_db)
    await _set_rule(real_db, "s1", "N_TRIES", 2)
    with tenant_scope(ACADEMY):
        w = _wire(real_db)
        await w["place"].execute(_place("L1"))
        first = await w["record"].execute(
            RecordTestAttemptCommand(
                student_id="kid",
                skill_id="s1",
                program_id="prog",
                coach_id="coach",
                can_sign_off=True,
                attempts_count=10,
                success_count=10,
                coach_override=False,
            )
        )
        second = await w["record"].execute(
            RecordTestAttemptCommand(
                student_id="kid",
                skill_id="s1",
                program_id="prog",
                coach_id="coach",
                can_sign_off=True,
                attempts_count=1,
                success_count=1,
            )
        )

    assert (first.passed, first.skill_status, first.tries) == (False, "PRACTICING", 1)
    assert (second.passed, second.skill_status, second.tries) == (True, "PASSED", 2)


# --- Fix round: a pass stays a pass, undo, lead-coach demotion -------------


def _test(skill_id: str, *, passing: bool = True, lead: bool = True) -> RecordTestAttemptCommand:
    return RecordTestAttemptCommand(
        student_id="kid",
        skill_id=skill_id,
        program_id="prog",
        coach_id="coach",
        can_sign_off=lead,
        attempts_count=1,
        success_count=1 if passing else 0,
    )


def _undo(skill_id: str, *, lead: bool = True) -> UnmarkSkillMasteredCommand:
    return UnmarkSkillMasteredCommand(
        student_id="kid",
        skill_id=skill_id,
        program_id="prog",
        updated_by="coach",
        can_sign_off=lead,
    )


async def test_a_credited_skill_switched_to_n_tries_stays_passed(real_db: Any) -> None:
    """A credit has tries 0; a passing test after the switch must not demote it."""
    await _seed_curriculum(real_db)
    with tenant_scope(ACADEMY):
        w = _wire(real_db)
        await w["place"].execute(_credit("L1", ["s1"]))
        await _set_rule(real_db, "s1", "N_TRIES", 3)
        result = await w["record"].execute(_test("s1"))
        row = await w["skill_progress"].get("kid", "s1")

    assert (result.passed, result.skill_status) == (True, "PASSED")
    assert row is not None and row.status == "PASSED"


async def test_a_one_tap_pass_switched_to_n_tries_stays_passed(real_db: Any) -> None:
    await _seed_curriculum(real_db)
    with tenant_scope(ACADEMY):
        w = _wire(real_db)
        await w["place"].execute(_place("L1"))
        await _pass(w, "s1")
        await _set_rule(real_db, "s1", "N_TRIES", 3)
        result = await w["record"].execute(_test("s1"))
        row = await w["skill_progress"].get("kid", "s1")

    assert (result.passed, result.skill_status) == (True, "PASSED")
    assert row is not None and row.status == "PASSED"


async def test_a_practicing_write_never_lands_on_a_passed_row(real_db: Any) -> None:
    """The lost-pass race: a stale try that reads before a pass writes after it."""
    await _seed_curriculum(real_db)
    with tenant_scope(ACADEMY):
        w = _wire(real_db)
        await w["place"].execute(_place("L1"))
        await _pass(w, "s1")
        landed = await w["skill_progress"].set_status_unless_passed(
            "kid", "s1", "PRACTICING", at=AT, by="coach"
        )
        row = await w["skill_progress"].get("kid", "s1")

    assert landed is False
    assert row is not None and row.status == "PASSED"


async def test_a_same_level_credit_seeds_a_skill_added_after_placement(real_db: Any) -> None:
    await _seed_curriculum(real_db)
    with tenant_scope(ACADEMY):
        w = _wire(real_db)
        await w["place"].execute(_place("L1"))
        await real_db["skills"].insert_one(
            {
                "academy_id": ACADEMY,
                "program_id": "prog",
                "level_id": "L1",
                "skill_id": "s3",
                "sequence": 3,
                "name": "Drop",
                "is_active": True,
                "created_at": AT,
                "updated_at": AT,
                "created_by": "owner",
            }
        )
        await w["place"].execute(_credit("L1", ["s3"]))
        row = await w["skill_progress"].get("kid", "s3")

    assert row is not None and row.status == "PASSED"


async def test_approval_refuses_a_retired_target_and_leaves_the_rec_pending(
    real_db: Any,
) -> None:
    await _seed_curriculum(real_db)
    with tenant_scope(ACADEMY):
        w = _wire(real_db)
        await w["place"].execute(_place("L1"))
        await _rec(w)
        await real_db["skill_levels"].update_one({"level_id": "L3"}, {"$set": {"is_active": False}})
        with pytest.raises(LevelNotConfigured):
            await w["review"].execute(
                ReviewLevelUpCommand(
                    rec_id="rec-1",
                    action="approve",
                    reviewed_by="owner",
                    student_name="Kid",
                    level_name="One",
                    program_name="Prog",
                )
            )
        rec = await w["recs"].get("rec-1")
        active = await w["level_progress"].get_active("kid", "prog")

    assert rec is not None and rec.status == "RECOMMENDED"
    assert active is not None and active.level_id == "L1"


async def test_undoing_a_try_keeps_the_pending_level_up(real_db: Any) -> None:
    """Only undoing a pass withdraws the level-up; a try below N does not."""
    await _seed_curriculum(real_db)
    await _set_rule(real_db, "s1", "N_TRIES", 3)
    with tenant_scope(ACADEMY):
        w = _wire_tap(real_db)
        await w["place"].execute(_place("L1"))
        await _tap(w, "s1")
        await _rec(w)
        result = await w["unmark"].execute(_undo("s1"))
        rec = await w["recs"].get("rec-1")

    assert result.withdrawn_rec_ids == []
    assert rec is not None and rec.status == "RECOMMENDED"


async def test_an_assistant_cannot_undo_or_fail_a_lead_coach_pass(real_db: Any) -> None:
    await _seed_curriculum(real_db)
    await _set_rule(real_db, "s1", "LEAD_COACH")
    with tenant_scope(ACADEMY):
        w = _wire_tap(real_db)
        await w["place"].execute(_place("L1"))
        await _tap(w, "s1")
        with pytest.raises(PassNeedsLeadCoach):
            await w["unmark"].execute(_undo("s1", lead=False))
        with pytest.raises(PassNeedsLeadCoach):
            await w["record"].execute(_test("s1", passing=False, lead=False))
        kept = await w["skill_progress"].get("kid", "s1")
        attempts = await real_db["test_attempts"].count_documents({"skill_id": "s1"})
        await w["unmark"].execute(_undo("s1"))
        undone = await w["skill_progress"].get("kid", "s1")

    assert kept is not None and kept.status == "PASSED"
    assert attempts == 1  # the refused failing test wrote nothing
    assert undone is not None and undone.status == "PRACTICING"


async def test_a_status_write_never_lands_on_a_pass_made_after_its_read(real_db: Any) -> None:
    """A tap passes the skill between UpdateSkillStatus's read and its write."""
    await _seed_curriculum(real_db)
    with tenant_scope(ACADEMY):
        w = _wire(real_db)
        await w["place"].execute(_place("L1"))
        repo = w["skill_progress"]
        read = repo.get

        async def read_then_tap(student_id: str, skill_id: str) -> Any:
            row = await read(student_id, skill_id)
            repo.get = read  # the tap below reads normally
            await _pass(w, skill_id)
            return row

        repo.get = read_then_tap
        status = UpdateSkillStatus(
            level_progress=w["level_progress"], skill_progress=repo, skill_lookup=w["lookup"]
        )
        with pytest.raises(SkillAlreadyPassed):
            await status.execute(
                UpdateSkillStatusCommand(
                    student_id="kid",
                    skill_id="s1",
                    program_id="prog",
                    new_status="PRACTICING",
                    updated_by="coach",
                )
            )
        row = await repo.get("kid", "s1")

    assert row is not None and row.status == "PASSED"


async def test_auto_approve_hands_a_level_up_into_a_retired_level_to_the_owner(
    real_db: Any,
) -> None:
    await _seed_curriculum(real_db)
    with tenant_scope(ACADEMY):
        w = _wire(real_db)
        await w["place"].execute(_place("L1"))
        await _pass(w, "s1")
        await _pass(w, "s2")
        await _rec(w)
        await real_db["skill_levels"].update_one({"level_id": "L3"}, {"$set": {"is_active": False}})

        async def display(_: str) -> dict[str, object]:
            return {}

        result = await AutoApproveLevelUps(
            recommendations=w["recs"],
            skill_progress=w["skill_progress"],
            skill_lookup=w["lookup"],
            review_level_up=w["review"],
        ).execute(display)
        rec = await w["recs"].get("rec-1")

    assert (result.approved, result.needs_owner, result.skipped) == (0, 1, 0)
    assert rec is not None and rec.status == "RECOMMENDED"


async def test_a_first_status_write_never_overwrites_a_pass_that_landed_first(
    real_db: Any,
) -> None:
    """No row at read time; a pass inserts one before the status write (F1)."""
    await _seed_curriculum(real_db)
    with tenant_scope(ACADEMY):
        w = _wire(real_db)
        await w["place"].execute(_place("L1"))
        await real_db["student_skill_progress"].delete_one({"student_id": "kid", "skill_id": "s1"})
        repo = w["skill_progress"]
        read = repo.get

        async def read_then_tap(student_id: str, skill_id: str) -> Any:
            row = await read(student_id, skill_id)
            repo.get = read
            await _pass(w, skill_id)
            return row

        repo.get = read_then_tap
        status = UpdateSkillStatus(
            level_progress=w["level_progress"], skill_progress=repo, skill_lookup=w["lookup"]
        )
        with pytest.raises(SkillAlreadyPassed):
            await status.execute(
                UpdateSkillStatusCommand(
                    student_id="kid",
                    skill_id="s1",
                    program_id="prog",
                    new_status="PRACTICING",
                    updated_by="coach",
                )
            )
        row = await repo.get("kid", "s1")

    assert row is not None and row.status == "PASSED"
    assert await real_db["student_skill_progress"].count_documents({"skill_id": "s1"}) == 1


async def test_placement_refuses_a_student_the_academy_does_not_have(real_db: Any) -> None:
    """F3: an unknown id (or another academy's) gets no level rows at all."""
    await _seed_curriculum(real_db)
    with tenant_scope(ACADEMY):
        w = _wire(real_db)
        place = PlaceStudentInLevel(
            level_progress=w["level_progress"],
            skill_progress=w["skill_progress"],
            skill_lookup=w["lookup"],
            recommendations=w["recs"],
            enrollment_lookup=_Live(unknown=frozenset({"kid"})),
        )
        with pytest.raises(StudentNotFound):
            await place.execute(_place("L1"))

    assert await real_db["student_level_progress"].count_documents({}) == 0
    assert await real_db["student_skill_progress"].count_documents({}) == 0
