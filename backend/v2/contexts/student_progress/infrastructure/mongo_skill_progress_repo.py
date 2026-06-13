"""Mongo StudentSkillProgressRepository."""

from __future__ import annotations

from backend.v2.contexts.student_progress.domain.models import StudentSkillProgress
from backend.v2.shared.tenancy import TenantScopedRepository

_IN_PROGRESS_STATUSES = ["INTRODUCED", "LEARNING", "PRACTICING", "TEST_READY", "NEEDS_REVIEW"]


class MongoStudentSkillProgressRepository(TenantScopedRepository):
    collection_name = "student_skill_progress"

    @staticmethod
    def _to_domain(doc: dict[str, object]) -> StudentSkillProgress:
        return StudentSkillProgress(
            skill_progress_id=str(doc["skill_progress_id"]),
            academy_id=str(doc["academy_id"]),
            student_id=str(doc["student_id"]),
            skill_id=str(doc["skill_id"]),
            level_id=str(doc["level_id"]),
            program_id=str(doc["program_id"]),
            status=doc["status"],  # type: ignore[arg-type]
            introduced_at=doc.get("introduced_at"),  # type: ignore[arg-type]
            last_updated_at=doc["last_updated_at"],  # type: ignore[arg-type]
            last_updated_by=str(doc["last_updated_by"]),
        )

    async def save(self, skill_progress: StudentSkillProgress) -> None:
        await self._insert_one(
            {
                "skill_progress_id": skill_progress.skill_progress_id,
                "student_id": skill_progress.student_id,
                "skill_id": skill_progress.skill_id,
                "level_id": skill_progress.level_id,
                "program_id": skill_progress.program_id,
                "status": skill_progress.status,
                "introduced_at": skill_progress.introduced_at,
                "last_updated_at": skill_progress.last_updated_at,
                "last_updated_by": skill_progress.last_updated_by,
            }
        )

    async def upsert(self, skill_progress: StudentSkillProgress) -> StudentSkillProgress:
        await self._update_one(
            {"student_id": skill_progress.student_id, "skill_id": skill_progress.skill_id},
            {
                "$set": {
                    "skill_progress_id": skill_progress.skill_progress_id,
                    "student_id": skill_progress.student_id,
                    "skill_id": skill_progress.skill_id,
                    "level_id": skill_progress.level_id,
                    "program_id": skill_progress.program_id,
                    "status": skill_progress.status,
                    "introduced_at": skill_progress.introduced_at,
                    "last_updated_at": skill_progress.last_updated_at,
                    "last_updated_by": skill_progress.last_updated_by,
                }
            },
            upsert=True,
        )
        saved = await self.get(skill_progress.student_id, skill_progress.skill_id)
        if saved is None:  # pragma: no cover - impossible unless Mongo write failed silently
            raise RuntimeError("skill progress upsert did not persist a row")
        return saved

    async def get(self, student_id: str, skill_id: str) -> StudentSkillProgress | None:
        doc = await self._find_one({"student_id": student_id, "skill_id": skill_id})
        return self._to_domain(doc) if doc else None

    async def list_for_student_level(
        self, student_id: str, level_id: str
    ) -> list[StudentSkillProgress]:
        cursor = self._find_many(
            {"student_id": student_id, "level_id": level_id},
            sort=[("skill_id", 1)],
        )
        return [self._to_domain(doc) async for doc in cursor]

    async def list_passed_for_student_level(
        self, student_id: str, level_id: str
    ) -> list[StudentSkillProgress]:
        cursor = self._find_many(
            {"student_id": student_id, "level_id": level_id, "status": "PASSED"},
        )
        return [self._to_domain(doc) async for doc in cursor]

    async def list_recent_for_student(
        self, student_id: str, limit: int = 10
    ) -> list[StudentSkillProgress]:
        cursor = self._find_many(
            {"student_id": student_id},
            sort=[("last_updated_at", -1)],
            limit=limit,
        )
        return [self._to_domain(doc) async for doc in cursor]

    async def list_in_progress_for_student(self, student_id: str) -> list[StudentSkillProgress]:
        cursor = self._find_many(
            {"student_id": student_id, "status": {"$in": _IN_PROGRESS_STATUSES}},
            sort=[("last_updated_at", -1)],
        )
        return [self._to_domain(doc) async for doc in cursor]

    async def list_for_students(
        self, student_ids: list[str], level_id: str
    ) -> list[StudentSkillProgress]:
        if not student_ids:
            return []
        cursor = self._find_many(
            {"student_id": {"$in": list(student_ids)}, "level_id": level_id},
            sort=[("student_id", 1), ("skill_id", 1)],
        )
        return [self._to_domain(doc) async for doc in cursor]
