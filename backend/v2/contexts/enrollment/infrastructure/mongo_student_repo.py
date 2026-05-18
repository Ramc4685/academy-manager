"""Mongo StudentQuery."""

from __future__ import annotations

from backend.v2.contexts.enrollment.application.use_cases.admin_directory import (
    AdminStudentSummary,
)
from backend.v2.contexts.enrollment.domain.models import Student
from backend.v2.shared.tenancy import TenantScopedRepository, current_academy_id


class MongoStudentRepository(TenantScopedRepository):
    collection_name = "students"

    @staticmethod
    def _to_domain(doc: dict[str, object]) -> Student:
        return Student(
            student_id=str(doc["student_id"]),
            academy_id=str(doc["academy_id"]),
            parent_id=str(doc["parent_id"]),
            full_name=str(doc["full_name"]),
        )

    async def by_ids(self, student_ids: list[str]) -> list[Student]:
        if not student_ids:
            return []
        cursor = self._find_many({"student_id": {"$in": student_ids}})
        return [self._to_domain(doc) async for doc in cursor]

    @staticmethod
    def _summary_id(doc: dict[str, object]) -> str:
        return str(doc.get("student_id") or doc.get("_id"))

    @classmethod
    def _to_admin_summary(
        cls,
        doc: dict[str, object],
        *,
        active_session_count: int,
        last_seen_at: object | None,
    ) -> AdminStudentSummary:
        first = str(doc.get("first_name") or "").strip()
        last = str(doc.get("last_name") or "").strip()
        full_name = str(doc.get("full_name") or f"{first} {last}".strip() or "Unnamed student")
        return AdminStudentSummary(
            student_id=cls._summary_id(doc),
            full_name=full_name,
            parent_id=str(doc.get("parent_id") or doc.get("parent_user_id") or ""),
            status=str(doc.get("status") or "active"),
            active_session_count=active_session_count,
            last_seen_at=last_seen_at,  # type: ignore[arg-type]
        )

    async def list_admin_students(self) -> list[AdminStudentSummary]:
        academy_id = current_academy_id()
        cursor = self._find_many({}, sort=[("full_name", 1), ("last_name", 1), ("first_name", 1)])
        students: list[AdminStudentSummary] = []
        async for doc in cursor:
            student_id = self._summary_id(doc)
            active_session_count = await self._db["enrollments"].count_documents(
                {
                    "academy_id": academy_id,
                    "student_id": student_id,
                    "status": "active",
                }
            )
            latest_attendance = await self._db["attendance"].find_one(
                {
                    "academy_id": academy_id,
                    "student_id": student_id,
                },
                sort=[("marked_at", -1)],
            )
            students.append(
                self._to_admin_summary(
                    doc,
                    active_session_count=active_session_count,
                    last_seen_at=latest_attendance.get("marked_at") if latest_attendance else None,
                )
            )
        return students
