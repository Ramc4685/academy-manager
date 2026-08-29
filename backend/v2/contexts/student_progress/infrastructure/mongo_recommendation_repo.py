"""Mongo LevelUpRecommendationRepository."""

from __future__ import annotations

from datetime import datetime

from backend.v2.contexts.student_progress.domain.models import LevelUpRecommendation
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
            }
        )

    async def update_status(
        self,
        rec_id: str,
        status: str,
        reviewed_by: str | None,
        reviewed_at: datetime | None,
        rejection_reason: str | None,
        *,
        expected_status: str | None = None,
    ) -> bool:
        filter_: dict[str, object] = {"rec_id": rec_id}
        if expected_status is not None:
            # Compare-and-set: a replayed review finds nothing to match and
            # reports False, so the caller can skip its side effects.
            filter_["status"] = expected_status
        result = await self._update_one(
            filter_,
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
                "status": {"$in": ["RECOMMENDED", "APPROVED"]},
            }
        )
        return self._to_domain(doc) if doc else None

    async def list_pending(self) -> list[LevelUpRecommendation]:
        cursor = self._find_many(
            {"status": "RECOMMENDED"},
            sort=[("recommended_at", 1)],
        )
        return [self._to_domain(doc) async for doc in cursor]
