"""The leaving report (issue #698): who left, when, why, and the monthly
revenue effect.

A read model over ``enrollment_events`` — the same reporting pattern used by
``reports_routes.py``'s other owner-only reports (a scoped range read, no new
storage). Includes reclaim and expiry departures (``hold_reclaimed`` /
``hold_expired``) and orphaned reclaims (``hold_reclaim_orphaned``, §3.8 of
the design contract) so an admin can see a child dropped for a seat nobody
ended up taking.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from pydantic import BaseModel

from backend.v2.contexts.enrollment.domain.events import EnrollmentLifecycleEvent
from backend.v2.contexts.enrollment.domain.models import Session, Student

#: Every event type that represents a departure (a class stopped happening
#: for a student), for the purposes of this report. ``withdrawn`` is what
#: ``WithdrawEnrollment`` (the single- and stop-all-classes Drop path)
#: actually records today; ``removed`` is what the admin Delete-enrollment
#: route (``DELETE /enrollments/{id}``, ``CancelEnrollmentCommand``) records
#: (#744); ``dropped`` is the Drop/withdraw-all path's rename (#697);
#: ``deleted`` covers session-cancellation cascades and the legacy default
#: cancel event_type. ``hold_reclaimed``/``hold_expired``/
#: ``hold_reclaim_orphaned`` are the system-initiated departures from the
#: hold/reclaim machinery. ``cancelled`` is what a parent's own self-cancel
#: taking effect (``self_cancel.py``) and a previously-scheduled cancel being
#: processed (``process_scheduled_cancellation_actions.py``) record — without
#: it, every family that left BY THEIR OWN ACTION was invisible to this
#: report (#775). Scope note, because the first pass at #775 overstated this:
#: the People directory's Left tab is NOT built on this report. That tab is
#: ``derive_lifecycle`` (``domain/lifecycle.py``, rule R5: every enrollment
#: row terminal) and reads no events at all, so a self-cancelled family
#: already appeared there. #775's acceptance criteria ask for the Left tab to
#: be rebuilt on this report and for a Re-enroll action on Left rows; neither
#: is built yet and both remain open scope of that issue. The sibling
#: ``cancellation_scheduled`` stays out on purpose: it is a promise with a
#: future date, and the real departure row follows when it runs.
DEPARTURE_EVENT_TYPES: frozenset[str] = frozenset(
    {
        "withdrawn",
        "dropped",
        "removed",
        "cancelled",
        "hold_reclaimed",
        "hold_expired",
        "hold_reclaim_orphaned",
        "deleted",
    }
)


class LeavingReportEventReader(Protocol):
    async def list_in_range(
        self, *, start: datetime, end: datetime, event_types: frozenset[str]
    ) -> list[EnrollmentLifecycleEvent]: ...


class LeavingReportSessionReader(Protocol):
    async def get(self, session_id: str) -> Session | None: ...


class LeavingReportStudentReader(Protocol):
    async def by_ids(self, student_ids: list[str]) -> list[Student]: ...


class LeavingReportRow(BaseModel):
    model_config = {"frozen": True}

    event_id: str
    student_id: str
    student_name: str | None = None
    enrollment_id: str | None = None
    session_id: str | None = None
    session_title: str | None = None
    occurred_at: datetime
    effective_at: datetime
    event_type: str
    reason: str | None = None
    #: Issue #775: the structured departure reason, when the action that
    #: ended the enrollment recorded one.
    reason_code: str | None = None
    actor_id: str | None = None
    #: A system action (reclaim, expiry) has no human actor.
    is_system_action: bool
    billing_result: str | None = None
    credit_id: str | None = None
    #: Negative = revenue the academy stops collecting monthly because of
    #: this departure; derived from the session's ``amount_cents``, never
    #: restated from policy. ``None`` when the session has no price on file.
    monthly_revenue_effect_cents: int | None = None


class LeavingReportRequest(BaseModel):
    model_config = {"frozen": True}
    start: datetime
    end: datetime


class GetLeavingReport:
    def __init__(
        self,
        *,
        events: LeavingReportEventReader,
        sessions: LeavingReportSessionReader,
        students: LeavingReportStudentReader,
    ) -> None:
        self._events = events
        self._sessions = sessions
        self._students = students

    async def execute(self, req: LeavingReportRequest) -> list[LeavingReportRow]:
        events = await self._events.list_in_range(
            start=req.start, end=req.end, event_types=DEPARTURE_EVENT_TYPES
        )
        student_ids = sorted({e.student_id for e in events})
        students_by_id = (
            {s.student_id: s for s in await self._students.by_ids(student_ids)}
            if student_ids
            else {}
        )
        # Small per-event session lookup, not batched: this report runs over
        # a bounded date range (a month, typically), matching the other
        # admin reports' cost profile.
        session_cache: dict[str, Session | None] = {}
        rows: list[LeavingReportRow] = []
        for e in events:
            session = None
            if e.session_id is not None:
                if e.session_id not in session_cache:
                    session_cache[e.session_id] = await self._sessions.get(e.session_id)
                session = session_cache[e.session_id]
            revenue_effect = -session.amount_cents if session and session.amount_cents else None
            student = students_by_id.get(e.student_id)
            rows.append(
                LeavingReportRow(
                    event_id=e.event_id,
                    student_id=e.student_id,
                    student_name=student.full_name if student else None,
                    enrollment_id=e.enrollment_id,
                    session_id=e.session_id,
                    session_title=session.title if session else None,
                    occurred_at=e.occurred_at,
                    effective_at=e.effective_at,
                    event_type=e.event_type,
                    reason=e.reason,
                    reason_code=e.reason_code,
                    actor_id=e.actor_id,
                    is_system_action=e.actor_id is None,
                    billing_result=e.billing_result,
                    credit_id=e.credit_id,
                    monthly_revenue_effect_cents=revenue_effect,
                )
            )
        return rows
