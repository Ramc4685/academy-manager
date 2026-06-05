"""Cross-context adapter: reads student data from enrollment context."""

from __future__ import annotations

from typing import Any


class EnrollmentStudentLookup:
    """Implements StudentLookup port by delegating to the enrollment student repo."""

    def __init__(self, students: Any) -> None:
        self._students = students

    async def get_student(self, student_id: str) -> object | None:
        return await self._students.get_admin_student(student_id)
