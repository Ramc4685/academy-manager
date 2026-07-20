"""Mongo EnrollmentQuery."""

from __future__ import annotations

from backend.v2.contexts.enrollment.domain.models import Enrollment
from backend.v2.shared.tenancy import TenantScopedRepository


class MongoEnrollmentRepository(TenantScopedRepository):
    collection_name = "enrollments"

    @staticmethod
    def _to_domain(doc: dict[str, object]) -> Enrollment:
        return Enrollment(
            enrollment_id=str(doc["enrollment_id"]),
            academy_id=str(doc["academy_id"]),
            session_id=str(doc["session_id"]),
            student_id=str(doc["student_id"]),
            status=doc.get("status", "active"),
            enrolled_at=doc.get("enrolled_at"),
            created_at=doc.get("created_at"),
            registration_application_id=doc.get("registration_application_id"),
            registration_student_lock=doc.get("registration_student_lock"),
        )

    async def active_for_session(self, session_id: str) -> list[Enrollment]:
        cursor = self._find_many(
            {"session_id": session_id, "status": "active"},
            sort=[("enrollment_id", 1)],
        )
        return [self._to_domain(doc) async for doc in cursor]

    async def is_active(self, session_id: str, student_id: str) -> bool:
        doc = await self._find_one(
            {"session_id": session_id, "student_id": student_id, "status": "active"}
        )
        return doc is not None

    async def is_active_or_paused(self, session_id: str, student_id: str) -> bool:
        doc = await self._find_one(
            {
                "session_id": session_id,
                "student_id": student_id,
                "status": {"$in": ["active", "paused"]},
            }
        )
        return doc is not None

    async def active_for_student(self, student_id: str) -> list[Enrollment]:
        cursor = self._find_many(
            {"student_id": student_id, "status": "active"},
            sort=[("enrollment_id", 1)],
        )
        return [self._to_domain(doc) async for doc in cursor]
