"""Confirm an enrollment.

Triggered by Billing.PaymentSucceeded via the cross-context handler in
composition/event_handlers.py. Atomically reserves a seat in the session;
if at capacity, raises CapacityExceeded so Billing can auto-refund.

Idempotent on payment_id: replay of the event returns the existing
enrollment instead of double-confirming.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from pydantic import BaseModel

from backend.v2.contexts.enrollment.application.ports import (
    EnrollmentEventRepository,
    EnrollmentQuery,
    EnrollmentWriter,
    SessionWriter,
    StudentWriter,
)
from backend.v2.contexts.enrollment.domain.errors import CapacityExceeded
from backend.v2.contexts.enrollment.domain.events import (
    CapacityExceeded as CapacityExceededEvent,
)
from backend.v2.contexts.enrollment.domain.events import (
    CapacityExceededPayload,
    EnrollmentConfirmed,
    EnrollmentConfirmedPayload,
    EnrollmentLifecycleEvent,
)
from backend.v2.contexts.enrollment.domain.models import Enrollment, Student
from backend.v2.shared.events import Outbox
from backend.v2.shared.idempotency import IdempotencyStore, idempotent
from backend.v2.shared.ids import new_ulid


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
        academy_id: Callable[[], str],
        enrollment_events: EnrollmentEventRepository | None = None,
        clock=lambda: datetime.now(UTC),
    ) -> None:
        self._sessions = sessions
        self._enrollments = enrollments
        self._enrollment_query = enrollment_query
        self._students = students
        self._outbox = outbox
        self._idempotency_store = idempotency_store
        self._academy_id = academy_id
        self._enrollment_events = enrollment_events
        self._now = clock

    @idempotent(
        key_from=lambda self, cmd: f"confirm_enrollment:{cmd.payment_id}",
        result_type=ConfirmEnrollmentResult,
    )
    async def execute(self, cmd: ConfirmEnrollmentCommand) -> ConfirmEnrollmentResult:
        # Request-time tenant via the injected provider — never a boot-time value.
        academy_id = self._academy_id()
        reserved = await self._sessions.try_reserve_seat(cmd.session_id)
        if not reserved:
            await self._outbox.append(
                CapacityExceededEvent(
                    aggregate_id=cmd.session_id,
                    academy_id=academy_id,
                    payload=CapacityExceededPayload(
                        session_id=cmd.session_id,
                        parent_id=cmd.parent_id,
                        student_id=None,
                        payment_id=cmd.payment_id,
                    ),
                )
            )
            raise CapacityExceeded("session is full", session_id=cmd.session_id)

        student_id = str(new_ulid())
        student = Student(
            student_id=student_id,
            academy_id=academy_id,
            parent_id=cmd.parent_id,
            full_name=f"{cmd.student_first_name} {cmd.student_last_name}".strip(),
        )
        await self._students.upsert(student)

        enrollment = Enrollment(
            enrollment_id=str(new_ulid()),
            academy_id=academy_id,
            session_id=cmd.session_id,
            student_id=student_id,
            status="active",
        )
        await self._enrollments.create(enrollment)
        now = self._now()
        if self._enrollment_events is not None:
            await self._enrollment_events.record(
                EnrollmentLifecycleEvent(
                    event_id=str(new_ulid()),
                    academy_id=academy_id,
                    event_type="created",
                    enrollment_id=enrollment.enrollment_id,
                    session_id=cmd.session_id,
                    student_id=student_id,
                    actor_id=cmd.parent_id,
                    reason="checkout_confirmed",
                    effective_at=now,
                    occurred_at=now,
                    billing_result=cmd.payment_id,
                )
            )

        await self._outbox.append(
            EnrollmentConfirmed(
                aggregate_id=enrollment.enrollment_id,
                academy_id=academy_id,
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
