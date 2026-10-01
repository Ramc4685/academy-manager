"""Student BFF response DTOs (UIM12)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class StudentScheduleEntryView(BaseModel):
    occurrence_id: str
    session_id: str
    session_title: str
    location: str | None = None
    start_at: datetime
    end_at: datetime
    status: str
    coach_name: str | None = None
    # "regular" (standing enrollment) or "makeup" / "trial" for a one-time
    # approved attendance (issue #1038).
    source: Literal["regular", "makeup", "trial"] = "regular"


class StudentScheduleResponse(BaseModel):
    entries: list[StudentScheduleEntryView]
    total: int
    limit: int
    offset: int


class StudentMeView(BaseModel):
    student_id: str
    full_name: str
    academy_id: str
    academy_name: str
    level: str | None = None
