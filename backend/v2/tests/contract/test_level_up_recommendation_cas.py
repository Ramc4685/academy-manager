"""Compare-and-set contract for the level-up recommendation repository.

The use-case tests drive hand-written fakes, so the guarantee they assert is
only as good as the fake. These exercise the real Mongo repository: the review
decision must land exactly once, never across a tenant boundary, and (issue
#548) the claim that reserves a row before any side effect must be held by at
most one reviewer at a time.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

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


# ---------------------------------------------------------------------------
# Claim / release (issue #548)
# ---------------------------------------------------------------------------

_LEASE = timedelta(minutes=10)


@pytest.mark.asyncio
async def test_only_one_reviewer_can_claim_a_recommendation(db, acad) -> None:
    """The claim is what stops approve and reject from both taking effect."""
    repo = MongoLevelUpRecommendationRepository(db)
    await repo.save(_pending())

    approving = await repo.claim("rec-1", "APPROVING", _NOW, lease=_LEASE)
    rejecting = await repo.claim("rec-1", "REJECTING", _NOW, lease=_LEASE)

    assert approving is True
    assert rejecting is False
    stored = await repo.get("rec-1")
    assert stored is not None
    assert stored.status == "APPROVING"
    assert stored.claimed_at is not None


@pytest.mark.asyncio
async def test_a_decided_recommendation_cannot_be_claimed(db, acad) -> None:
    repo = MongoLevelUpRecommendationRepository(db)
    await repo.save(_pending())
    await repo.update_status(
        "rec-1", "APPROVED", "admin-1", _NOW, None, expected_status="RECOMMENDED"
    )

    assert await repo.claim("rec-1", "REJECTING", _NOW, lease=_LEASE) is False


@pytest.mark.asyncio
async def test_a_claim_past_its_lease_can_be_taken_over(db, acad) -> None:
    """A reviewer whose process died must not park the row for good — there
    is no recovery job, the next reviewer's claim is the recovery."""
    repo = MongoLevelUpRecommendationRepository(db)
    await repo.save(_pending())
    await repo.claim("rec-1", "APPROVING", _NOW, lease=_LEASE)

    still_fresh = await repo.claim("rec-1", "REJECTING", _NOW + _LEASE, lease=_LEASE)
    expired = await repo.claim(
        "rec-1", "REJECTING", _NOW + _LEASE + timedelta(seconds=1), lease=_LEASE
    )

    assert still_fresh is False
    assert expired is True
    stored = await repo.get("rec-1")
    assert stored is not None
    assert stored.status == "REJECTING"


@pytest.mark.asyncio
async def test_releasing_a_claim_makes_the_row_immediately_reviewable(db, acad) -> None:
    repo = MongoLevelUpRecommendationRepository(db)
    await repo.save(_pending())
    await repo.claim("rec-1", "APPROVING", _NOW, lease=_LEASE)

    released = await repo.release("rec-1", claim_status="APPROVING")

    assert released is True
    stored = await repo.get("rec-1")
    assert stored is not None
    assert stored.status == "RECOMMENDED"
    assert stored.claimed_at is None
    assert await repo.claim("rec-1", "REJECTING", _NOW, lease=_LEASE) is True


@pytest.mark.asyncio
async def test_releasing_a_claim_someone_else_took_over_is_a_no_op(db, acad) -> None:
    repo = MongoLevelUpRecommendationRepository(db)
    await repo.save(_pending())
    await repo.claim("rec-1", "REJECTING", _NOW, lease=_LEASE)

    released = await repo.release("rec-1", claim_status="APPROVING")

    assert released is False
    stored = await repo.get("rec-1")
    assert stored is not None
    assert stored.status == "REJECTING"


@pytest.mark.asyncio
async def test_a_claim_from_another_academy_is_refused(db, acad, other_acad) -> None:
    repo = MongoLevelUpRecommendationRepository(db)
    with tenant_scope(acad):
        await repo.save(_pending())

    with tenant_scope(other_acad):
        claimed = await repo.claim("rec-1", "APPROVING", _NOW, lease=_LEASE)

    assert claimed is False
    with tenant_scope(acad):
        stored = await repo.get("rec-1")
    assert stored is not None
    assert stored.status == "RECOMMENDED"


@pytest.mark.asyncio
async def test_a_claimed_recommendation_still_blocks_a_new_one(db, acad) -> None:
    """A review in flight holds the student's slot exactly as a pending one
    does — otherwise the claim window is a window for a duplicate."""
    repo = MongoLevelUpRecommendationRepository(db)
    await repo.save(_pending())
    await repo.claim("rec-1", "APPROVING", _NOW, lease=_LEASE)

    active = await repo.get_active_for_student("student-1", "prog-1")
    listed = await repo.list_active_for_students(["student-1"], "prog-1")

    assert active is not None
    assert active.rec_id == "rec-1"
    assert [rec.rec_id for rec in listed] == ["rec-1"]


@pytest.mark.asyncio
async def test_a_claimed_recommendation_stays_in_the_admin_queue(db, acad) -> None:
    """Shown as in progress rather than vanishing mid-review."""
    repo = MongoLevelUpRecommendationRepository(db)
    await repo.save(_pending())
    await repo.claim("rec-1", "REJECTING", _NOW, lease=_LEASE)

    assert [rec.rec_id for rec in await repo.list_pending()] == ["rec-1"]
    assert [rec.rec_id for rec in await repo.list_pending_for_student("student-1")] == ["rec-1"]
