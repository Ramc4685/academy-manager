"""Adapters wiring Coaching's lookup ports to Enrollment's queries.

Coaching never imports Enrollment directly (ADR-0005 rule 5). The
composition root supplies these adapters at wire time. Both contexts'
ports define independent shapes; the adapter is the only place that knows
about both.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Protocol

from backend.v2.contexts.coaching.application.ports import (
    AttendanceEligibility,
    DropoffPolicy,
    DropoffPolicyLookup,
    EnrollmentLookup,
    ExpectedRosterLookup,
    GuardianLookup,
    OccurrenceDetails,
    OccurrenceLookup,
    SessionLookup,
)
from backend.v2.contexts.enrollment.application.ports import SessionQuery
from backend.v2.contexts.enrollment.application.use_cases.get_occurrence_roster import (
    OccurrenceRosterQuery,
)
from backend.v2.contexts.enrollment.domain.models import Enrollment, Student
from backend.v2.contexts.enrollment.domain.self_service import ParentSelfServicePolicy


class EnrollmentSessionLookup(SessionLookup):
    """Implements Coaching's SessionLookup using Enrollment's SessionQuery."""

    def __init__(self, sessions: SessionQuery) -> None:
        self._sessions = sessions

    async def is_coach_assigned(self, coach_id: str, session_id: str, on_date: date) -> bool:
        sessions = await self._sessions.for_coach_on_date(coach_id, on_date)
        return any(s.session_id == session_id for s in sessions)

    async def is_cancelled(self, session_id: str) -> bool:
        s = await self._sessions.get(session_id)
        return s is not None and s.status == "cancelled"

    async def session_date(self, session_id: str) -> date | None:
        s = await self._sessions.get(session_id)
        return s.start_at.date() if s else None


class EnrollmentEligibilityReads(Protocol):
    """The two Enrollment reads attendance eligibility needs (issue #672).

    ``MongoEnrollmentRepository`` satisfies this; the composition root passes
    it straight in.
    """

    async def is_active(self, session_id: str, student_id: str) -> bool: ...

    async def active_or_paused_for_student(self, student_id: str) -> list[Enrollment]: ...


class EnrollmentLookupAdapter(EnrollmentLookup):
    """Implements Coaching's EnrollmentLookup using Enrollment's enrollment
    reads plus the one-time occurrence roster (approved make-ups / trials).

    Tenant scope comes from the request context inside both repositories;
    nothing tenant-specific is captured here.
    """

    def __init__(
        self,
        enrollments: EnrollmentEligibilityReads,
        occurrence_roster: OccurrenceRosterQuery,
    ) -> None:
        self._enrollments = enrollments
        self._occurrence_roster = occurrence_roster

    async def is_active(self, session_id: str, student_id: str) -> bool:
        return await self._enrollments.is_active(session_id, student_id)

    async def attendance_eligibility(
        self,
        *,
        occurrence_id: str,
        session_id: str,
        template_session_id: str | None,
        student_id: str,
    ) -> AttendanceEligibility | None:
        # Standing enrollment first (session, then the recurring template the
        # occurrence was expanded from) — the pre-#672 rule, unchanged. Only
        # ``active`` counts: paused / cancelled / withdrawn stay ineligible.
        if await self._enrollments.is_active(session_id, student_id):
            return AttendanceEligibility(source="enrollment")
        if template_session_id and template_session_id != session_id:
            if await self._enrollments.is_active(template_session_id, student_id):
                return AttendanceEligibility(source="enrollment")
        # Otherwise an approved make-up / trial entry for exactly this
        # occurrence — the same read GetOccurrenceRoster uses to render the
        # MAKE-UP / TRIAL rows the coach is tapping (issue #672).
        for entry in await self._occurrence_roster.list_for_occurrence(occurrence_id):
            if entry.student_id != student_id:
                continue
            # A make-up row is earned by an enrollment somewhere in the
            # academy, but cancel / withdraw only prune one-time rows on the
            # *cancelled* session, and a make-up targets a different session
            # by construction. So the row can outlive the family's exit;
            # require a still-live (active or paused) enrollment before
            # honouring it. Trials have no enrollment by definition.
            if (
                entry.source == "makeup"
                and not await self._enrollments.active_or_paused_for_student(student_id)
            ):
                return None
            return AttendanceEligibility(source=entry.source)
        return None


class EnrollmentOccurrenceLookup(OccurrenceLookup):
    """Maps Enrollment-owned occurrences into Coaching's occurrence port."""

    def __init__(self, occurrences: Any) -> None:
        self._occurrences = occurrences

    async def get(self, occurrence_id: str) -> OccurrenceDetails | None:
        occurrence = await self._occurrences.get(occurrence_id)
        if occurrence is None:
            return None
        return OccurrenceDetails(
            occurrence_id=occurrence.occurrence_id,
            session_id=occurrence.session_id,
            starts_at=occurrence.start_at,
            status=occurrence.status,
            scheduled_coach_id=occurrence.scheduled_coach_id,
            actual_coach_id=occurrence.actual_coach_id,
            substitute_coach_id=occurrence.substitute_coach_id,
            template_session_id=occurrence.template_session_id,
            assistant_coach_ids=occurrence.assistant_coach_ids,
        )


class _PolicyReads(Protocol):
    async def get_or_default(self) -> ParentSelfServicePolicy: ...


class SelfServiceDropoffPolicyLookup(DropoffPolicyLookup):
    """Coaching's drop-off switch and window, read from Enrollment's
    per-academy self-service policy (tenant from the request context)."""

    def __init__(self, policies: _PolicyReads) -> None:
        self._policies = policies

    async def get(self) -> DropoffPolicy:
        policy = await self._policies.get_or_default()
        return DropoffPolicy(
            enabled=policy.dropoff_checkin_enabled,
            opens_minutes_before=policy.dropoff_checkin_opens_minutes_before,
            closes_minutes_after=policy.dropoff_checkin_closes_minutes_after,
        )


class _ParentStudentReads(Protocol):
    async def get_for_parent(self, parent_id: str, student_id: str) -> Student | None: ...


class StudentGuardianLookup(GuardianLookup):
    """Parent ownership via the tenant-scoped ``get_for_parent`` read, the
    same check ``SubmitAbsenceNotice`` makes."""

    def __init__(self, students: _ParentStudentReads) -> None:
        self._students = students

    async def is_guardian(self, parent_id: str, student_id: str) -> bool:
        return await self._students.get_for_parent(parent_id, student_id) is not None


class _ActiveEnrollmentReads(Protocol):
    async def active_for_session(self, session_id: str) -> list[Enrollment]: ...


class EnrollmentExpectedRosterLookup(ExpectedRosterLookup):
    """Who staff expect at a class date, for the drop-off breakdown."""

    def __init__(
        self, enrollments: _ActiveEnrollmentReads, occurrence_roster: OccurrenceRosterQuery
    ) -> None:
        self._enrollments = enrollments
        self._occurrence_roster = occurrence_roster

    async def expected_student_ids(
        self, *, occurrence_id: str, session_id: str, template_session_id: str | None
    ) -> list[str]:
        ids: dict[str, None] = {}
        for sid in dict.fromkeys(s for s in (session_id, template_session_id) if s):
            for enrollment in await self._enrollments.active_for_session(sid):
                ids[enrollment.student_id] = None
        # shortcut: make-up rows are counted without the live-enrollment check
        # attendance_eligibility makes; this is a headcount, never a mark.
        for entry in await self._occurrence_roster.list_for_occurrence(occurrence_id):
            ids[entry.student_id] = None
        return list(ids)
