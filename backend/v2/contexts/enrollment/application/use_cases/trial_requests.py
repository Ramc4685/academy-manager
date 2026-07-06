"""Parent-submitted trial class requests with conversion tracking (R3).

Parents request to try a class before enrolling — either for an existing
student or a prospective child not yet in the system. Admin approves
(assigning a specific occurrence) or denies. Approval writes NO billing
call: trial fee handling is out of v1 scope (no-charge trials only). Only
existing-student trials create a one-time ``OccurrenceRosterEntry`` on
approval — prospective trials have no ``student_id`` to roster, so staff
roster them manually at check-in (a documented v1 limitation: no ghost
students).

``LinkTrialConversion`` closes the loop: when a parent later completes a
registration, the onboarding ``ApproveRegistration`` hook calls it with the
parent's id and the new application id. It finds the newest
approved-or-completed trial for that parent with no linked application yet
and marks it ``converted``. No match is a silent no-op by design (not every
registration follows a trial).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from pydantic import BaseModel, model_validator

from backend.v2.contexts.enrollment.domain.errors import StudentNotFound
from backend.v2.contexts.enrollment.domain.models import (
    Enrollment,
    Session,
    SessionOccurrence,
    Student,
)
from backend.v2.contexts.enrollment.domain.self_service import (
    DuplicateTrialRequest,
    OccurrenceFull,
    OccurrenceRosterEntry,
    TrialRequest,
    TrialRequestNotFound,
    TrialRequestNotPending,
    TrialSessionNotAvailable,
    open_slots,
)
from backend.v2.shared.ids import new_ulid


class SubmitTrialRequestCommand(BaseModel):
    model_config = {"frozen": True}

    parent_user_id: str
    student_ref: str
    requested_session_id: str
    preferred_start: str
    preferred_end: str
    student_id: str | None = None
    prospective_child_name: str | None = None
    prospective_child_dob: str | None = None

    @model_validator(mode="after")
    def _validate_ref(self) -> SubmitTrialRequestCommand:
        if self.student_ref == "prospective":
            if not self.prospective_child_name or not self.prospective_child_name.strip():
                raise ValueError("prospective trial requests require a child name")
        elif self.student_ref == "existing_student":
            if not self.student_id:
                raise ValueError("existing_student trial requests require a student_id")
        else:
            raise ValueError(f"invalid student_ref: {self.student_ref!r}")
        return self


class StudentQuery(Protocol):
    async def get_for_parent(self, parent_id: str, student_id: str) -> Student | None: ...


class SessionRepository(Protocol):
    async def get(self, session_id: str) -> Session | None: ...

    async def get_many(self, session_ids: list[str]) -> list[Session]: ...


class TrialRequestRepository(Protocol):
    async def add(self, request: TrialRequest) -> None: ...

    async def find_pending_for_parent_and_session(
        self, parent_user_id: str, session_id: str
    ) -> TrialRequest | None: ...

    async def list_for_parent(self, parent_user_id: str) -> list[TrialRequest]: ...


class SubmitTrialRequest:
    def __init__(
        self,
        *,
        students: StudentQuery,
        sessions: SessionRepository,
        trials: TrialRequestRepository,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._students = students
        self._sessions = sessions
        self._trials = trials
        self._now = clock

    async def execute(self, cmd: SubmitTrialRequestCommand) -> TrialRequest:
        if cmd.student_ref == "existing_student":
            assert cmd.student_id is not None  # enforced by command validator
            student = await self._students.get_for_parent(cmd.parent_user_id, cmd.student_id)
            if student is None:
                raise StudentNotFound("student not found for parent", student_id=cmd.student_id)

        session = await self._sessions.get(cmd.requested_session_id)
        if session is None or session.status != "scheduled":
            raise TrialSessionNotAvailable(
                "requested session is not available for trials",
                session_id=cmd.requested_session_id,
            )

        existing = await self._trials.find_pending_for_parent_and_session(
            cmd.parent_user_id, cmd.requested_session_id
        )
        if existing is not None:
            raise DuplicateTrialRequest(
                "a pending trial request already exists for this parent and session",
                parent_user_id=cmd.parent_user_id,
                session_id=cmd.requested_session_id,
            )

        request = TrialRequest(
            request_id=str(new_ulid()),
            academy_id=session.academy_id,
            parent_user_id=cmd.parent_user_id,
            student_ref=cmd.student_ref,  # type: ignore[arg-type]
            student_id=cmd.student_id,
            prospective_child_name=cmd.prospective_child_name,
            prospective_child_dob=cmd.prospective_child_dob,
            requested_session_id=cmd.requested_session_id,
            preferred_start=cmd.preferred_start,
            preferred_end=cmd.preferred_end,
            status="pending",
            created_at=self._now(),
        )
        await self._trials.add(request)
        return request


class ListParentTrialRequests:
    def __init__(self, *, trials: TrialRequestRepository) -> None:
        self._trials = trials

    async def execute(self, parent_user_id: str) -> list[TrialRequest]:
        return await self._trials.list_for_parent(parent_user_id)


# ============================================================================
# Admin review — list / approve / deny trial requests
# ============================================================================


class AdminTrialRequestRepository(Protocol):
    async def get(self, request_id: str) -> TrialRequest | None: ...

    async def update(self, request: TrialRequest) -> None: ...

    async def list_by_status(self, status: str | None) -> list[TrialRequest]: ...

    async def transition_from_pending(
        self, request_id: str, updates: dict[str, object]
    ) -> TrialRequest | None: ...


class ListTrialRequestsForAdmin:
    """Lists trial requests for admin review, newest first, optionally
    filtered by status."""

    def __init__(self, *, trials: AdminTrialRequestRepository) -> None:
        self._trials = trials

    async def execute(self, status: str | None = None) -> list[TrialRequest]:
        return await self._trials.list_by_status(status)


class SessionOccurrenceRepository(Protocol):
    async def get(self, occurrence_id: str) -> SessionOccurrence | None: ...


class EnrollmentRepository(Protocol):
    async def active_for_session(self, session_id: str) -> list[Enrollment]: ...


class AdminOccurrenceRosterRepository(Protocol):
    async def add(self, entry: OccurrenceRosterEntry) -> None: ...

    async def list_for_occurrence(self, occurrence_id: str) -> list[OccurrenceRosterEntry]: ...

    async def exists(self, occurrence_id: str, student_id: str) -> bool: ...


class ApproveTrialRequestCommand(BaseModel):
    model_config = {"frozen": True}

    request_id: str
    actor_id: str
    occurrence_id: str


class ApproveTrialRequest:
    """Approves a pending trial request, assigning it to a specific future
    scheduled occurrence with available capacity.

    BILLING SAFETY (R3): trial fee handling is out of v1 scope — this use
    case must NEVER accept a billing dependency (no-charge trials only).

    Only ``student_ref == "existing_student"`` requests write a one-time
    ``OccurrenceRosterEntry`` (``source="trial"``). Prospective requests have
    no ``student_id`` to roster — the occurrence is recorded and staff roster
    the child manually at check-in (documented v1 limitation: no ghost
    students).
    """

    def __init__(
        self,
        *,
        trials: AdminTrialRequestRepository,
        occurrences: SessionOccurrenceRepository,
        enrollments: EnrollmentRepository,
        sessions: SessionRepository,
        occurrence_roster: AdminOccurrenceRosterRepository,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._trials = trials
        self._occurrences = occurrences
        self._enrollments = enrollments
        self._sessions = sessions
        self._occurrence_roster = occurrence_roster
        self._now = clock

    async def execute(self, cmd: ApproveTrialRequestCommand) -> TrialRequest:
        request = await self._trials.get(cmd.request_id)
        if request is None:
            raise TrialRequestNotFound("trial request not found", request_id=cmd.request_id)
        if request.status != "pending":
            raise TrialRequestNotPending(
                "only pending trial requests can be approved", request_id=cmd.request_id
            )

        now = self._now()
        occurrence = await self._occurrences.get(cmd.occurrence_id)
        if occurrence is None or occurrence.status != "scheduled" or occurrence.start_at <= now:
            raise TrialSessionNotAvailable(
                "occurrence is not a valid future scheduled occurrence",
                occurrence_id=cmd.occurrence_id,
            )

        session = await self._sessions.get(occurrence.session_id)
        if session is None:
            raise TrialSessionNotAvailable(
                "occurrence's session no longer exists",
                occurrence_id=cmd.occurrence_id,
            )

        active_count = len(await self._enrollments.active_for_session(occurrence.session_id))
        roster_count = len(await self._occurrence_roster.list_for_occurrence(cmd.occurrence_id))
        remaining = open_slots(
            capacity=session.capacity, active_count=active_count, roster_count=roster_count
        )
        if remaining <= 0:
            raise OccurrenceFull(
                "occurrence has no remaining capacity", occurrence_id=cmd.occurrence_id
            )

        # Atomic compare-and-swap: mirrors ApproveMakeupRequest — only one
        # concurrent approve/deny call for this SAME request can win the
        # pending -> approved transition, so a double-submit loses cleanly
        # instead of racing past the capacity check and over-filling it.
        updated = await self._trials.transition_from_pending(
            request.request_id,
            {
                "status": "approved",
                "assigned_occurrence_id": cmd.occurrence_id,
                "decided_by": cmd.actor_id,
                "decided_at": now,
            },
        )
        if updated is None:
            raise TrialRequestNotPending(
                "only pending trial requests can be approved", request_id=cmd.request_id
            )

        if updated.student_ref == "existing_student" and updated.student_id is not None:
            if not await self._occurrence_roster.exists(cmd.occurrence_id, updated.student_id):
                entry = OccurrenceRosterEntry(
                    entry_id=str(new_ulid()),
                    academy_id=updated.academy_id,
                    occurrence_id=cmd.occurrence_id,
                    student_id=updated.student_id,
                    source="trial",
                    origin_request_id=updated.request_id,
                    created_at=now,
                )
                await self._occurrence_roster.add(entry)

        return updated


class DenyTrialRequestCommand(BaseModel):
    model_config = {"frozen": True}

    request_id: str
    actor_id: str
    reason: str


class DenyTrialRequest:
    """Denies a pending trial request, recording the reason and decision."""

    def __init__(
        self,
        *,
        trials: AdminTrialRequestRepository,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._trials = trials
        self._now = clock

    async def execute(self, cmd: DenyTrialRequestCommand) -> TrialRequest:
        request = await self._trials.get(cmd.request_id)
        if request is None:
            raise TrialRequestNotFound("trial request not found", request_id=cmd.request_id)
        if request.status != "pending":
            raise TrialRequestNotPending(
                "only pending trial requests can be denied", request_id=cmd.request_id
            )

        updated = await self._trials.transition_from_pending(
            request.request_id,
            {
                "status": "denied",
                "denial_reason": cmd.reason,
                "decided_by": cmd.actor_id,
                "decided_at": self._now(),
            },
        )
        if updated is None:
            raise TrialRequestNotPending(
                "only pending trial requests can be denied", request_id=cmd.request_id
            )
        return updated


# ============================================================================
# Conversion tracking — linking a trial to a subsequent registration
# ============================================================================


class ConvertibleTrialRequestRepository(Protocol):
    async def find_latest_convertible_for_parent(
        self, parent_user_id: str
    ) -> TrialRequest | None: ...

    async def update(self, request: TrialRequest) -> None: ...


class LinkTrialConversion:
    """Links the newest convertible trial request for a parent to a
    subsequent registration.

    Called from the onboarding ``ApproveRegistration`` hook after a
    successful registration approval, with the parent's id and the new
    application id. "Convertible" means ``approved`` or ``completed`` status
    with no ``linked_application_id`` yet. No match is a silent no-op — not
    every registration follows a trial.
    """

    def __init__(
        self,
        *,
        trials: ConvertibleTrialRequestRepository,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._trials = trials
        self._now = clock

    async def execute(self, *, parent_user_id: str, application_id: str) -> None:
        trial = await self._trials.find_latest_convertible_for_parent(parent_user_id)
        if trial is None:
            return
        updated = trial.model_copy(
            update={"status": "converted", "linked_application_id": application_id}
        )
        await self._trials.update(updated)
