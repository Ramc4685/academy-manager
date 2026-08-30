"""Compare-and-set contract for the level-up recommendation repository.

The use-case tests drive hand-written fakes, so the guarantee they assert is
only as good as the fake. These exercise the real Mongo repository: the review
decision must land exactly once, and never across a tenant boundary.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.contexts.student_progress.domain.models import LevelUpRecommendation
from backend.v2.contexts.student_progress.infrastructure.mongo_recommendation_repo import (
    MongoLevelUpRecommendationRepository,
)
from backend.v2.shared.tenancy.context import tenant_scope

_NOW = datetime(2026, 8, 20, 9, 0, tzinfo=UTC)


def _pending(rec_id: str = "rec-1") -> LevelUpRecommendation:
    # academy_id is injected by the repo from the active tenant scope.
    return LevelUpRecommendation(
        rec_id=rec_id,
        academy_id="",
        student_id="student-1",
        from_level_id="lvl-1",
        to_level_id="lvl-2",
        program_id="prog-1",
        status="RECOMMENDED",
        recommended_by="coach-1",
        recommended_at=_NOW,
    )


@pytest.mark.asyncio
async def test_first_review_applies_and_the_replay_is_refused(db, acad) -> None:
    repo = MongoLevelUpRecommendationRepository(db)
    await repo.save(_pending())

    applied = await repo.update_status(
        "rec-1", "APPROVED", "admin-1", _NOW, None, expected_status="RECOMMENDED"
    )
    assert applied is True

    replayed = await repo.update_status(
        "rec-1", "REJECTED", "admin-2", _NOW, "changed my mind", expected_status="RECOMMENDED"
    )
    assert replayed is False

    stored = await repo.get("rec-1")
    assert stored is not None
    assert stored.status == "APPROVED"
    assert stored.reviewed_by == "admin-1"
    assert stored.rejection_reason is None


@pytest.mark.asyncio
async def test_review_of_a_missing_recommendation_is_refused(db, acad) -> None:
    repo = MongoLevelUpRecommendationRepository(db)

    applied = await repo.update_status(
        "no-such-rec", "APPROVED", "admin-1", _NOW, None, expected_status="RECOMMENDED"
    )

    assert applied is False


@pytest.mark.asyncio
async def test_review_from_another_academy_is_refused(db, acad, other_acad) -> None:
    repo = MongoLevelUpRecommendationRepository(db)
    with tenant_scope(acad):
        await repo.save(_pending())

    with tenant_scope(other_acad):
        applied = await repo.update_status(
            "rec-1", "APPROVED", "intruder", _NOW, None, expected_status="RECOMMENDED"
        )

    assert applied is False
    with tenant_scope(acad):
        stored = await repo.get("rec-1")
    assert stored is not None
    assert stored.status == "RECOMMENDED"
    assert stored.reviewed_by is None


@pytest.mark.asyncio
async def test_an_approved_recommendation_still_blocks_a_new_one(db, acad) -> None:
    """Why the CAS matters: APPROVED counts as an active recommendation."""
    repo = MongoLevelUpRecommendationRepository(db)
    await repo.save(_pending())
    await repo.update_status(
        "rec-1", "APPROVED", "admin-1", _NOW, None, expected_status="RECOMMENDED"
    )

    active = await repo.get_active_for_student("student-1", "prog-1")

    assert active is not None
    assert active.rec_id == "rec-1"
