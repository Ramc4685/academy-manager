"""Parent drop-off check-in (report + staff confirm) and its read helpers.

``ReportArrival`` records that a parent says the child is here. It is never
attendance: only ``ConfirmDropoff`` writes a mark, and it does so through
``MarkAttendance`` so every attendance rule (occurrence, cancellation, lead
time, eligibility, conflict) still applies.

Confirm runs in three steps so a crash between them is retryable:

1. ``reported -> confirming`` atomically, with the deterministic
   ``confirm_mutation_id = "dropoff:" + checkin_id``. Two staff confirming at
   once both use that id, so they converge on one attendance row.
2. ``MarkAttendance`` (status ``present``) with that mutation id.
3. ``confirming -> confirmed`` with the ``attendance_id``.

A row left ``confirming`` (step 2 or 3 failed) is finished by the next
confirm. If a mark already exists (``ConflictAttendanceExists``, voided marks
included) confirm links the check-in to it and writes nothing else.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from pydantic import BaseModel

from backend.v2.contexts.coaching.application.ports import (
    AttendanceRepository,
    DropoffCheckinRepository,
    DropoffPolicy,
    DropoffPolicyLookup,
    EnrollmentLookup,
    ExpectedRosterLookup,
    GuardianLookup,
    OccurrenceDetails,
    OccurrenceLookup,
)
from backend.v2.contexts.coaching.application.use_cases.mark_attendance import (
    MarkAttendance,
    MarkAttendanceCommand,
    is_assigned_to_occurrence,
)
from backend.v2.contexts.coaching.domain.dropoff import (
    DropoffCheckin,
    DropoffCheckinState,
    DropoffWindow,
    checkin_state,
    confirm_mutation_id_for,
    dropoff_window,
)
from backend.v2.contexts.coaching.domain.errors import (
    ConflictAttendanceExists,
    DropoffCheckinDisabled,
    DropoffCheckinNotFound,
    DropoffWindowClosed,
    SessionNotAssigned,
    StudentNotEnrolled,
)
from backend.v2.shared.ids import new_ulid

DROPOFF_CLIENT_APP_VERSION = "dropoff-checkin"


class DropoffCheckinSnapshot(BaseModel):
    """A check-in as callers show it: the stored row (if any), the derived
    state, the current window and whether a report may be sent now."""

    model_config = {"frozen": True}

    occurrence_id: str
    student_id: str
    state: DropoffCheckinState
    window_opens_at: datetime
    window_closes_at: datetime
    can_report_arrival: bool
    checkin: DropoffCheckin | None = None


class OccurrenceRef(BaseModel):
    """What the read helpers need about an occurrence the caller already has."""

    model_config = {"frozen": True}

    occurrence_id: str
    starts_at: datetime
    status: str


def _window(policy: DropoffPolicy, starts_at: datetime) -> DropoffWindow:
    return dropoff_window(
        starts_at,
        opens_minutes_before=policy.opens_minutes_before,
        closes_minutes_after=policy.closes_minutes_after,
    )


def _snapshot(
    *,
    occurrence_id: str,
    student_id: str,
    status: str,
    row: DropoffCheckin | None,
    window: DropoffWindow,
    now: datetime,
) -> DropoffCheckinSnapshot:
    state = checkin_state(row, window, now)
    return DropoffCheckinSnapshot(
        occurrence_id=occurrence_id,
        student_id=student_id,
        state=state,
        window_opens_at=window.opens_at,
        window_closes_at=window.closes_at,
        can_report_arrival=state == "none" and status == "scheduled" and window.contains(now),
        checkin=row,
    )


class ReportArrivalCommand(BaseModel):
    model_config = {"frozen": True}

    parent_id: str
    student_id: str
    occurrence_id: str


class ConfirmDropoffCommand(BaseModel):
    model_config = {"frozen": True}

    occurrence_id: str
    student_id: str


class ReportArrival:
    def __init__(
        self,
        *,
        checkins: DropoffCheckinRepository,
        policies: DropoffPolicyLookup,
        guardians: GuardianLookup,
        occurrence_lookup: OccurrenceLookup,
        enrollment_lookup: EnrollmentLookup,
        academy_id: Callable[[], str],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._checkins = checkins
        self._policies = policies
        self._guardians = guardians
        self._occurrences = occurrence_lookup
        self._enrollments = enrollment_lookup
        self._academy_id = academy_id
        self._now = clock

    async def execute(self, cmd: ReportArrivalCommand) -> DropoffCheckinSnapshot:
        policy = await self._policies.get()
        if not policy.enabled:
            raise DropoffCheckinDisabled("drop-off check-in is not switched on")
        if not await self._guardians.is_guardian(cmd.parent_id, cmd.student_id):
            raise DropoffCheckinNotFound("student not found", student_id=cmd.student_id)
        # Tenant-scoped: another academy's occurrence reads as missing.
        occurrence = await self._occurrences.get(cmd.occurrence_id)
        if occurrence is None:
            raise DropoffCheckinNotFound("class not found", occurrence_id=cmd.occurrence_id)
        if occurrence.status != "scheduled":
            raise DropoffWindowClosed(
                "this class is not running",
                occurrence_id=cmd.occurrence_id,
                reason="cancelled" if occurrence.status == "cancelled" else "not_scheduled",
            )
        # The same eligibility rule MarkAttendance applies, so a report the
        # staff could never confirm is refused up front.
        eligibility = await self._enrollments.attendance_eligibility(
            occurrence_id=cmd.occurrence_id,
            session_id=occurrence.session_id,
            template_session_id=occurrence.template_session_id,
            student_id=cmd.student_id,
        )
        if eligibility is None:
            raise StudentNotEnrolled(
                "student is not on this class's roster",
                occurrence_id=cmd.occurrence_id,
                student_id=cmd.student_id,
            )
        now = self._now()
        window = _window(policy, occurrence.starts_at)
        # A repeat tap or a retry after a timeout returns the first report.
        existing = await self._checkins.get(cmd.occurrence_id, cmd.student_id)
        if existing is None:
            if now < window.opens_at:
                raise DropoffWindowClosed(
                    "arrival can be reported closer to the class start",
                    occurrence_id=cmd.occurrence_id,
                    reason="not_open_yet",
                    opens_at=window.opens_at.isoformat(),
                )
            if now > window.closes_at:
                raise DropoffWindowClosed(
                    "the arrival window for this class has closed",
                    occurrence_id=cmd.occurrence_id,
                    reason="closed",
                    closes_at=window.closes_at.isoformat(),
                )
            existing = await self._checkins.report(
                DropoffCheckin(
                    checkin_id=new_ulid(),
                    academy_id=self._academy_id(),
                    occurrence_id=cmd.occurrence_id,
                    session_id=occurrence.session_id,
                    student_id=cmd.student_id,
                    reported_by=cmd.parent_id,
                    reported_at=now,
                )
            )
        return _snapshot(
            occurrence_id=cmd.occurrence_id,
            student_id=cmd.student_id,
            status=occurrence.status,
            row=existing,
            window=window,
            now=now,
        )


class ConfirmDropoff:
    def __init__(
        self,
        *,
        checkins: DropoffCheckinRepository,
        policies: DropoffPolicyLookup,
        occurrence_lookup: OccurrenceLookup,
        attendance_repo: AttendanceRepository,
        mark_attendance: MarkAttendance,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._checkins = checkins
        self._policies = policies
        self._occurrences = occurrence_lookup
        self._attendance = attendance_repo
        self._mark = mark_attendance
        self._now = clock

    async def execute(
        self, cmd: ConfirmDropoffCommand, *, staff_id: str, supervisor: bool
    ) -> DropoffCheckinSnapshot:
        """``supervisor`` (admin, owner, front desk) skips only the coach
        assignment check, exactly as in ``MarkAttendance``.

        The policy switch is not re-checked: turning the feature off mid-class
        must not strand reports parents already sent; staff can still confirm
        or ignore them.
        """
        occurrence = await self._occurrences.get(cmd.occurrence_id)
        if occurrence is None:
            raise DropoffCheckinNotFound("class not found", occurrence_id=cmd.occurrence_id)
        if not supervisor and not is_assigned_to_occurrence(occurrence, staff_id):
            raise SessionNotAssigned(
                "session occurrence not assigned to this coach",
                occurrence_id=cmd.occurrence_id,
                coach_id=staff_id,
            )
        row = await self._checkins.get(cmd.occurrence_id, cmd.student_id)
        if row is None:
            raise DropoffCheckinNotFound(
                "no arrival report to confirm",
                occurrence_id=cmd.occurrence_id,
                student_id=cmd.student_id,
            )
        policy = await self._policies.get()
        window = _window(policy, occurrence.starts_at)
        if row.status == "reported":
            row = await self._claim(row, occurrence, window, staff_id)
        if row.status == "confirming":
            row = await self._finish(row, occurrence, staff_id, supervisor)
        return _snapshot(
            occurrence_id=cmd.occurrence_id,
            student_id=cmd.student_id,
            status=occurrence.status,
            row=row,
            window=window,
            now=self._now(),
        )

    async def _claim(
        self,
        row: DropoffCheckin,
        occurrence: OccurrenceDetails,
        window: DropoffWindow,
        staff_id: str,
    ) -> DropoffCheckin:
        if occurrence.status == "cancelled":
            raise DropoffWindowClosed(
                "this class was cancelled", occurrence_id=row.occurrence_id, reason="cancelled"
            )
        if checkin_state(row, window, self._now()) == "expired":
            raise DropoffWindowClosed(
                "this arrival report has expired; mark attendance instead",
                occurrence_id=row.occurrence_id,
                reason="expired",
            )
        claimed = await self._checkins.begin_confirm(
            row.occurrence_id,
            row.student_id,
            confirm_mutation_id=confirm_mutation_id_for(row.checkin_id),
            staff_id=staff_id,
        )
        if claimed is None:  # pragma: no cover - rows are never deleted
            raise DropoffCheckinNotFound("no arrival report to confirm")
        return claimed

    async def _finish(
        self,
        row: DropoffCheckin,
        occurrence: OccurrenceDetails,
        staff_id: str,
        supervisor: bool,
    ) -> DropoffCheckin:
        mutation_id = row.confirm_mutation_id or confirm_mutation_id_for(row.checkin_id)
        try:
            result = await self._mark.execute(
                MarkAttendanceCommand(
                    mutation_id=mutation_id,
                    occurrence_id=row.occurrence_id,
                    session_id=occurrence.session_id,
                    student_id=row.student_id,
                    status="present",
                    client_app_version=DROPOFF_CLIENT_APP_VERSION,
                ),
                staff_id,
                supervisor=supervisor,
            )
            attendance_id, reconciled = result.attendance_id, False
        except ConflictAttendanceExists as exc:
            # A mark already exists (manual, or voided). Link to it; its status
            # and correction rules stay exactly as they are.
            existing_id = exc.details.get("existing_attendance_id")
            if not existing_id:
                existing = await self._attendance.find_existing(row.occurrence_id, row.student_id)
                existing_id = existing.attendance_id if existing else None
            if not existing_id:
                raise
            attendance_id, reconciled = str(existing_id), existing_id != mutation_id
        finished = await self._checkins.finish_confirm(
            row.occurrence_id,
            row.student_id,
            attendance_id=attendance_id,
            reconciled=reconciled,
            confirmed_at=self._now(),
        )
        if finished is None:  # pragma: no cover - rows are never deleted
            raise DropoffCheckinNotFound("no arrival report to confirm")
        return finished


class OccurrenceDropoffSummary(BaseModel):
    """Staff breakdown for one class date: who is expected and every arrival
    report (pending, expired or confirmed)."""

    model_config = {"frozen": True}

    enabled: bool
    expected_student_ids: list[str]
    checkins: list[DropoffCheckinSnapshot]


class DropoffCheckinReads:
    """Check-in state for schedule and roster reads, so clients need no extra
    round trip."""

    def __init__(
        self,
        *,
        checkins: DropoffCheckinRepository,
        policies: DropoffPolicyLookup,
        occurrence_lookup: OccurrenceLookup,
        expected_roster: ExpectedRosterLookup,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._checkins = checkins
        self._policies = policies
        self._occurrences = occurrence_lookup
        self._expected = expected_roster
        self._now = clock

    async def occurrence_summary(self, occurrence_id: str) -> OccurrenceDropoffSummary | None:
        """None when the occurrence is not in this academy."""
        occurrence = await self._occurrences.get(occurrence_id)
        if occurrence is None:
            return None
        policy = await self._policies.get()
        expected = await self._expected.expected_student_ids(
            occurrence_id=occurrence_id,
            session_id=occurrence.session_id,
            template_session_id=occurrence.template_session_id,
        )
        ref = OccurrenceRef(
            occurrence_id=occurrence_id, starts_at=occurrence.starts_at, status=occurrence.status
        )
        by_student = (await self.for_occurrences([ref]))[occurrence_id]
        return OccurrenceDropoffSummary(
            enabled=policy.enabled,
            expected_student_ids=expected,
            checkins=list(by_student.values()),
        )

    async def policy(self) -> DropoffPolicy:
        return await self._policies.get()

    async def for_student(
        self, student_id: str, occurrences: Sequence[OccurrenceRef]
    ) -> dict[str, DropoffCheckinSnapshot] | None:
        """One snapshot per occurrence (state ``none`` when not reported).
        None when the academy has the feature off: parents see nothing."""
        policy = await self._policies.get()
        if not policy.enabled:
            return None
        rows = await self._checkins.list_for_student(
            student_id, [o.occurrence_id for o in occurrences]
        )
        by_occurrence = {r.occurrence_id: r for r in rows}
        now = self._now()
        return {
            o.occurrence_id: _snapshot(
                occurrence_id=o.occurrence_id,
                student_id=student_id,
                status=o.status,
                row=by_occurrence.get(o.occurrence_id),
                window=_window(policy, o.starts_at),
                now=now,
            )
            for o in occurrences
        }

    async def for_occurrences(
        self, occurrences: Sequence[OccurrenceRef]
    ) -> dict[str, dict[str, DropoffCheckinSnapshot]]:
        """Reported students only, keyed occurrence id -> student id.

        Not gated on the switch: reports sent before it was turned off stay
        visible to staff, who may still confirm them (see ConfirmDropoff).
        With the feature never used there are no rows, so nothing shows.
        """
        policy = await self._policies.get()
        refs = {o.occurrence_id: o for o in occurrences}
        rows = await self._checkins.list_for_occurrences(list(refs))
        now = self._now()
        out: dict[str, dict[str, DropoffCheckinSnapshot]] = {o: {} for o in refs}
        for row in rows:
            ref = refs.get(row.occurrence_id)
            if ref is None:
                continue
            out[row.occurrence_id][row.student_id] = _snapshot(
                occurrence_id=row.occurrence_id,
                student_id=row.student_id,
                status=ref.status,
                row=row,
                window=_window(policy, ref.starts_at),
                now=now,
            )
        return out
