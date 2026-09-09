"""Confirm an enrollment.

Triggered by Billing.PaymentSucceeded via the cross-context handler in
composition/event_handlers.py. Atomically reserves a seat in the session;
if at capacity, raises CapacityExceeded so Billing can auto-refund.

Idempotent on payment_id: replay of the event returns the existing
enrollment instead of double-confirming.
"""

from __future__ import annotations

import logging
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
from backend.v2.contexts.enrollment.application.seat_broker import SeatAcquisition, SeatBroker
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

log = logging.getLogger(__name__)


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
        seat_broker: SeatBroker | None = None,
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
        # Departures design contract §3.1: every caller that needs a seat
        # routes through SeatBroker.acquire so a checkout confirmation for a
        # class that is full only because held enrollments occupy it can
        # reclaim the longest-held hold instead of forcing an auto-refund.
        # Optional + a setter (production wiring injects this from main.py
        # via `set_seat_broker`, same as every other brokered use case).
        self._seat_broker = seat_broker
        self._now = clock

    def set_seat_broker(self, seat_broker: SeatBroker) -> None:
        self._seat_broker = seat_broker

    @idempotent(
        key_from=lambda self, cmd: f"confirm_enrollment:{cmd.payment_id}",
        result_type=ConfirmEnrollmentResult,
    )
    async def execute(self, cmd: ConfirmEnrollmentCommand) -> ConfirmEnrollmentResult:
        # Request-time tenant via the injected provider — never a boot-time value.
        academy_id = self._academy_id()
        acquisition: SeatAcquisition | None = None
        if self._seat_broker is not None:
            acquisition = await self._seat_broker.acquire(
                cmd.session_id, requested_by=f"checkout:{cmd.payment_id}"
            )
            reserved = acquisition.granted
        else:
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

        try:
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
        except BaseException:
            await self._release_quietly(cmd.session_id, acquisition)
            raise
        return ConfirmEnrollmentResult(
            enrollment_id=enrollment.enrollment_id,
            student_id=student_id,
        )

    async def _release_quietly(self, session_id: str, acquisition: SeatAcquisition | None) -> None:
        """Give a just-acquired seat back without masking the error being
        handled. When the seat came from ``SeatBroker.acquire`` compensation
        MUST go through ``SeatBroker.release`` rather than a bare
        ``sessions.release_seat`` — a reclaim-granted acquisition already
        dropped and emailed a different family for THEIR seat, and only the
        broker knows to record that as a ``hold_reclaim_orphaned`` event."""
        try:
            if self._seat_broker is not None and acquisition is not None:
                await self._seat_broker.release(acquisition)
            else:
                await self._sessions.release_seat(session_id)
        except Exception:
            log.exception(
                "confirm_enrollment_seat_release_failed", extra={"session_id": session_id}
            )
