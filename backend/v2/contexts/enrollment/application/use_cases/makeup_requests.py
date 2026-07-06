"""Parent-submitted makeup requests (R2).

Parents request to make up a missed occurrence, optionally proposing a
target occurrence to attend instead; admin (Task 5) approves or denies. This
module also exposes ``ListEligibleMakeupTargets``, which lists upcoming
occurrences the parent could propose — respecting the academy's expiry
window, the student's existing active enrollments, and available capacity.

Task 5 adds the admin-side review use cases (``ListMakeupRequestsForAdmin``,
``ApproveMakeupRequest``, ``DenyMakeupRequest``, ``ListAbsencesForAdmin``).
BILLING SAFETY: approving a makeup request only writes a one-time
``OccurrenceRosterEntry`` — the student already paid for the missed session,
so ``ApproveMakeupRequest`` must never accept a billing dependency.

Task 6 adds ``ExpireMakeupRequests``, a scheduler-driven job that flips
lapsed ``pending`` requests to ``expired`` so they never linger silently.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol

from pydantic import BaseModel

from backend.v2.contexts.enrollment.domain.errors import StudentNotFound
from backend.v2.contexts.enrollment.domain.models import (
    Enrollment,
    Session,
    SessionOccurrence,
    Student,
)
from backend.v2.contexts.enrollment.domain.self_service import (
    DuplicateMakeupRequest,
    MakeupNotEligible,
    MakeupRequest,
    MakeupRequestNotFound,
    MakeupRequestNotPending,
    MakeupWindowExpired,
    OccurrenceFull,
    OccurrenceRosterEntry,
    ParentSelfServicePolicy,
)
from backend.v2.shared.ids import new_ulid


class SubmitMakeupRequestCommand(BaseModel):
    model_config = {"frozen": True}

    parent_id: str
    student_id: str
    missed_occurrence_id: str
    requested_target_occurrence_id: str | None = None


class MakeupTargetView(BaseModel):
    model_config = {"frozen": True}

    occurrence_id: str
    session_id: str
    title: str
    start_at: datetime
    end_at: datetime
    open_slots: int


class StudentQuery(Protocol):
    async def get_for_parent(self, parent_id: str, student_id: str) -> Student | None: ...


class SessionOccurrenceRepository(Protocol):
    async def get(self, occurrence_id: str) -> SessionOccurrence | None: ...


class AbsenceNoticeQuery(Protocol):
    async def get_for_occurrence_and_student(
        self, occurrence_id: str, student_id: str
    ) -> object | None: ...


class SelfServicePolicyRepository(Protocol):
    async def get_or_default(self) -> ParentSelfServicePolicy: ...


class MakeupRequestRepository(Protocol):
    async def add(self, request: MakeupRequest) -> None: ...

    async def find_active_for_missed_occurrence(
        self, missed_occurrence_id: str, student_id: str
    ) -> MakeupRequest | None: ...

    async def list_for_parent(self, parent_id: str) -> list[MakeupRequest]: ...


class SubmitMakeupRequest:
    def __init__(
        self,
        *,
        students: StudentQuery,
        occurrences: SessionOccurrenceRepository,
        notices: AbsenceNoticeQuery,
        makeups: MakeupRequestRepository,
        policies: SelfServicePolicyRepository,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._students = students
        self._occurrences = occurrences
        self._notices = notices
        self._makeups = makeups
        self._policies = policies
        self._now = clock

    async def execute(self, cmd: SubmitMakeupRequestCommand) -> MakeupRequest:
        student = await self._students.get_for_parent(cmd.parent_id, cmd.student_id)
        if student is None:
            raise StudentNotFound("student not found for parent", student_id=cmd.student_id)

        missed = await self._occurrences.get(cmd.missed_occurrence_id)
        now = self._now()
        if missed is None or missed.start_at >= now:
            raise MakeupWindowExpired(
                "cannot request a makeup for an occurrence that hasn't happened yet",
                occurrence_id=cmd.missed_occurrence_id,
            )

        policy = await self._policies.get_or_default()

        if policy.makeup_requires_notice:
            notice = await self._notices.get_for_occurrence_and_student(
                cmd.missed_occurrence_id, cmd.student_id
            )
            if notice is None or not getattr(notice, "notice_window_met", False):
                raise MakeupNotEligible(
                    "a window-met absence notice is required before requesting a makeup",
                    occurrence_id=cmd.missed_occurrence_id,
                    student_id=cmd.student_id,
                )

        expires_at = missed.start_at + timedelta(days=policy.makeup_expiry_days)
        if now > expires_at:
            raise MakeupWindowExpired(
                "makeup request window has expired",
                occurrence_id=cmd.missed_occurrence_id,
            )

        existing = await self._makeups.find_active_for_missed_occurrence(
            cmd.missed_occurrence_id, cmd.student_id
        )
        if existing is not None:
            raise DuplicateMakeupRequest(
                "a non-denied makeup request already exists for this occurrence",
                occurrence_id=cmd.missed_occurrence_id,
                student_id=cmd.student_id,
            )

        request = MakeupRequest(
            request_id=str(new_ulid()),
            academy_id=missed.academy_id,
            student_id=cmd.student_id,
            parent_id=cmd.parent_id,
            missed_occurrence_id=cmd.missed_occurrence_id,
            requested_target_occurrence_id=cmd.requested_target_occurrence_id,
            status="pending",
            expires_at=expires_at,
            created_at=now,
        )
        await self._makeups.add(request)
        return request


class ListParentMakeups:
    def __init__(self, *, makeups: MakeupRequestRepository) -> None:
        self._makeups = makeups

    async def execute(self, parent_id: str) -> list[MakeupRequest]:
        return await self._makeups.list_for_parent(parent_id)


class SessionRepository(Protocol):
    async def get(self, session_id: str) -> Session | None: ...

    async def get_many(self, session_ids: list[str]) -> list[Session]: ...


class EnrollmentRepository(Protocol):
    async def active_for_session(self, session_id: str) -> list[Enrollment]: ...

    async def is_active(self, session_id: str, student_id: str) -> bool: ...


class OccurrenceRosterRepository(Protocol):
    async def list_for_occurrence(self, occurrence_id: str) -> list[OccurrenceRosterEntry]: ...


class UpcomingOccurrenceRepository(SessionOccurrenceRepository, Protocol):
    async def list_upcoming_scheduled_between(
        self, *, start_at: datetime, end_at: datetime
    ) -> list[SessionOccurrence]: ...


class ListEligibleMakeupTargets:
    def __init__(
        self,
        *,
        students: StudentQuery,
        occurrences: UpcomingOccurrenceRepository,
        sessions: SessionRepository,
        enrollments: EnrollmentRepository,
        occurrence_roster: OccurrenceRosterRepository,
        policies: SelfServicePolicyRepository,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._students = students
        self._occurrences = occurrences
        self._sessions = sessions
        self._enrollments = enrollments
        self._occurrence_roster = occurrence_roster
        self._policies = policies
        self._now = clock

    async def execute(
        self, *, parent_id: str, student_id: str, missed_occurrence_id: str
    ) -> list[MakeupTargetView]:
        student = await self._students.get_for_parent(parent_id, student_id)
        if student is None:
            raise StudentNotFound("student not found for parent", student_id=student_id)

        missed = await self._occurrences.get(missed_occurrence_id)
        if missed is None:
            return []

        policy = await self._policies.get_or_default()
        now = self._now()
        window_end = missed.start_at + timedelta(days=policy.makeup_expiry_days)

        candidates = await self._occurrences.list_upcoming_scheduled_between(
            start_at=now,
            end_at=window_end,
        )
        if not candidates:
            return []

        session_ids = list({c.session_id for c in candidates})
        sessions_by_id = {s.session_id: s for s in await self._sessions.get_many(session_ids)}

        views: list[MakeupTargetView] = []
        for occurrence in candidates:
            session = sessions_by_id.get(occurrence.session_id)
            if session is None:
                continue
            if await self._enrollments.is_active(occurrence.session_id, student_id):
                continue

            active_count = len(await self._enrollments.active_for_session(occurrence.session_id))
            roster_count = len(
                await self._occurrence_roster.list_for_occurrence(occurrence.occurrence_id)
            )
            open_slots = session.capacity - active_count - roster_count
            if open_slots <= 0:
                continue

            views.append(
                MakeupTargetView(
                    occurrence_id=occurrence.occurrence_id,
                    session_id=occurrence.session_id,
                    title=session.title,
                    start_at=occurrence.start_at,
                    end_at=occurrence.end_at,
                    open_slots=open_slots,
                )
            )

        return views


# ============================================================================
# Task 5: Admin review — approve/deny makeup requests, admin absence queue
# ============================================================================


class AdminMakeupRequestRepository(Protocol):
    async def get(self, request_id: str) -> MakeupRequest | None: ...

    async def update(self, request: MakeupRequest) -> None: ...

    async def list_by_status(self, status: str | None) -> list[MakeupRequest]: ...

    async def transition_from_pending(
        self, request_id: str, updates: dict[str, object]
    ) -> MakeupRequest | None: ...


class AdminStudentQuery(Protocol):
    async def by_ids(self, student_ids: list[str]) -> list[Student]: ...


class AdminAbsenceNoticeQuery(Protocol):
    async def list_all(self) -> list: ...


class AdminOccurrenceRosterRepository(Protocol):
    async def add(self, entry: OccurrenceRosterEntry) -> None: ...

    async def list_for_occurrence(self, occurrence_id: str) -> list[OccurrenceRosterEntry]: ...

    async def exists(self, occurrence_id: str, student_id: str) -> bool: ...


class MakeupRequestAdminView(BaseModel):
    model_config = {"frozen": True}

    request_id: str
    student_id: str
    missed_occurrence_id: str
    requested_target_occurrence_id: str | None = None
    status: str
    expires_at: datetime
    denial_reason: str | None = None
    decided_by: str | None = None
    decided_at: datetime | None = None
    approved_target_occurrence_id: str | None = None
    created_at: datetime
    student_full_name: str | None = None


class AbsenceNoticeAdminView(BaseModel):
    model_config = {"frozen": True}

    notice_id: str
    student_id: str
    occurrence_id: str
    session_id: str
    submitted_by: str
    submitted_at: datetime
    notice_window_met: bool
    student_full_name: str | None = None


def _student_names(students: list[Student]) -> dict[str, str]:
    return {s.student_id: s.full_name for s in students}


class ListMakeupRequestsForAdmin:
    """Lists makeup requests for admin review, newest first, optionally
    filtered by status. Enriches each row with the student's full name."""

    def __init__(
        self,
        *,
        makeups: AdminMakeupRequestRepository,
        students: AdminStudentQuery,
    ) -> None:
        self._makeups = makeups
        self._students = students

    async def execute(self, status: str | None = None) -> list[MakeupRequestAdminView]:
        requests = await self._makeups.list_by_status(status)
        student_ids = list({r.student_id for r in requests})
        names = _student_names(await self._students.by_ids(student_ids))
        return [
            MakeupRequestAdminView(
                **r.model_dump(exclude={"academy_id", "parent_id"}),
                student_full_name=names.get(r.student_id),
            )
            for r in requests
        ]


