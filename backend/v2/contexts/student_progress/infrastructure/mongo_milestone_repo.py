"""Mongo ``student_milestones``: one row per student per celebration (L5B).

``student_milestones_one_per_key_uq`` (migration 0241) makes the write
idempotent at the database: the upsert inserts once and every repeat matches
the existing row and changes nothing. Two writers racing on the same key can
both miss and one gets a duplicate-key error, which means the row is there.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pymongo.errors import DuplicateKeyError

from backend.v2.contexts.student_progress.domain.milestones import StudentMilestone
from backend.v2.shared.tenancy import TenantScopedRepository
from backend.v2.shared.time.mongo import ensure_utc


class MongoStudentMilestoneRepository(TenantScopedRepository):
    collection_name = "student_milestones"

    async def record(self, milestone: StudentMilestone) -> None:
        try:
            await self._update_one(
                {"student_id": milestone.student_id, "milestone_key": milestone.milestone_key},
                {
                    "$setOnInsert": {
                        "kind": milestone.kind,
                        "count": milestone.count,
                        "reached_at": milestone.reached_at,
                        "recorded_at": datetime.now(UTC),
                    }
                },
                upsert=True,
            )
        except DuplicateKeyError:
            return

    async def delete(self, student_id: str, milestone_key: str) -> None:
        await self._delete_one({"student_id": student_id, "milestone_key": milestone_key})

    async def list_for_student(self, student_id: str) -> list[StudentMilestone]:
        cursor = self._find_many({"student_id": student_id}, sort=[("reached_at", 1)])
        return [self._to_domain(doc) async for doc in cursor]

    @staticmethod
    def _to_domain(doc: dict[str, Any]) -> StudentMilestone:
        return StudentMilestone(
            student_id=str(doc["student_id"]),
            milestone_key=str(doc["milestone_key"]),
            kind=doc["kind"],
            count=int(doc["count"]),
            reached_at=ensure_utc(doc["reached_at"]),
        )
