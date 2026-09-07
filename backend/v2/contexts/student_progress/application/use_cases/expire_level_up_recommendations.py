"""Use case: expire pending level-up recommendations once a student stops attending.

Issue #673: a coach recommends a student, the family withdraws, and the row
sat in the admin queue forever — approvable, and a certificate would be
issued to a student who no longer attends. This runs from the
``Enrollment.EnrollmentCancelled`` handler and clears the row itself.

The recommendation is closed as ``REJECTED`` with ``rejection_reason`` set to
:data:`ENROLLMENT_ENDED_REASON` rather than a new ``EXPIRED`` status: the
recommendations collection carries a ``$jsonSchema`` status enum (migration
0133) and every reader (queue, active-recommendation guard, parent passport)
already treats ``REJECTED`` as closed, so no validator migration or new
read-side branch is needed. The reason string is the discriminator.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel

from backend.v2.contexts.student_progress.application.ports import (
    EnrollmentStatusLookup,
    LevelUpRecommendationRepository,
)

ENROLLMENT_ENDED_REASON = "enrollment_ended"
ENROLLMENT_ENDED_REVIEWER = "system:enrollment_ended"
PENDING_STATUS = "RECOMMENDED"


class ExpireLevelUpRecommendationsResult(BaseModel):
    model_config = {"frozen": True}
    student_id: str
    expired_rec_ids: list[str]
    skipped_still_enrolled: bool = False


class ExpireLevelUpRecommendations:
    def __init__(
        self,
        *,
        recommendations: LevelUpRecommendationRepository,
        enrollment_lookup: EnrollmentStatusLookup,
    ) -> None:
        self._recs = recommendations
        self._enrollments = enrollment_lookup

    async def execute(self, student_id: str) -> ExpireLevelUpRecommendationsResult:
        # One cancelled enrollment is not the end of attendance: a student on
        # two sessions who drops one, or a paused student whose seat was
        # handed on (PauseEnrollment also emits EnrollmentCancelled), is still
        # live. Only a student with no active-or-paused enrollment left is
        # expired.
        if await self._enrollments.has_active_or_paused_enrollment(student_id):
            return ExpireLevelUpRecommendationsResult(
                student_id=student_id, expired_rec_ids=[], skipped_still_enrolled=True
            )

        now = datetime.now(UTC)
        expired: list[str] = []
        for rec in await self._recs.list_pending_for_student(student_id):
            # Compare-and-set, same as an admin review: if an admin decided the
            # row between our read and this write, their decision stands.
            applied = await self._recs.update_status(
                rec.rec_id,
                "REJECTED",
                ENROLLMENT_ENDED_REVIEWER,
                now,
                ENROLLMENT_ENDED_REASON,
                expected_status=PENDING_STATUS,
            )
            if applied:
                expired.append(rec.rec_id)
        return ExpireLevelUpRecommendationsResult(student_id=student_id, expired_rec_ids=expired)
