"""Confirm an enrollment.

Triggered by Billing.PaymentSucceeded via the cross-context handler in
composition/event_handlers.py. Atomically reserves a seat in the session;
if at capacity, raises CapacityExceeded so Billing can auto-refund.

Idempotent on payment_id: replay of the event returns the existing
enrollment instead of double-confirming.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel
from ulid import ULID

from backend.v2.contexts.enrollment.application.ports import (
    EnrollmentQuery,
    EnrollmentWriter,
    SessionWriter,
    StudentWriter,
)
from backend.v2.contexts.enrollment.domain.errors import CapacityExceeded
from backend.v2.contexts.enrollment.domain.events import (
    CapacityExceeded as CapacityExceededEvent,
    CapacityExceededPayload,
    EnrollmentConfirmed,
    EnrollmentConfirmedPayload,
)
from backend.v2.contexts.enrollment.domain.models import Enrollment, Student
from backend.v2.shared.events import Outbox
from backend.v2.shared.idempotency import IdempotencyStore, idempotent


class ConfirmEnrollmentCommand(BaseModel):
    model_config = {"frozen": True}

    payment_id: str
    parent_id: str
    session_id: str
    student_first_name: str
    student_last_name: str


class ConfirmEnrollmentResult(BaseModel):
    model_config = {"frozen": True}

    enrollment_id: str
    student_id: str


class ConfirmEnrollment:
    def __init__(
        self,
        *,
        sessions: SessionWriter,
        enrollments: EnrollmentWriter,
        enrollment_query: EnrollmentQuery,
        students: StudentWriter,
        outbox: Outbox,
        idempotency_store: IdempotencyStore,
        academy_id: str,
        clock=lambda: datetime.now(timezone.utc),
    ) -> None:
        self._sessions = sessions
        self._enrollments = enrollments
        self._enrollment_query = enrollment_query
        self._students = students
        self._outbox = outbox
        self._idempotency_store = idempotency_store
        self._academy_id = academy_id
        self._now = clock

    @idempotent(
        key_from=lambda self, cmd: f"confirm_enrollment:{cmd.payment_id}",
        result_type=ConfirmEnrollmentResult,
    )
    async def execute(self, cmd: ConfirmEnrollmentCommand) -> ConfirmEnrollmentResult:
        reserved = await self._sessions.try_reserve_seat(cmd.session_id)
        if not reserved:
            await self._outbox.append(
                CapacityExceededEvent(
                    aggregate_id=cmd.session_id,
                    academy_id=self._academy_id,
                    payload=CapacityExceededPayload(
                        session_id=cmd.session_id,
                        parent_id=cmd.parent_id,
                        student_id=None,
                        payment_id=cmd.payment_id,
                    ),
                )
            )
            raise CapacityExceeded("session is full", session_id=cmd.session_id)

        student_id = str(ULID())
        student = Student(
            student_id=student_id,
            academy_id=self._academy_id,
            parent_id=cmd.parent_id,
            full_name=f"{cmd.student_first_name} {cmd.student_last_name}".strip(),
        )
        await self._students.upsert(student)

        enrollment = Enrollment(
            enrollment_id=str(ULID()),
            academy_id=self._academy_id,
            session_id=cmd.session_id,
            student_id=student_id,
            status="active",
        )
        await self._enrollments.create(enrollment)

        await self._outbox.append(
            EnrollmentConfirmed(
                aggregate_id=enrollment.enrollment_id,
                academy_id=self._academy_id,
                payload=EnrollmentConfirmedPayload(
                    enrollment_id=enrollment.enrollment_id,
                    session_id=cmd.session_id,
                    student_id=student_id,
                    parent_id=cmd.parent_id,
                ),
            )
        )
        return ConfirmEnrollmentResult(
            enrollment_id=enrollment.enrollment_id,
            student_id=student_id,
        )
