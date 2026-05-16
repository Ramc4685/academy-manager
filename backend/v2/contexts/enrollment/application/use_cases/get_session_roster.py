"""Query: roster (enrollments + students) for a session."""

from __future__ import annotations

from backend.v2.contexts.enrollment.application.ports import (
    EnrollmentQuery,
    StudentQuery,
)
from backend.v2.contexts.enrollment.domain.models import RosterEntry


class GetSessionRoster:
    def __init__(self, enrollments: EnrollmentQuery, students: StudentQuery) -> None:
        self._enrollments = enrollments
        self._students = students

    async def execute(self, session_id: str) -> list[RosterEntry]:
        active = await self._enrollments.active_for_session(session_id)
        if not active:
            return []
        students = await self._students.by_ids([e.student_id for e in active])
        by_id = {s.student_id: s for s in students}
        out: list[RosterEntry] = []
        for e in active:
            s = by_id.get(e.student_id)
            if s is None:
                # Orphan enrollment — skip; do not crash. Logged out-of-band.
                continue
            out.append(
                RosterEntry(
                    enrollment_id=e.enrollment_id,
                    student_id=s.student_id,
                    full_name=s.full_name,
                    status=e.status,
                )
            )
        return out
