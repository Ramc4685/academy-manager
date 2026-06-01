"""Coach session feedback — create + list.

A coach posts free-text feedback (optionally rated 1-5) for a student in a
session. Only a coach assigned to the session may post (``SessionNotAssigned``,
403). On success the feedback row is saved and a
``Coaching.SessionFeedbackPosted`` event is appended to the outbox.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

from pydantic import BaseModel, Field

from backend.v2.contexts.coaching.application.ports import SessionFeedbackRepository
from backend.v2.contexts.coaching.domain.errors import SessionNotAssigned
from backend.v2.contexts.coaching.domain.events import SessionFeedbackPosted
from backend.v2.contexts.coaching.domain.models import SessionFeedback
from backend.v2.shared.events import Outbox
from backend.v2.shared.ids import new_ulid
from backend.v2.shared.tenancy import TenantContextUnset, current_academy_id


def _resolve_academy_id() -> str:
    """Best-effort tenant id for the feedback row + event.

    The persisted document is tenant-scoped by the repository regardless;
    this value carries the academy onto the domain model and the emitted
    event when the tenant ContextVar is set.
    """
    try:
        return current_academy_id()
    except TenantContextUnset:
        return ""


class CoachAssignmentLookup(Protocol):
    async def is_coach_assigned(self, coach_id: str, session_id: str) -> bool: ...


class CreateFeedbackCommand(BaseModel):
    model_config = {"frozen": True}

    session_id: str
    occurrence_id: str | None = None
    student_id: str
    body: str
    rating: int | None = Field(default=None, ge=1, le=5)


class CreateSessionFeedback:
    def __init__(
        self,
        feedback_repo: SessionFeedbackRepository,
        assignment_lookup: CoachAssignmentLookup,
        outbox: Outbox,
        clock=lambda: datetime.now(UTC),
    ) -> None:
        self._feedback = feedback_repo
        self._assignments = assignment_lookup
        self._outbox = outbox
        self._now = clock

    async def execute(self, cmd: CreateFeedbackCommand, coach_id: str) -> SessionFeedback:
        # 1. Guard: coach must be assigned to the session.
        if not await self._assignments.is_coach_assigned(coach_id, cmd.session_id):
            raise SessionNotAssigned(
                "session not assigned to this coach",
                session_id=cmd.session_id,
                coach_id=coach_id,
            )

        # 2. Build the feedback row (new ULID; academy_id from the saved doc
        # is injected by the tenant-scoped repository, but the domain model
        # carries it explicitly too — resolved via the outbox event below).
        feedback = SessionFeedback(
            feedback_id=new_ulid(),
            academy_id="",  # placeholder; repo scopes the stored doc
            session_id=cmd.session_id,
            occurrence_id=cmd.occurrence_id,
            coach_id=coach_id,
            student_id=cmd.student_id,
            body=cmd.body,
            rating=cmd.rating,
            created_at=self._now(),
        )

        # 3. Persist.
        await self._feedback.save(feedback)

        # 4. Emit the domain event.
        await self._outbox.append(
            SessionFeedbackPosted(
                feedback_id=feedback.feedback_id,
                session_id=feedback.session_id,
                student_id=feedback.student_id,
                coach_id=feedback.coach_id,
                academy_id=feedback.academy_id,
            )
        )

        # 5. Return.
        return feedback


class ListSessionFeedback:
    def __init__(self, feedback_repo: SessionFeedbackRepository) -> None:
        self._feedback = feedback_repo

    async def execute(self, session_id: str) -> list[SessionFeedback]:
        return await self._feedback.list_for_session(session_id)
