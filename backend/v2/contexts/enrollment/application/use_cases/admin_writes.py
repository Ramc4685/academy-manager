"""Admin write use cases for Enrollment — sessions + roster + waitlist.

CreateSession, EditSession, CancelSession, EditRoster, TransferEnrollment,
PauseEnrollment, ResumeEnrollment, AdminPromoteFromWaitlist, JoinWaitlist,
SkipWaitlist, RemoveFromWaitlist.

Each emits the right domain event so downstream handlers (waitlist
promotion on cancellation, comms notifications, etc.) react.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

from backend.v2.contexts.enrollment.application.ports import (
    EnrollmentLifecycleBillingPort,
    EnrollmentEventRepository,
    EnrollmentQuery,
    EnrollmentWriter,
    SessionWriter,
    StudentQuery,
    StudentWriter,
    WaitlistRepository,
)
from backend.v2.contexts.enrollment.domain.errors import (
    EnrollmentNotFound,
    SessionNotFound,
)
from backend.v2.contexts.enrollment.domain.events import (
    EnrollmentCancelled,
    EnrollmentCancelledPayload,
    EnrollmentLifecycleEvent,
)
from backend.v2.contexts.enrollment.domain.models import Enrollment, Session, Student
from backend.v2.contexts.enrollment.domain.models_extra import WaitlistEntry
from backend.v2.shared.events import Outbox
from backend.v2.shared.ids import new_ulid

Clock = Callable[[], datetime]


async def _record_lifecycle_event(
    enrollment_events: EnrollmentEventRepository | None,
    *,
    academy_id: str,
    event_type: str,
    student_id: str,
    effective_at: datetime,
    occurred_at: datetime,
    enrollment_id: str | None = None,
    waitlist_id: str | None = None,
    session_id: str | None = None,
    from_session_id: str | None = None,
    to_session_id: str | None = None,
    actor_id: str | None = None,
    reason: str | None = None,
    billing_policy: str | None = None,
    billing_result: str | None = None,
    credit_id: str | None = None,
    refund_id: str | None = None,
    metadata: dict[str, str] | None = None,
) -> None:
    if enrollment_events is None:
        return
    await enrollment_events.record(
        EnrollmentLifecycleEvent(
            event_id=str(new_ulid()),
            academy_id=academy_id,
            event_type=event_type,  # type: ignore[arg-type]
            enrollment_id=enrollment_id,
            waitlist_id=waitlist_id,
            session_id=session_id,
            from_session_id=from_session_id,
            to_session_id=to_session_id,
            student_id=student_id,
            actor_id=actor_id,
            reason=reason,
            effective_at=effective_at,
            occurred_at=occurred_at,
            billing_policy=billing_policy,
            billing_result=billing_result,
            credit_id=credit_id,
            refund_id=refund_id,
            metadata=metadata or {},
        )
    )


# -- Session writes ------------------------------------------------------


class CreateSessionCommand(BaseModel):
    model_config = {"frozen": True}
    coach_id: str
    title: str
    location: str
    start_at: datetime
    end_at: datetime
    capacity: int = Field(ge=1)


class CreateSession:
    def __init__(self, *, sessions: SessionWriter, academy_id: str) -> None:
        self._sessions = sessions
        self._academy_id = academy_id

    async def execute(self, cmd: CreateSessionCommand) -> Session:
        session = Session(
            session_id=str(new_ulid()),
            academy_id=self._academy_id,
            coach_id=cmd.coach_id,
            title=cmd.title,
            location=cmd.location,
            start_at=cmd.start_at,
            end_at=cmd.end_at,
            capacity=cmd.capacity,
            status="scheduled",
        )
        await self._sessions.create(session)
        return session


class EditSessionCommand(BaseModel):
    model_config = {"frozen": True}
    session_id: str
    coach_id: str | None = None
    title: str | None = None
    location: str | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    capacity: int | None = Field(default=None, ge=1)
    actor_id: str | None = None
    reason: str | None = None


class EditSession:
    def __init__(self, *, sessions: SessionWriter) -> None:
        self._sessions = sessions

    async def execute(self, cmd: EditSessionCommand) -> Session:
        current = await self._sessions.get(cmd.session_id)
        if current is None:
            raise SessionNotFound("session missing", session_id=cmd.session_id)

        update: dict[str, object] = {}
        for field_name in ("coach_id", "title", "location", "start_at", "end_at", "capacity"):
            value = getattr(cmd, field_name)
            if value is not None:
                update[field_name] = value

        updated = current.model_copy(update=update)
        await self._sessions.update(updated)
        return updated


class CancelSessionCommand(BaseModel):
    model_config = {"frozen": True}
    session_id: str


class CancelSession:
    """Cancels a session + emits EnrollmentCancelled for each active enrollment.

    The waitlist-promotion handler reacts per cancellation. For session-wide
    cancellation we keep this simple — admin gets a confirmation modal in
    the UI before triggering this.
    """

    def __init__(
        self,
        *,
        sessions: SessionWriter,
        enrollments_query: EnrollmentQuery,
        enrollments_writer: EnrollmentWriter,
        outbox: Outbox,
        academy_id: str,
    ) -> None:
        self._sessions = sessions
        self._enrollments_q = enrollments_query
        self._enrollments_w = enrollments_writer
        self._outbox = outbox
        self._academy_id = academy_id

    async def execute(self, cmd: CancelSessionCommand) -> None:
        active = await self._enrollments_q.active_for_session(cmd.session_id)
        await self._sessions.update_status(cmd.session_id, "cancelled")
        for e in active:
            await self._enrollments_w.update_status(e.enrollment_id, "cancelled")
            await self._outbox.append(
                EnrollmentCancelled(
                    aggregate_id=e.enrollment_id,
                    academy_id=self._academy_id,
                    payload=EnrollmentCancelledPayload(
                        enrollment_id=e.enrollment_id,
                        session_id=cmd.session_id,
                        student_id=e.student_id,
                        reason="session_cancelled",
                    ),
                )
            )


# -- Roster + enrollment writes -----------------------------------------


class EditRosterAddCommand(BaseModel):
    model_config = {"frozen": True}
    session_id: str
    student_id: str
    parent_id: str
    full_name: str
    actor_id: str | None = None
    reason: str | None = None


class EditRosterAdd:
    """Admin manually adds a student to a session, bypassing checkout.

    Useful for academy comp seats / scholarships. Reserves a seat atomically
    via the same try_reserve_seat path used by ConfirmEnrollment.
    """

    def __init__(
        self,
        *,
        sessions: SessionWriter,
        enrollments: EnrollmentWriter,
        students: StudentWriter,
        academy_id: str,
        enrollment_events: EnrollmentEventRepository | None = None,
        clock: Clock = lambda: datetime.now(UTC),
    ) -> None:
        self._sessions = sessions
        self._enrollments = enrollments
        self._students = students
        self._academy_id = academy_id
        self._enrollment_events = enrollment_events
        self._now = clock

    async def execute(self, cmd: EditRosterAddCommand) -> Enrollment:
        reserved = await self._sessions.try_reserve_seat(cmd.session_id)
        if not reserved:
            from backend.v2.contexts.enrollment.domain.errors import CapacityExceeded

            raise CapacityExceeded("session full", session_id=cmd.session_id)
        await self._students.upsert(
            Student(
                student_id=cmd.student_id,
                academy_id=self._academy_id,
                parent_id=cmd.parent_id,
                full_name=cmd.full_name,
            )
        )
        enrollment = Enrollment(
            enrollment_id=str(new_ulid()),
            academy_id=self._academy_id,
            session_id=cmd.session_id,
            student_id=cmd.student_id,
            status="active",
        )
        await self._enrollments.create(enrollment)
        now = self._now()
        await _record_lifecycle_event(
            self._enrollment_events,
            academy_id=self._academy_id,
            event_type="created",
            enrollment_id=enrollment.enrollment_id,
            session_id=cmd.session_id,
            student_id=cmd.student_id,
            actor_id=cmd.actor_id,
            reason=cmd.reason,
            effective_at=now,
            occurred_at=now,
        )
        return enrollment


class CancelEnrollmentCommand(BaseModel):
    model_config = {"frozen": True}
    enrollment_id: str
    event_type: Literal["cancelled", "removed"] = "cancelled"
    reason: str = Field(default="admin_cancel", min_length=1)
    effective_at: datetime | None = None
    actor_id: str | None = None


class CancelEnrollment:
    def __init__(
        self,
        *,
        enrollments: EnrollmentWriter,
        sessions: SessionWriter,
        outbox: Outbox,
        academy_id: str,
        enrollment_events: EnrollmentEventRepository | None = None,
        clock: Clock = lambda: datetime.now(UTC),
    ) -> None:
        self._enrollments = enrollments
        self._sessions = sessions
        self._outbox = outbox
        self._academy_id = academy_id
        self._enrollment_events = enrollment_events
        self._now = clock

    async def execute(self, cmd: CancelEnrollmentCommand) -> None:
        e = await self._enrollments.get(cmd.enrollment_id)
        if e is None:
            raise EnrollmentNotFound("enrollment missing", enrollment_id=cmd.enrollment_id)
        if e.status == "cancelled":
            return
        await self._enrollments.update_status(e.enrollment_id, "cancelled")
        now = self._now()
        await _record_lifecycle_event(
            self._enrollment_events,
            academy_id=self._academy_id,
            event_type=cmd.event_type,
            enrollment_id=e.enrollment_id,
            session_id=e.session_id,
            student_id=e.student_id,
            actor_id=cmd.actor_id,
            reason=cmd.reason,
            effective_at=cmd.effective_at or now,
            occurred_at=now,
        )
        await self._sessions.release_seat(e.session_id)
        cancel_reason: Literal["admin_cancel", "parent_cancel", "session_cancelled"]
        if cmd.reason in {"admin_cancel", "parent_cancel", "session_cancelled"}:
            cancel_reason = cmd.reason  # type: ignore[assignment]
        else:
            cancel_reason = "admin_cancel"
        await self._outbox.append(
            EnrollmentCancelled(
                aggregate_id=e.enrollment_id,
                academy_id=self._academy_id,
                payload=EnrollmentCancelledPayload(
                    enrollment_id=e.enrollment_id,
                    session_id=e.session_id,
                    student_id=e.student_id,
                    reason=cancel_reason,
                ),
            )
        )


class TransferEnrollmentCommand(BaseModel):
    model_config = {"frozen": True}
    enrollment_id: str
    target_session_id: str
    effective_at: datetime | None = None
    actor_id: str | None = None
    reason: str | None = None


class TransferEnrollment:
    """Move an active or paused enrollment to another session.

    The target seat is reserved first; only after the enrollment points at the
    new session do we release the old session seat.
    """

    def __init__(
        self,
        *,
        enrollments: EnrollmentWriter,
        sessions: SessionWriter,
        enrollment_events: EnrollmentEventRepository | None = None,
        billing: EnrollmentLifecycleBillingPort | None = None,
        clock: Clock = lambda: datetime.now(UTC),
    ) -> None:
        self._enrollments = enrollments
        self._sessions = sessions
        self._enrollment_events = enrollment_events
        self._billing = billing
        self._now = clock

    async def execute(self, cmd: TransferEnrollmentCommand) -> Enrollment:
        enrollment = await self._enrollments.get(cmd.enrollment_id)
        if enrollment is None:
            raise EnrollmentNotFound("enrollment missing", enrollment_id=cmd.enrollment_id)
        if enrollment.session_id == cmd.target_session_id:
            return enrollment
        reserved = await self._sessions.try_reserve_seat(cmd.target_session_id)
        if not reserved:
            from backend.v2.contexts.enrollment.domain.errors import CapacityExceeded

            raise CapacityExceeded("target session full", session_id=cmd.target_session_id)
        await self._enrollments.update_session(enrollment.enrollment_id, cmd.target_session_id)
        now = self._now()
        effective_at = cmd.effective_at or now
        billing_decision = {
            "billing_policy": None,
            "billing_result": None,
            "metadata": {},
        }
        if self._billing is not None and cmd.actor_id is not None:
            billing_decision = await self._billing.record_move_proration(
                enrollment=enrollment,
                from_session_id=enrollment.session_id,
                to_session_id=cmd.target_session_id,
                effective_at=effective_at,
                actor_id=cmd.actor_id,
                reason=cmd.reason,
            )
        await _record_lifecycle_event(
            self._enrollment_events,
            academy_id=enrollment.academy_id,
            event_type="moved",
            enrollment_id=enrollment.enrollment_id,
            session_id=cmd.target_session_id,
            from_session_id=enrollment.session_id,
            to_session_id=cmd.target_session_id,
            student_id=enrollment.student_id,
            actor_id=cmd.actor_id,
            reason=cmd.reason,
            effective_at=effective_at,
            occurred_at=now,
            billing_policy=billing_decision.get("billing_policy"),
            billing_result=billing_decision.get("billing_result"),
            metadata=billing_decision.get("metadata", {}),
        )
        await self._sessions.release_seat(enrollment.session_id)
        return enrollment.model_copy(update={"session_id": cmd.target_session_id})


class PauseEnrollmentCommand(BaseModel):
    model_config = {"frozen": True}
    enrollment_id: str
    effective_at: datetime | None = None
    actor_id: str | None = None
    reason: str | None = None


class PauseEnrollment:
    """Pause keeps the seat but marks the enrollment paused (no attendance
    expected). Resume returns to active without re-reserving a seat (the
    seat was held the whole time).
    """

    def __init__(
        self,
        enrollments: EnrollmentWriter,
        sessions: SessionWriter | None = None,
        students: StudentQuery | None = None,
        waitlist: WaitlistRepository | None = None,
        enrollment_events: EnrollmentEventRepository | None = None,
        clock: Clock = lambda: datetime.now(UTC),
    ) -> None:
        self._enrollments = enrollments
        self._sessions = sessions
        self._students = students
        self._waitlist = waitlist
        self._enrollment_events = enrollment_events
        self._now = clock

    async def execute(self, cmd: PauseEnrollmentCommand) -> None:
        e = await self._enrollments.get(cmd.enrollment_id)
        if e is None:
            raise EnrollmentNotFound("enrollment missing")
        if e.status == "paused":
            return
        await self._enrollments.update_status(e.enrollment_id, "paused")
        now = self._now()
        effective_at = cmd.effective_at or now
        waitlist_id: str | None = None
        if self._sessions is not None:
            await self._sessions.release_seat(e.session_id)
        if self._waitlist is not None:
            parent_id = ""
            if self._students is not None:
                students = await self._students.by_ids([e.student_id])
                if students:
                    parent_id = students[0].parent_id
            entry = WaitlistEntry(
                waitlist_id=str(new_ulid()),
                academy_id=e.academy_id,
                session_id=e.session_id,
                student_id=e.student_id,
                parent_id=parent_id,
                joined_at=now,
                status="waiting",
            )
            await self._waitlist.add(entry)
            waitlist_id = entry.waitlist_id
        await _record_lifecycle_event(
            self._enrollment_events,
            academy_id=e.academy_id,
            event_type="paused",
            enrollment_id=e.enrollment_id,
            waitlist_id=waitlist_id,
            session_id=e.session_id,
            student_id=e.student_id,
            actor_id=cmd.actor_id,
            reason=cmd.reason,
            effective_at=effective_at,
            occurred_at=now,
            billing_policy="release_seat_waitlist_stop_billing",
            billing_result="future_billing_stopped",
            metadata={"seat_policy": "released_to_waitlist"},
        )


class WithdrawEnrollmentCommand(BaseModel):
    model_config = {"frozen": True}
    enrollment_id: str
    effective_at: datetime
    outcome: Literal["credit", "refund", "adjustment"] = "credit"
    actor_id: str
    reason: str = Field(min_length=1)


class WithdrawEnrollment:
    def __init__(
        self,
        *,
        enrollments: EnrollmentWriter,
        enrollment_events: EnrollmentEventRepository | None = None,
        billing: EnrollmentLifecycleBillingPort | None = None,
        clock: Clock = lambda: datetime.now(UTC),
    ) -> None:
        self._enrollments = enrollments
        self._enrollment_events = enrollment_events
        self._billing = billing
        self._now = clock

    async def execute(self, cmd: WithdrawEnrollmentCommand) -> None:
        e = await self._enrollments.get(cmd.enrollment_id)
        if e is None:
            raise EnrollmentNotFound("enrollment missing")
        if e.status == "withdrawn":
            return
        now = self._now()
        billing_decision = {
            "billing_policy": f"withdrawal_{cmd.outcome}",
            "billing_result": "recorded",
            "metadata": {"outcome": cmd.outcome},
        }
        if self._billing is not None:
            billing_decision = await self._billing.record_withdrawal_decision(
                enrollment=e,
                outcome=cmd.outcome,
                effective_at=cmd.effective_at,
                actor_id=cmd.actor_id,
                reason=cmd.reason,
            )
        await self._enrollments.update_status(e.enrollment_id, "withdrawn")
        await _record_lifecycle_event(
            self._enrollment_events,
            academy_id=e.academy_id,
            event_type="withdrawn",
            enrollment_id=e.enrollment_id,
            session_id=e.session_id,
            student_id=e.student_id,
            actor_id=cmd.actor_id,
            reason=cmd.reason,
            effective_at=cmd.effective_at,
            occurred_at=now,
            billing_policy=billing_decision.get("billing_policy"),
            billing_result=billing_decision.get("billing_result"),
            credit_id=billing_decision.get("credit_id"),
            refund_id=billing_decision.get("refund_id"),
            metadata=billing_decision.get("metadata", {"outcome": cmd.outcome}),
        )


class ResumeEnrollment:
    def __init__(
        self,
        enrollments: EnrollmentWriter,
        enrollment_events: EnrollmentEventRepository | None = None,
        clock: Clock = lambda: datetime.now(UTC),
    ) -> None:
        self._enrollments = enrollments
        self._enrollment_events = enrollment_events
        self._now = clock

    async def execute(
        self,
        enrollment_id: str,
        *,
        actor_id: str | None = None,
        reason: str | None = None,
    ) -> None:
        e = await self._enrollments.get(enrollment_id)
        if e is None:
            raise EnrollmentNotFound("enrollment missing")
        if e.status != "paused":
            return
        await self._enrollments.update_status(e.enrollment_id, "active")
        now = self._now()
        await _record_lifecycle_event(
            self._enrollment_events,
            academy_id=e.academy_id,
            event_type="resumed",
            enrollment_id=e.enrollment_id,
            session_id=e.session_id,
            student_id=e.student_id,
            actor_id=actor_id,
            reason=reason,
            effective_at=now,
            occurred_at=now,
        )


# -- Waitlist writes ----------------------------------------------------


class JoinWaitlistCommand(BaseModel):
    model_config = {"frozen": True}
    session_id: str
    parent_id: str
    student_id: str
    actor_id: str | None = None
    reason: str | None = None


class JoinWaitlist:
    def __init__(
        self,
        *,
        waitlist: WaitlistRepository,
        academy_id: str,
        enrollment_events: EnrollmentEventRepository | None = None,
        clock: Clock = lambda: datetime.now(UTC),
    ) -> None:
        self._waitlist = waitlist
        self._academy_id = academy_id
        self._enrollment_events = enrollment_events
        self._now = clock

    async def execute(self, cmd: JoinWaitlistCommand) -> WaitlistEntry:
        now = self._now()
        entry = WaitlistEntry(
            waitlist_id=str(new_ulid()),
            academy_id=self._academy_id,
            session_id=cmd.session_id,
            student_id=cmd.student_id,
            parent_id=cmd.parent_id,
            joined_at=now,
            status="waiting",
        )
        await self._waitlist.add(entry)
        await _record_lifecycle_event(
            self._enrollment_events,
            academy_id=self._academy_id,
            event_type="waitlisted",
            waitlist_id=entry.waitlist_id,
            session_id=entry.session_id,
            student_id=entry.student_id,
            actor_id=cmd.actor_id,
            reason=cmd.reason,
            effective_at=now,
            occurred_at=now,
        )
        return entry


class SkipFromWaitlist:
    def __init__(self, waitlist: WaitlistRepository) -> None:
        self._waitlist = waitlist

    async def execute(self, waitlist_id: str) -> None:
        await self._waitlist.update_status(waitlist_id, "skipped")


class RemoveFromWaitlist:
    def __init__(self, waitlist: WaitlistRepository) -> None:
        self._waitlist = waitlist

    async def execute(self, waitlist_id: str) -> None:
        await self._waitlist.update_status(waitlist_id, "removed")
