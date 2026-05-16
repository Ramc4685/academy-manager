"""EnrollmentWriter."""

from __future__ import annotations

from backend.v2.contexts.enrollment.domain.models import Enrollment
from backend.v2.shared.tenancy import TenantScopedRepository


class MongoEnrollmentWriter(TenantScopedRepository):
    collection_name = "enrollments"

    async def create(self, enrollment: Enrollment) -> None:
        doc = enrollment.model_dump(mode="python")
        await self._insert_one({k: v for k, v in doc.items() if k != "academy_id"})

    async def update_status(self, enrollment_id: str, status: str) -> None:
        await self._update_one(
            {"enrollment_id": enrollment_id}, {"$set": {"status": status}}
        )

    @staticmethod
    def _to_domain(doc: dict[str, object]) -> Enrollment:
        return Enrollment(
            enrollment_id=str(doc["enrollment_id"]),
            academy_id=str(doc["academy_id"]),
            session_id=str(doc["session_id"]),
            student_id=str(doc["student_id"]),
            status=doc.get("status", "active"),  # type: ignore[arg-type]
        )

    async def get(self, enrollment_id: str) -> Enrollment | None:
        doc = await self._find_one({"enrollment_id": enrollment_id})
        return self._to_domain(doc) if doc else None
