"""Scheduled enrollment actions.

These records are durable work items for enrollment lifecycle changes that
must run outside the original request, such as fixed-date pause resumes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel, Field

ScheduledActionStatus = Literal[
    "pending",
    "succeeded",
    "blocked_capacity",
    "failed",
    "cancelled",
]
ScheduledActionType = Literal["resume_from_pause"]


class ScheduledEnrollmentAction(BaseModel):
    model_config = {"frozen": True}

    action_id: str
    academy_id: str
    action_type: ScheduledActionType
    enrollment_id: str
    pause_request_id: str
    run_at: datetime
    status: ScheduledActionStatus = "pending"
    attempt_count: int = Field(default=0, ge=0)
    last_attempt_at: datetime | None = None
    last_error: str | None = None
    created_at: datetime
    updated_at: datetime


class ScheduledEnrollmentActionRepository(Protocol):
    async def add(self, action: ScheduledEnrollmentAction) -> None: ...

    async def list_due(
        self, *, now: datetime, limit: int = 50
    ) -> list[ScheduledEnrollmentAction]: ...

    async def list_by_status(
        self,
        status: ScheduledActionStatus,
        *,
        limit: int = 50,
    ) -> list[ScheduledEnrollmentAction]: ...

    async def mark_succeeded(self, action_id: str, *, attempted_at: datetime) -> None: ...

    async def mark_blocked_capacity(self, action_id: str, *, attempted_at: datetime) -> None: ...

    async def mark_failed(
        self,
        action_id: str,
        *,
        attempted_at: datetime,
        error: str,
    ) -> None: ...

    async def cancel_pending_for_enrollment(self, enrollment_id: str, *, reason: str) -> int:
        """Cancel every still-pending action for an enrollment (issue #651).

        When the session a paused family was due to resume into is cancelled,
        the ``resume_from_pause`` action must not fire later and try to
        reserve a seat in a cancelled class. Returns the number cancelled.
        """
