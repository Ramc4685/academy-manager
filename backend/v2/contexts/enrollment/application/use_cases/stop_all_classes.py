"""Stop every class for a student in one action (issue #698).

Composes over the existing per-enrollment ``WithdrawEnrollment`` use case
rather than writing a bulk status update. A bespoke bulk write would bypass
the status CAS, the seat-release pairing (``SEAT_HOLDING`` only) and the
per-enrollment ``EnrollmentBillingSync`` call that ``WithdrawEnrollment``
already gets right — that is exactly how a family ends up billed for a class
they will not attend. See the departures design contract §5.3.

One lifecycle event is recorded PER ENROLLMENT (by ``WithdrawEnrollment``
itself), never one event for the whole batch, so a leaving report built over
``enrollment_events`` sees every departure individually.

Partial failure is deliberately not rolled back: each drop commits and bills
independently, and a failure on one enrollment must not undo (or block) the
drops that already succeeded. The caller sees exactly which enrollments
failed and why via ``StopAllClassesResult.results``.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel, Field

from backend.v2.contexts.enrollment.application.ports import WithdrawalOutcome
from backend.v2.contexts.enrollment.application.use_cases.admin_writes import (
    WithdrawEnrollment,
    WithdrawEnrollmentCommand,
)
from backend.v2.contexts.enrollment.domain.models import Enrollment

log = logging.getLogger(__name__)


class StopAllClassesQuery(Protocol):
    async def departable_for_student(self, student_id: str) -> list[Enrollment]: ...


class StopAllClassesCommand(BaseModel):
    model_config = {"frozen": True}

    student_id: str
    effective_at: datetime
    #: Resolved by the caller (route) from the academy's
    #: ``EnrollmentDeparturePolicy.drop_default_outcome`` unless the admin
    #: chose otherwise. ``"credit"`` stays owner-gated per action by
    #: ``ensure_owner_for_withdrawal_credit`` at the route, exactly as a
    #: single-enrollment Drop is — this use case does not re-check it.
    outcome: WithdrawalOutcome
    reason: str = Field(min_length=1)
    actor_id: str


class EnrollmentStopResult(BaseModel):
    model_config = {"frozen": True}

    enrollment_id: str
    session_id: str
    outcome: Literal["dropped", "failed"]
    error: str | None = None


class StopAllClassesResult(BaseModel):
    model_config = {"frozen": True}

    student_id: str
    results: list[EnrollmentStopResult]

    @property
    def dropped_count(self) -> int:
        return sum(1 for r in self.results if r.outcome == "dropped")

    @property
    def failed_count(self) -> int:
        return sum(1 for r in self.results if r.outcome == "failed")


class StopAllClasses:
    """One date, one reason, one outcome, applied to every active/held/paused
    enrollment for a student. See module docstring."""

    def __init__(self, *, enrollments: StopAllClassesQuery, withdraw: WithdrawEnrollment) -> None:
        self._enrollments = enrollments
        self._withdraw = withdraw

    async def execute(self, cmd: StopAllClassesCommand) -> StopAllClassesResult:
        rows = await self._enrollments.departable_for_student(cmd.student_id)
        results: list[EnrollmentStopResult] = []
        for row in rows:
            try:
                await self._withdraw.execute(
                    WithdrawEnrollmentCommand(
                        enrollment_id=row.enrollment_id,
                        effective_at=cmd.effective_at,
                        outcome=cmd.outcome,
                        actor_id=cmd.actor_id,
                        reason=cmd.reason,
                    )
                )
                results.append(
                    EnrollmentStopResult(
                        enrollment_id=row.enrollment_id,
                        session_id=row.session_id,
                        outcome="dropped",
                    )
                )
            except Exception as exc:  # noqa: BLE001 - partial failure must be visible, not swallowed
                log.exception(
                    "stop_all_classes_enrollment_failed",
                    extra={"student_id": cmd.student_id, "enrollment_id": row.enrollment_id},
                )
                results.append(
                    EnrollmentStopResult(
                        enrollment_id=row.enrollment_id,
                        session_id=row.session_id,
                        outcome="failed",
                        error=str(exc),
                    )
                )
        return StopAllClassesResult(student_id=cmd.student_id, results=results)
