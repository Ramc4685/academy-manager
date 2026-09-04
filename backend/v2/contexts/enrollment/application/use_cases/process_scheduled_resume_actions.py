"""Process due scheduled enrollment resume actions."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from pydantic import BaseModel

from backend.v2.contexts.enrollment.application.use_cases.billing_deferrals import (
    BillingDeferralRepository,
)
from backend.v2.contexts.enrollment.application.use_cases.scheduled_actions import (
    ScheduledEnrollmentActionRepository,
)
from backend.v2.contexts.enrollment.domain.errors import CapacityExceeded, SessionNotEnrollable


class ResumeEnrollmentRunner(Protocol):
    async def execute(
        self,
        enrollment_id: str,
        *,
        actor_id: str | None = None,
        reason: str | None = None,
        close_billing_deferral: bool = True,
    ) -> None: ...


class ProcessScheduledResumeActionsResult(BaseModel):
    model_config = {"frozen": True}

    processed: int = 0
    succeeded: int = 0
    blocked_capacity: int = 0
    blocked_session_cancelled: int = 0
    failed: int = 0


class ProcessScheduledResumeActions:
    """Resolve scheduled `resume_from_pause` actions.

    `ResumeEnrollmentRunner.execute` (Slice B) already toggles the parent's
    app-owned `autopay_enrollment_status` back to `active` internally — this
    worker no longer resumes a Stripe subscription; there is none to resume.
    """

    def __init__(
        self,
        *,
        scheduled_actions: ScheduledEnrollmentActionRepository,
        resume_enrollment: ResumeEnrollmentRunner,
        billing_deferrals: BillingDeferralRepository | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._scheduled_actions = scheduled_actions
        self._resume_enrollment = resume_enrollment
        self._billing_deferrals = billing_deferrals
        self._now = clock

    async def execute(
        self,
        *,
        now: datetime | None = None,
        limit: int = 50,
    ) -> ProcessScheduledResumeActionsResult:
        attempted_at = now or self._now()
        actions = await self._scheduled_actions.list_due(now=attempted_at, limit=limit)
        succeeded = 0
        blocked_capacity = 0
        blocked_session_cancelled = 0
        failed = 0

        for action in actions:
            try:
                await self._resume_enrollment.execute(
                    action.enrollment_id,
                    actor_id="system",
                    reason="scheduled resume from approved pause",
                    close_billing_deferral=False,
                )
            except CapacityExceeded:
                await self._scheduled_actions.mark_blocked_capacity(
                    action.action_id,
                    attempted_at=attempted_at,
                )
                blocked_capacity += 1
                continue
            except SessionNotEnrollable:
                # Issue #651: the class was cancelled while the family was
                # paused. Terminal, and recorded under its own reason rather
                # than as "blocked_capacity" — an admin reading "session is
                # full" would go looking for a capacity problem (#610).
                await self._scheduled_actions.mark_failed(
                    action.action_id,
                    attempted_at=attempted_at,
                    error="session_cancelled",
                )
                blocked_session_cancelled += 1
                continue

            try:
                if self._billing_deferrals is not None:
                    await self._billing_deferrals.close_active_for_enrollment(
                        action.enrollment_id,
                        closed_at=attempted_at,
                        closed_by="system",
                        reason="resume_succeeded",
                    )
                await self._scheduled_actions.mark_succeeded(
                    action.action_id,
                    attempted_at=attempted_at,
                )
                succeeded += 1
            except Exception as exc:
                await self._scheduled_actions.mark_failed(
                    action.action_id,
                    attempted_at=attempted_at,
                    error=str(exc),
                )
                failed += 1

        return ProcessScheduledResumeActionsResult(
            processed=len(actions),
            succeeded=succeeded,
            blocked_capacity=blocked_capacity,
            blocked_session_cancelled=blocked_session_cancelled,
            failed=failed,
        )
