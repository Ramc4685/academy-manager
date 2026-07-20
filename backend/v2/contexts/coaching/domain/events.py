"""Coaching domain events."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, model_validator

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
    name: Literal["Coaching.AttendanceMarked"] = "Coaching.AttendanceMarked"
    schema_version: Literal[1] = 1
    payload: AttendanceMarkedPayload


class SessionFeedbackPosted(DomainEvent):
    """Coach posted feedback for a student in a session.

    Carries flat identifying fields per the Phase 1 portal spec. The
    base ``DomainEvent`` requires ``aggregate_id`` / ``payload``; both are
    derived from the flat fields when not supplied so callers can construct
    the event with the flat fields alone.
    """

    name: Literal["Coaching.SessionFeedbackPosted"] = "Coaching.SessionFeedbackPosted"
    schema_version: Literal[1] = 1
    feedback_id: str
    session_id: str
    student_id: str
    coach_id: str
    academy_id: str

    @model_validator(mode="before")
    @classmethod
    def _fill_base_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data.setdefault("aggregate_id", data.get("feedback_id"))
            if "payload" not in data:
                data["payload"] = {
                    "feedback_id": data.get("feedback_id"),
                    "session_id": data.get("session_id"),
                    "student_id": data.get("student_id"),
                    "coach_id": data.get("coach_id"),
                    "academy_id": data.get("academy_id"),
                }
        return data
