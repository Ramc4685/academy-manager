"""Mongo AttendanceRepository."""

from __future__ import annotations

from pymongo.errors import DuplicateKeyError

from backend.v2.contexts.coaching.domain.errors import ConflictAttendanceExists
from backend.v2.contexts.coaching.domain.models import Attendance, CoachAttendance
from backend.v2.shared.tenancy import TenantScopedRepository


class MongoAttendanceRepository(TenantScopedRepository):
    collection_name = "attendance"

    @staticmethod
    def _to_domain(doc: dict[str, object]) -> Attendance:
        return Attendance(
            attendance_id=str(doc["attendance_id"]),
            academy_id=str(doc["academy_id"]),
            occurrence_id=str(doc["occurrence_id"]),
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
                    "occurrence_id": attendance.occurrence_id,
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
            existing = await self.find_existing(attendance.occurrence_id, attendance.student_id)
            raise ConflictAttendanceExists(
                "another mutation raced ahead and recorded attendance",
                session_id=attendance.session_id,
                occurrence_id=attendance.occurrence_id,
                student_id=attendance.student_id,
                existing_attendance_id=existing.attendance_id if existing else None,
            ) from None

    async def find_existing(self, occurrence_id: str, student_id: str) -> Attendance | None:
        doc = await self._find_one({"occurrence_id": occurrence_id, "student_id": student_id})
        return self._to_domain(doc) if doc else None

    async def find_by_attendance_id(self, attendance_id: str) -> Attendance | None:
        doc = await self._find_one({"attendance_id": attendance_id})
        return self._to_domain(doc) if doc else None


class MongoCoachAttendanceRepository(TenantScopedRepository):
    collection_name = "coach_attendance"

    @staticmethod
    def _to_domain(doc: dict[str, object]) -> CoachAttendance:
        return CoachAttendance(
            attendance_id=str(doc["attendance_id"]),
            academy_id=str(doc["academy_id"]),
            occurrence_id=str(doc["occurrence_id"]),
            coach_id=str(doc["coach_id"]),
            status=doc["status"],  # type: ignore[arg-type]
            role=doc.get("role", "lead"),  # type: ignore[arg-type]
            source=doc["source"],  # type: ignore[arg-type]
            marked_by=str(doc["marked_by"]),
            marked_at=doc["marked_at"],  # type: ignore[arg-type]
            rate_override_minor=(
                None if doc.get("rate_override_minor") is None else int(doc["rate_override_minor"])
            ),
            note=str(doc.get("note", "")),
        )

    async def upsert(self, row: CoachAttendance) -> CoachAttendance:
        await self._update_one(
            {"occurrence_id": row.occurrence_id, "coach_id": row.coach_id},
            {
                "$set": {
                    "attendance_id": row.attendance_id,
                    "occurrence_id": row.occurrence_id,
                    "coach_id": row.coach_id,
                    "status": row.status,
                    "role": row.role,
                    "source": row.source,
                    "marked_by": row.marked_by,
                    "marked_at": row.marked_at,
                    "rate_override_minor": row.rate_override_minor,
                    "note": row.note,
                }
            },
            upsert=True,
        )
        saved = await self.find_for_occurrence_coach(row.occurrence_id, row.coach_id)
        if saved is None:  # pragma: no cover - impossible unless Mongo write failed silently
            raise RuntimeError("coach attendance upsert did not persist a row")
        return saved

    async def find_for_occurrence_coach(
        self, occurrence_id: str, coach_id: str
    ) -> CoachAttendance | None:
        doc = await self._find_one({"occurrence_id": occurrence_id, "coach_id": coach_id})
        return self._to_domain(doc) if doc else None

    async def list_for_occurrences(self, occurrence_ids: list[str]) -> list[CoachAttendance]:
        if not occurrence_ids:
            return []
        cursor = self._find_many(
            {"occurrence_id": {"$in": occurrence_ids}},
            sort=[("marked_at", 1)],
        )
        return [self._to_domain(doc) async for doc in cursor]
