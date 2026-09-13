"""Mongo LevelUpRecommendationRepository."""

from __future__ import annotations

from datetime import datetime, timedelta

from backend.v2.contexts.student_progress.domain.models import (
    ACTIVE_LEVEL_UP_STATUSES,
    CLAIMABLE_LEVEL_UP_STATUSES,
    LevelUpRecommendation,
)
from backend.v2.shared.tenancy import TenantScopedRepository


class MongoLevelUpRecommendationRepository(TenantScopedRepository):
    collection_name = "level_up_recommendations"

    @staticmethod
    def _to_domain(doc: dict[str, object]) -> LevelUpRecommendation:
        return LevelUpRecommendation(
            rec_id=str(doc["rec_id"]),
            academy_id=str(doc["academy_id"]),
            student_id=str(doc["student_id"]),
            from_level_id=str(doc["from_level_id"]),
            to_level_id=str(doc["to_level_id"]),
            program_id=str(doc["program_id"]),
            status=doc["status"],
            recommended_by=str(doc["recommended_by"]),
            recommended_at=doc["recommended_at"],
            reviewed_by=str(doc["reviewed_by"]) if doc.get("reviewed_by") else None,
            reviewed_at=doc.get("reviewed_at"),
            rejection_reason=str(doc["rejection_reason"]) if doc.get("rejection_reason") else None,
            claimed_at=doc.get("claimed_at"),
        )

    async def save(self, rec: LevelUpRecommendation) -> None:
        await self._insert_one(
            {
                "rec_id": rec.rec_id,
                "student_id": rec.student_id,
                "from_level_id": rec.from_level_id,
                "to_level_id": rec.to_level_id,
                "program_id": rec.program_id,
                "status": rec.status,
                "recommended_by": rec.recommended_by,
                "recommended_at": rec.recommended_at,
                "reviewed_by": rec.reviewed_by,
                "reviewed_at": rec.reviewed_at,
                "rejection_reason": rec.rejection_reason,
                "claimed_at": rec.claimed_at,
            }
        )

    async def claim(
        self,
        rec_id: str,
        claim_status: str,
        claimed_at: datetime,
        *,
        lease: timedelta,
    ) -> bool:
        """Compare-and-set an undecided recommendation into ``claim_status``.

        Matches either a row still waiting for a decision, or a claim whose
        lease has run out — a reviewer that died mid-review must not park the
        row for good. ``claimed_at`` doubles as the lease clock and as the
        new stamp, so the filter and the write share one instant.
        """
        cutoff = claimed_at - lease
        result = await self._update_one(
            {
                "rec_id": rec_id,
                "$or": [
                    {"status": "RECOMMENDED"},
                    {
                        "status": {"$in": sorted(CLAIMABLE_LEVEL_UP_STATUSES - {"RECOMMENDED"})},
                        "claimed_at": {"$lt": cutoff},
                    },
                ],
            },
            {"$set": {"status": claim_status, "claimed_at": claimed_at}},
        )
        return bool(result.matched_count)

    async def release(self, rec_id: str, *, claim_status: str) -> bool:
        """Give an unused claim back, so the admin can retry immediately."""
        result = await self._update_one(
            {"rec_id": rec_id, "status": claim_status},
            {"$set": {"status": "RECOMMENDED", "claimed_at": None}},
        )
        return bool(result.matched_count)

    async def update_status(
        self,
        rec_id: str,
        status: str,
        reviewed_by: str | None,
        reviewed_at: datetime | None,
        rejection_reason: str | None,
        *,
        expected_status: str,
    ) -> bool:
        """Compare-and-set the review decision.

        The status is part of the filter, so a replayed review matches
        nothing and reports ``False``; only the racer that finds the
        recommendation still in ``expected_status`` records the decision.
        """
        result = await self._update_one(
            {"rec_id": rec_id, "status": expected_status},
            {
                "$set": {
                    "status": status,
                    "reviewed_by": reviewed_by,
                    "reviewed_at": reviewed_at,
                    "rejection_reason": rejection_reason,
                }
            },
        )
        return bool(result.matched_count)

    async def get(self, rec_id: str) -> LevelUpRecommendation | None:
        doc = await self._find_one({"rec_id": rec_id})
        return self._to_domain(doc) if doc else None

    async def get_active_for_student(
        self, student_id: str, program_id: str
    ) -> LevelUpRecommendation | None:
        doc = await self._find_one(
            {
                "student_id": student_id,
                "program_id": program_id,
                "status": {"$in": sorted(ACTIVE_LEVEL_UP_STATUSES)},
            }
        )
        return self._to_domain(doc) if doc else None

    async def list_active_for_students(
        self, student_ids: list[str], program_id: str
    ) -> list[LevelUpRecommendation]:
        if not student_ids:
            return []
        cursor = self._find_many(
            {
                "student_id": {"$in": student_ids},
                "program_id": program_id,
                "status": {"$in": sorted(ACTIVE_LEVEL_UP_STATUSES)},
            }
        )
        return [self._to_domain(doc) async for doc in cursor]

    async def list_pending(self) -> list[LevelUpRecommendation]:
        cursor = self._find_many(
            {"status": {"$in": sorted(CLAIMABLE_LEVEL_UP_STATUSES)}},
            sort=[("recommended_at", 1)],
        )
        return [self._to_domain(doc) async for doc in cursor]

    async def list_recommended_for_student(self, student_id: str) -> list[LevelUpRecommendation]:
        """Rows still waiting for a first decision — deliberately not claimed ones.

        Issue #548: the expiry use case compare-and-sets every row this
        returns out of ``RECOMMENDED``, and a row a reviewer is holding
        (``APPROVING``/``REJECTING``) must be left to that reviewer — taking
        it would either no-op the CAS or, worse, reject a row whose
        certificate is already being written.
        """
        cursor = self._find_many(
            {"student_id": student_id, "status": "RECOMMENDED"},
            sort=[("recommended_at", 1)],
        )
        return [self._to_domain(doc) async for doc in cursor]
