"""Coaching domain events."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from backend.v2.shared.events.base import DomainEvent


class AttendanceMarkedPayload(BaseModel):
    model_config = {"frozen": True}

    attendance_id: str
    occurrence_id: str
    session_id: str
    student_id: str
    marked_by: str
    marked_at: datetime
    status: Literal["present", "absent", "late"]


class AttendanceMarked(DomainEvent):
    name: Literal["Coaching.AttendanceMarked"] = "Coaching.AttendanceMarked"  # type: ignore[assignment]
    schema_version: Literal[1] = 1  # type: ignore[assignment]
    payload: AttendanceMarkedPayload  # type: ignore[assignment]
