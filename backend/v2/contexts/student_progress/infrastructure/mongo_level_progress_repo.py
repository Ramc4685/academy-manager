"""Mongo StudentLevelProgressRepository."""

from __future__ import annotations

from datetime import datetime

from backend.v2.contexts.student_progress.domain.models import StudentLevelProgress
from backend.v2.shared.tenancy import TenantScopedRepository


class MongoStudentLevelProgressRepository(TenantScopedRepository):
    collection_name = "student_level_progress"

    @staticmethod
    def _to_domain(doc: dict[str, object]) -> StudentLevelProgress:
        return StudentLevelProgress(
            progress_id=str(doc["progress_id"]),
            academy_id=str(doc["academy_id"]),
            student_id=str(doc["student_id"]),
            program_id=str(doc["program_id"]),
            level_id=str(doc["level_id"]),
            status=doc["status"],
            started_at=doc["started_at"],
            completed_at=doc.get("completed_at"),
            created_at=doc["created_at"],
        )

    async def save(self, progress: StudentLevelProgress) -> None:
        await self._insert_one(
            {
                "progress_id": progress.progress_id,
                "student_id": progress.student_id,
                "program_id": progress.program_id,
                "level_id": progress.level_id,
                "status": progress.status,
                "started_at": progress.started_at,
                "completed_at": progress.completed_at,
                "created_at": progress.created_at,
            }
        )

    async def get_active(self, student_id: str, program_id: str) -> StudentLevelProgress | None:
        doc = await self._find_one(
            {"student_id": student_id, "program_id": program_id, "status": "active"}
        )
        return self._to_domain(doc) if doc else None

    async def get_by_id(self, progress_id: str) -> StudentLevelProgress | None:
        doc = await self._find_one({"progress_id": progress_id})
        return self._to_domain(doc) if doc else None

    async def complete(self, progress_id: str, completed_at: datetime) -> None:
        await self._update_one(
            {"progress_id": progress_id},
            {"$set": {"status": "completed", "completed_at": completed_at}},
        )

    async def list_for_student(self, student_id: str) -> list[StudentLevelProgress]:
        cursor = self._find_many(
            {"student_id": student_id},
            sort=[("started_at", 1)],
        )
        return [self._to_domain(doc) async for doc in cursor]

    async def list_active_for_students(
        self, student_ids: list[str], program_id: str
    ) -> list[StudentLevelProgress]:
        if not student_ids:
            return []
        cursor = self._find_many(
            {
                "student_id": {"$in": student_ids},
                "program_id": program_id,
                "status": "active",
            }
        )
        return [self._to_domain(doc) async for doc in cursor]