class ListAbsencesForAdmin:
    """Lists absence notices for admin visibility, newest first, enriched
    with the student's full name."""

    def __init__(
        self,
        *,
        notices: AdminAbsenceNoticeQuery,
        students: AdminStudentQuery,
    ) -> None:
        self._notices = notices
        self._students = students

    async def execute(self) -> list[AbsenceNoticeAdminView]:
        notices = await self._notices.list_all()
        student_ids = list({n.student_id for n in notices})
        names = _student_names(await self._students.by_ids(student_ids))
        return [
            AbsenceNoticeAdminView(
                notice_id=n.notice_id,
                student_id=n.student_id,
                occurrence_id=n.occurrence_id,
                session_id=n.session_id,
                submitted_by=n.submitted_by,
                submitted_at=n.submitted_at,
                notice_window_met=n.notice_window_met,
                student_full_name=names.get(n.student_id),
            )
            for n in notices
        ]


class ApproveMakeupRequestCommand(BaseModel):
    model_config = {"frozen": True}

    request_id: str
    actor_id: str
    target_occurrence_id: str


class ApproveMakeupRequest:
    """Approves a pending makeup request, writing a one-time occurrence
    roster entry for the target occurrence.

    BILLING SAFETY (R2): the student already paid for the missed session, so
    this use case must NEVER accept a billing dependency. Do not add one.
    """

    def __init__(
        self,
        *,
        makeups: AdminMakeupRequestRepository,
        occurrences: SessionOccurrenceRepository,
        enrollments: EnrollmentRepository,
        sessions: SessionRepository,
        occurrence_roster: AdminOccurrenceRosterRepository,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._makeups = makeups
        self._occurrences = occurrences
        self._enrollments = enrollments
        self._sessions = sessions
        self._occurrence_roster = occurrence_roster
        self._now = clock

    async def execute(self, cmd: ApproveMakeupRequestCommand) -> MakeupRequest:
        request = await self._makeups.get(cmd.request_id)
        if request is None:
            raise MakeupRequestNotFound("makeup request not found", request_id=cmd.request_id)
        if request.status != "pending":
            raise MakeupRequestNotPending(
                "only pending makeup requests can be approved", request_id=cmd.request_id
            )

        now = self._now()
        if now > request.expires_at:
            raise MakeupWindowExpired(
                "makeup request window has expired", request_id=cmd.request_id
            )

        target = await self._occurrences.get(cmd.target_occurrence_id)
        if target is None or target.status != "scheduled" or target.start_at <= now:
            raise MakeupWindowExpired(
                "target occurrence is not a valid future scheduled occurrence",
                occurrence_id=cmd.target_occurrence_id,
            )

        session = await self._sessions.get(target.session_id)
        if session is None:
            raise MakeupWindowExpired(
                "target occurrence's session no longer exists",
                occurrence_id=cmd.target_occurrence_id,
            )

        active_count = len(await self._enrollments.active_for_session(target.session_id))
        roster_count = len(
            await self._occurrence_roster.list_for_occurrence(cmd.target_occurrence_id)
        )
        if active_count + roster_count >= session.capacity:
            raise OccurrenceFull(
                "target occurrence has no remaining capacity",
                occurrence_id=cmd.target_occurrence_id,
            )

        # Atomic compare-and-swap: only one concurrent approve/deny call for
        # this SAME request can win the pending -> approved transition. The
        # second caller (double-click / two tabs) gets MakeupRequestNotPending
        # instead of racing past the check above and writing a duplicate
        # roster entry / silently over-filling capacity.
        updated_doc = await self._makeups.transition_from_pending(
            request.request_id,
            {
                "status": "approved",
                "approved_target_occurrence_id": cmd.target_occurrence_id,
                "decided_by": cmd.actor_id,
                "decided_at": now,
            },
        )
        if updated_doc is None:
            raise MakeupRequestNotPending(
                "only pending makeup requests can be approved", request_id=cmd.request_id
            )

        # Belt-and-braces: should be unreachable after a successful CAS (the
        # CAS is keyed on request_id, so it can only ever fire once per
        # request), but cheap to guard against a duplicate roster entry. A
        # DB-level unique index on (academy_id, occurrence_id, student_id)
        # arrives in a later migration.
        if not await self._occurrence_roster.exists(cmd.target_occurrence_id, request.student_id):
            entry = OccurrenceRosterEntry(
                entry_id=str(new_ulid()),
                academy_id=request.academy_id,
                occurrence_id=cmd.target_occurrence_id,
                student_id=request.student_id,
                source="makeup",
                origin_request_id=request.request_id,
                created_at=now,
            )
            await self._occurrence_roster.add(entry)

        return updated_doc


class DenyMakeupRequestCommand(BaseModel):
    model_config = {"frozen": True}

    request_id: str
    actor_id: str
    reason: str


class DenyMakeupRequest:
    """Denies a pending makeup request, recording the reason and decision."""

    def __init__(
        self,
        *,
        makeups: AdminMakeupRequestRepository,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._makeups = makeups
        self._now = clock

    async def execute(self, cmd: DenyMakeupRequestCommand) -> MakeupRequest:
        request = await self._makeups.get(cmd.request_id)
        if request is None:
            raise MakeupRequestNotFound("makeup request not found", request_id=cmd.request_id)
        if request.status != "pending":
            raise MakeupRequestNotPending(
                "only pending makeup requests can be denied", request_id=cmd.request_id
            )

        # Atomic compare-and-swap guards the same double-submit race as
        # ApproveMakeupRequest: a second concurrent deny (or a deny racing an
        # approve) for this request gets MakeupRequestNotPending instead of
        # silently overwriting the decision.
        updated_doc = await self._makeups.transition_from_pending(
            request.request_id,
            {
                "status": "denied",
                "denial_reason": cmd.reason,
                "decided_by": cmd.actor_id,
                "decided_at": self._now(),
            },
        )
        if updated_doc is None:
            raise MakeupRequestNotPending(
                "only pending makeup requests can be denied", request_id=cmd.request_id
            )
        return updated_doc


# ============================================================================
# Task 6: Makeup expiry job — pending requests past their window -> expired
# ============================================================================


class ExpirableMakeupRequestRepository(Protocol):
    async def expire_pending_before(self, now: datetime) -> int: ...


class ExpireMakeupRequests:
    """Scheduler-driven job: flips pending makeup requests whose window has
    lapsed to ``expired``. Approved/denied/completed requests are untouched.
    """

    def __init__(
        self,
        *,
        makeups: ExpirableMakeupRequestRepository,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._makeups = makeups
        self._now = clock

    async def execute(self) -> int:
        return await self._makeups.expire_pending_before(self._now())
