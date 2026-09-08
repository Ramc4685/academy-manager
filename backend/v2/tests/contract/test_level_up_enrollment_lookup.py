"""Contract tests for the enrollment-status adapter behind the level-up flow (#673).

The application tests drive fakes; these exercise the real Mongo reads the
adapter composes over: which enrollment statuses count as "live", the batch
read the queue uses, tenant scoping, and the recommendation repo's
per-student pending read the expiry use case relies on.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.composition.level_up_lifecycle import (
    compose_expire_level_up_recommendations,
    enrollment_status_lookup,
)
from backend.v2.composition.pathway import compose_student_progress
from backend.v2.contexts.student_progress.domain.models import LevelUpRecommendation
from backend.v2.contexts.student_progress.infrastructure.mongo_recommendation_repo import (
    MongoLevelUpRecommendationRepository,
)

_NOW = datetime(2026, 8, 20, 9, 0, tzinfo=UTC)


async def _enrollment(db, *, student_id: str, status: str, academy_id: str = "test-academy"):
    await db["enrollments"].insert_one(
        {
            "enrollment_id": f"enr-{student_id}-{status}-{academy_id}",
            "academy_id": academy_id,
            "session_id": "sess-1",
            "student_id": student_id,
            "status": status,
        }
    )


def _pending(rec_id: str, student_id: str, recommended_at: datetime = _NOW):
    return LevelUpRecommendation(
        rec_id=rec_id,
        academy_id="",
        student_id=student_id,
        from_level_id="lvl-1",
        to_level_id="lvl-2",
        program_id="prog-1",
        status="RECOMMENDED",
        recommended_by="coach-1",
        recommended_at=recommended_at,
    )


@pytest.mark.asyncio
async def test_only_active_and_paused_enrollments_count_as_live(db, acad) -> None:
    await _enrollment(db, student_id="st-active", status="active")
    await _enrollment(db, student_id="st-paused", status="paused")
    await _enrollment(db, student_id="st-cancelled", status="cancelled")
    await _enrollment(db, student_id="st-withdrawn", status="withdrawn")
    # Withdrawn from one session but still active on another: live.
    await _enrollment(db, student_id="st-mixed", status="withdrawn")
    await _enrollment(db, student_id="st-mixed", status="active")
    lookup = enrollment_status_lookup(db)

    assert await lookup.has_active_or_paused_enrollment("st-active") is True
    assert await lookup.has_active_or_paused_enrollment("st-paused") is True
    assert await lookup.has_active_or_paused_enrollment("st-cancelled") is False
    assert await lookup.has_active_or_paused_enrollment("st-withdrawn") is False
    assert await lookup.has_active_or_paused_enrollment("st-mixed") is True
    assert await lookup.has_active_or_paused_enrollment("st-unknown") is False

    live = await lookup.students_with_active_or_paused_enrollment(
        ["st-active", "st-paused", "st-cancelled", "st-withdrawn", "st-mixed", "st-unknown"]
    )
    assert live == {"st-active", "st-paused", "st-mixed"}
    assert await lookup.students_with_active_or_paused_enrollment([]) == set()


@pytest.mark.asyncio
async def test_lookup_never_sees_another_tenants_enrollment(db, acad) -> None:
    await _enrollment(db, student_id="st-elsewhere", status="active", academy_id="other-academy")
    lookup = enrollment_status_lookup(db)

    assert await lookup.has_active_or_paused_enrollment("st-elsewhere") is False
    assert await lookup.students_with_active_or_paused_enrollment(["st-elsewhere"]) == set()


@pytest.mark.asyncio
async def test_pending_for_student_is_scoped_and_ordered(db, acad) -> None:
    repo = MongoLevelUpRecommendationRepository(db)
    await repo.save(_pending("rec-later", "st-1", datetime(2026, 8, 21, tzinfo=UTC)))
    await repo.save(_pending("rec-earlier", "st-1", datetime(2026, 8, 19, tzinfo=UTC)))
    await repo.save(_pending("rec-other-student", "st-2"))
    await repo.update_status(
        "rec-later", "APPROVED", "admin-1", _NOW, None, expected_status="RECOMMENDED"
    )
    await repo.save(_pending("rec-latest", "st-1", datetime(2026, 8, 22, tzinfo=UTC)))
    await db["level_up_recommendations"].insert_one(
        {
            "rec_id": "rec-foreign",
            "academy_id": "other-academy",
            "student_id": "st-1",
            "from_level_id": "lvl-1",
            "to_level_id": "lvl-2",
            "program_id": "prog-1",
            "status": "RECOMMENDED",
            "recommended_by": "coach-9",
            "recommended_at": _NOW,
        }
    )

    rows = await repo.list_pending_for_student("st-1")

    assert [row.rec_id for row in rows] == ["rec-earlier", "rec-latest"]


@pytest.mark.asyncio
async def test_expiry_over_real_repos_closes_the_row_with_the_lifecycle_reason(db, acad) -> None:
    repo = MongoLevelUpRecommendationRepository(db)
    await repo.save(_pending("rec-1", "st-gone"))
    await _enrollment(db, student_id="st-gone", status="withdrawn")
    expire = compose_expire_level_up_recommendations(db)

    result = await expire.execute("st-gone")

    assert result.expired_rec_ids == ["rec-1"]
    row = await repo.get("rec-1")
    assert row is not None
    assert row.status == "REJECTED"
    assert row.rejection_reason == "enrollment_ended"
    assert row.reviewed_by == "system:enrollment_ended"
    assert await repo.list_pending() == []


def test_student_progress_composition_wires_the_enrollment_lookup(db) -> None:
    """The guard is only as good as its wiring: every production use case
    that consults enrollment lifecycle must get the real adapter."""
    comp = compose_student_progress(db)

    for use_case in (comp.recommend_level_up, comp.review_level_up, comp.get_level_up_queue):
        lookup = use_case._enrollments
        assert type(lookup).__name__ == "EnrollmentStatusAdapter", use_case
