"""Admin directory read use cases for enrollment-owned people data."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from pydantic import BaseModel


class AdminStudentSummary(BaseModel):
    model_config = {"frozen": True}

    student_id: str
    full_name: str
    parent_id: str
    parent_name: str | None = None
    parent_email: str | None = None
    status: str
    active_session_count: int = 0
    last_seen_at: datetime | None = None


class AdminStudentDirectoryQuery(Protocol):
    async def list_admin_students(self) -> list[AdminStudentSummary]: ...


class ListAdminStudents:
    def __init__(self, students: AdminStudentDirectoryQuery) -> None:
        self._students = students

    async def execute(self) -> list[AdminStudentSummary]:
        return await self._students.list_admin_students()
