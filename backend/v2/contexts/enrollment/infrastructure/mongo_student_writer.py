"""StudentWriter — upsert by student_id."""

from __future__ import annotations

from backend.v2.contexts.enrollment.domain.models import Student
from backend.v2.shared.tenancy import TenantScopedRepository


class MongoStudentWriter(TenantScopedRepository):
    collection_name = "students"

    async def upsert(self, student: Student) -> None:
        doc = student.model_dump(mode="python")
        await self._update_one(
            {"student_id": student.student_id},
            {"$set": {k: v for k, v in doc.items() if k != "academy_id"}},
            upsert=True,
        )
