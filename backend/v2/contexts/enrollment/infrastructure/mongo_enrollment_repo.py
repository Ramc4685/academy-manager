"""Mongo EnrollmentQuery."""

from __future__ import annotations

from datetime import date

from backend.v2.contexts.enrollment.domain.models import Enrollment
from backend.v2.shared.tenancy import TenantScopedRepository


class MongoEnrollmentRepository(TenantScopedRepository):
    collection_name = "enrollments"

    @staticmethod
    def _to_domain(doc: dict[str, object]) -> Enrollment:
        raw_return_on = doc.get("hold_return_on")
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
            pending_cancellation_at=doc.get("pending_cancellation_at"),
            hold_started_at=doc.get("hold_started_at"),
            hold_return_on=(
                date.fromisoformat(raw_return_on)
                if isinstance(raw_return_on, str)
                else raw_return_on
            ),
            hold_expires_at=doc.get("hold_expires_at"),
            hold_seq=doc.get("hold_seq", 0),
        )

    async def active_for_session(self, session_id: str) -> list[Enrollment]:
        cursor = self._find_many(
            {"session_id": session_id, "status": "active"},
            sort=[("enrollment_id", 1)],
        )
        return [self._to_domain(doc) async for doc in cursor]

    async def for_session_in_statuses(
        self, session_id: str, statuses: list[str]
    ) -> list[Enrollment]:
        # Issue #651: CancelSession reads active + paused so paused families
        # are cancelled (and their deferrals/resumes closed) with everyone else.
        cursor = self._find_many(
            {"session_id": session_id, "status": {"$in": list(statuses)}},
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

    async def active_or_paused_for_student(self, student_id: str) -> list[Enrollment]:
        """Live enrollments (active or paused) for one student.

        issue #651: the coach skill passport authorises by "is this student on
        a session I coach". Paused students keep their roster seat (issue
        #641) so they must stay reachable; cancelled / withdrawn rows are not.
        Kept separate from ``active_for_student`` because the parent schedule
        and digests deliberately exclude paused enrollments.
        """
        cursor = self._find_many(
            {"student_id": student_id, "status": {"$in": ["active", "paused"]}},
            sort=[("enrollment_id", 1)],
        )
        return [self._to_domain(doc) async for doc in cursor]

    async def departable_for_student(self, student_id: str) -> list[Enrollment]:
        """Issue #698: every row ``StopAllClasses`` can act on for a student —
        ``active``/``held`` (still hold a seat) plus ``paused`` (released its
        seat but still a live commitment, #641)."""
        cursor = self._find_many(
            {"student_id": student_id, "status": {"$in": ["active", "held", "paused"]}},
            sort=[("enrollment_id", 1)],
        )
        return [self._to_domain(doc) async for doc in cursor]

    async def student_ids_with_active_or_paused_enrollment(
        self, student_ids: list[str]
    ) -> set[str]:
        """Batch twin of ``active_or_paused_for_student`` (issue #673).

        One query for the whole level-up queue: returns the subset of
        ``student_ids`` that still holds a live (active or paused) enrollment.
        """
        if not student_ids:
            return set()
        cursor = self._find_many(
            {"student_id": {"$in": list(student_ids)}, "status": {"$in": ["active", "paused"]}},
        )
        return {str(doc["student_id"]) async for doc in cursor}
