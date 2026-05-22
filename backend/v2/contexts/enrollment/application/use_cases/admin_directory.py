"""Admin directory read use cases for enrollment-owned people data."""

from __future__ import annotations

import base64
import json
import re
import unicodedata
from datetime import date, datetime
from typing import Literal, Protocol

from pydantic import BaseModel, Field

DuesStatus = Literal["current", "due", "overdue"]


class AdminStudentCursor(BaseModel):
    model_config = {"frozen": True}

    full_name_key: str = Field(min_length=1)
    student_id: str = Field(min_length=1)


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
    attendance_rate: float | None = None
    dues_status: DuesStatus = "current"


class AdminStudentDetail(AdminStudentSummary):
    model_config = {"frozen": True}

    date_of_birth: date | None = None
    level: str | None = None
    notes: str | None = None
    parent_phone: str | None = None
    parent_details: str | None = None


class UpdateAdminStudentCommand(BaseModel):
    model_config = {"frozen": True}

    full_name: str | None = Field(default=None, min_length=1, max_length=120)
    date_of_birth: date | None = None
    level: str | None = Field(default=None, max_length=80)
    status: str | None = Field(default=None, max_length=32)
    parent_id: str | None = Field(default=None, min_length=1, max_length=120)
    notes: str | None = Field(default=None, max_length=2000)
    actor_id: str = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=500)


class AdminStudentPage(BaseModel):
    model_config = {"frozen": True}

    students: list[AdminStudentSummary]
    next_cursor: str | None = None


def full_name_key(value: str) -> str:
    """Return the stable sort/search key shared by admin student cursors."""
    normalized = unicodedata.normalize("NFKD", value)
    ascii_folded = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", ascii_folded.lower()).strip()


def encode_student_cursor(full_name_key_value: str, student_id: str) -> str:
    payload = {"full_name_key": full_name_key_value, "student_id": student_id}
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_student_cursor(value: str) -> AdminStudentCursor:
    try:
        padded = value + ("=" * (-len(value) % 4))
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))
        return AdminStudentCursor(**payload)
    except Exception as exc:
        raise ValueError("Malformed student cursor") from exc


class AdminStudentDirectoryQuery(Protocol):
    async def list_admin_students(
        self,
        *,
        search: str | None,
        status: str | None,
        limit: int,
        cursor: str | None,
    ) -> AdminStudentPage: ...


class AdminStudentDetailQuery(Protocol):
    async def get_admin_student(self, student_id: str) -> AdminStudentDetail | None: ...


class AdminStudentWriter(Protocol):
    async def update_admin_student(
        self,
        student_id: str,
        command: UpdateAdminStudentCommand,
    ) -> AdminStudentDetail | None: ...


class ListAdminStudents:
    def __init__(self, students: AdminStudentDirectoryQuery) -> None:
        self._students = students

    async def execute(
        self,
        *,
        search: str | None = None,
        status: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> AdminStudentPage:
        return await self._students.list_admin_students(
            search=search,
            status=status,
            limit=limit,
            cursor=cursor,
        )


class GetAdminStudent:
    def __init__(self, students: AdminStudentDetailQuery) -> None:
        self._students = students

    async def execute(self, student_id: str) -> AdminStudentDetail:
        from backend.v2.contexts.enrollment.domain.errors import StudentNotFound

        student = await self._students.get_admin_student(student_id)
        if student is None:
            raise StudentNotFound("student not found")
        return student


class UpdateAdminStudent:
    def __init__(self, students: AdminStudentWriter) -> None:
        self._students = students

    async def execute(
        self,
        student_id: str,
        command: UpdateAdminStudentCommand,
    ) -> AdminStudentDetail:
        from backend.v2.contexts.enrollment.domain.errors import StudentNotFound

        updated = await self._students.update_admin_student(student_id, command)
        if updated is None:
            raise StudentNotFound("student not found")
        return updated
