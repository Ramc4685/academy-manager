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
        # Issue #697 (contract §2.4 T1 roster visibility): a held row stays
        # on the roster, marked "On hold until <return_on>" — a paused row
        # invisible on the roster but still blocking re-add was the #641
        # dead end, and held rows must not repeat it.
        active = await self._enrollments.for_session_in_statuses(session_id, ["active", "held"])
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
                    pending_cancellation_at=e.pending_cancellation_at,
                    hold_return_on=e.hold_return_on,
                )
            )
        return out
