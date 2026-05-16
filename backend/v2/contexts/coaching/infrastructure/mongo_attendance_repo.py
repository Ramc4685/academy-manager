"""Mongo AttendanceRepository."""

from __future__ import annotations

from pymongo.errors import DuplicateKeyError

from backend.v2.contexts.coaching.domain.errors import ConflictAttendanceExists
from backend.v2.contexts.coaching.domain.models import Attendance
from backend.v2.shared.tenancy import TenantScopedRepository


class MongoAttendanceRepository(TenantScopedRepository):
    collection_name = "attendance"

    @staticmethod
    def _to_domain(doc: dict[str, object]) -> Attendance:
        return Attendance(
            attendance_id=str(doc["attendance_id"]),
            academy_id=str(doc["academy_id"]),
            session_id=str(doc["session_id"]),
            student_id=str(doc["student_id"]),
            marked_by=str(doc["marked_by"]),
            marked_at=doc["marked_at"],  # type: ignore[arg-type]
            marked_at_client=doc.get("marked_at_client"),  # type: ignore[arg-type]
            status=doc["status"],  # type: ignore[arg-type]
            client_app_version=str(doc.get("client_app_version", "unknown")),
        )

    async def save(self, attendance: Attendance) -> None:
        """Insert the attendance row. On a unique-index collision
        (two offline devices marked the same session+student
        concurrently and both passed the use case's pre-insert
        existence check), translate to the domain
        `ConflictAttendanceExists` error so the BFF returns the
        documented 409 instead of a transient 500 — see
        docs/offline-policy.md conflict case #4."""
        try:
            await self._insert_one(
                {
                    "attendance_id": attendance.attendance_id,
                    "session_id": attendance.session_id,
                    "student_id": attendance.student_id,
                    "marked_by": attendance.marked_by,
                    "marked_at": attendance.marked_at,
                    "marked_at_client": attendance.marked_at_client,
                    "status": attendance.status,
                    "client_app_version": attendance.client_app_version,
                }
            )
        except DuplicateKeyError:
            existing = await self.find_existing(attendance.session_id, attendance.student_id)
            raise ConflictAttendanceExists(
                "another mutation raced ahead and recorded attendance",
                session_id=attendance.session_id,
                student_id=attendance.student_id,
                existing_attendance_id=existing.attendance_id if existing else None,
            ) from None

    async def find_existing(self, session_id: str, student_id: str) -> Attendance | None:
        doc = await self._find_one({"session_id": session_id, "student_id": student_id})
        return self._to_domain(doc) if doc else None

    async def find_by_attendance_id(self, attendance_id: str) -> Attendance | None:
        doc = await self._find_one({"attendance_id": attendance_id})
        return self._to_domain(doc) if doc else None
