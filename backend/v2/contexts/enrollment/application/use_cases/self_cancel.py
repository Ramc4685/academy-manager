"""Parent self-cancel enrollment (R4).

Parents can cancel their own active enrollment, subject to the academy's
``ParentSelfServicePolicy`` (minimum notice window, flat cancellation fee,
and immediate-vs-end-of-period timing). ``compute_self_cancel_terms`` (in
``domain/self_service.py``) is the single source of truth for the
notice/fee computation — both ``PreviewSelfCancel`` and
``SelfCancelEnrollment`` call it with the same inputs so they can never
disagree.

BILLING SAFETY: the app ledger owns invoices. A cancellation fee is
appended as an ``InvoiceLine`` via ``SelfCancelBillingPort`` — a minimal
cross-context port (mirroring the other enrollment ports in
``application/ports.py``) whose concrete implementation delegates to the
billing context's existing ``AddInvoiceLine`` use case (the real
production line-append path). This use case never calls Stripe, never
closes/settles invoices, and never touches refund/credit machinery.

Idempotency: the fee line's natural key is ``f"{enrollment_id}-self-cancel-fee"``,
recorded as the ``InvoiceLine.source_id`` (with ``source_type="self_cancel_fee"``)
by the billing-port implementation, which checks for an existing line with that
key before appending — so a retried cancel call can never double-bill even if
the enrollment-status CAS below were somehow bypassed. The primary guard against
a double-submitted cancel is the atomic active->cancelled CAS on the enrollment
itself (``EnrollmentWriter.mark_cancelled_by_parent``, mirroring
``transition_from_pending`` / ``TenantScopedRepository._find_one_and_update``):
only one concurrent call can win that transition; the loser raises
``EnrollmentNotCancellable`` before ever reaching the billing port, so the
fee-line idempotency key is defense in depth, not the primary guard.

end_of_period mechanism (v1 simplification, documented per the task brief):
the existing scheduled-action machinery (``ScheduledEnrollmentAction`` /
``ScheduledEnrollmentActionRepository`` / ``ProcessScheduledResumeActions``)
is tightly coupled to pause/resume — ``ScheduledActionType`` is a closed
``Literal["resume_from_pause"]`` and the record requires a
``pause_request_id``. Generalizing it for cancellation would mean widening a
model built for a different purpose plus a new processor/job wiring — real
scope creep for what the brief explicitly allows simplifying. So
``"end_of_period"`` here does NOT keep the enrollment ``active`` pending a
background job; it sets ``status="cancelled"`` immediately, with
``cancelled_at`` computed as the end of the current calendar month (UTC) —
still a fully auditable state change (R4), just with a future-dated
``cancelled_at`` instead of a deferred status flip. ``"immediate"`` timing
sets ``cancelled_at`` to now.
"""

from __future__ import annotations

import calendar
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import BaseModel, Field

from backend.v2.contexts.enrollment.domain.errors import EnrollmentNotFound
from backend.v2.contexts.enrollment.domain.models import Enrollment, Student
from backend.v2.contexts.enrollment.domain.self_service import (
    EnrollmentNotCancellable,
    ParentSelfServicePolicy,
    SelfCancelTerms,
    compute_self_cancel_terms,
)

Clock = Callable[[], datetime]


def _end_of_month_utc(now: datetime) -> datetime:
    """Last instant (23:59:59.999999 UTC) of ``now``'s calendar month."""
    last_day = calendar.monthrange(now.year, now.month)[1]
    return datetime(now.year, now.month, last_day, 23, 59, 59, 999999, tzinfo=UTC)


def _policy_snapshot(policy: ParentSelfServicePolicy, terms: SelfCancelTerms) -> dict[str, Any]:
    """The 6 policy fields + computed fee_cents/notice_met, frozen at
    decision time — so later policy edits never retroactively change what
    this cancellation actually charged/decided."""
    return {
        "academy_id": policy.academy_id,
        "absence_notice_min_hours": policy.absence_notice_min_hours,
        "makeup_expiry_days": policy.makeup_expiry_days,
        "makeup_requires_notice": policy.makeup_requires_notice,
        "cancellation_minimum_notice_days": policy.cancellation_minimum_notice_days,
        "cancellation_fee_cents": policy.cancellation_fee_cents,
        "cancellation_effective_timing": policy.cancellation_effective_timing,
        "fee_cents": terms.fee_cents,
        "notice_met": terms.notice_met,
    }


# --- Ports ------------------------------------------------------------


class SelfCancelStudentQuery(Protocol):
    async def get_for_parent(self, parent_id: str, student_id: str) -> Student | None: ...


class SelfCancelEnrollmentQuery(Protocol):
    async def get(self, enrollment_id: str) -> Enrollment | None: ...


class SelfCancelEnrollmentWriter(SelfCancelEnrollmentQuery, Protocol):
    async def mark_cancelled_by_parent(
        self,
        enrollment_id: str,
        *,
        cancellation_reason: str,
        cancellation_policy_snapshot: dict[str, Any],
        cancelled_at: datetime,
    ) -> Enrollment | None: ...


class SelfCancelPolicyRepository(Protocol):
    async def get_or_default(self) -> ParentSelfServicePolicy: ...


class SelfCancelOccurrenceQuery(Protocol):
    """Resolves the next upcoming scheduled occurrence for a session — the
    input ``compute_self_cancel_terms`` needs to judge notice met/not-met."""

    async def next_upcoming_start_for_session(
        self, session_id: str, *, now: datetime
    ) -> datetime | None: ...


class SelfCancelBillingPort(Protocol):
    """Cross-context port: append a cancellation-fee invoice line via the
    billing context's real production line-append path (``AddInvoiceLine``).
    Never call Stripe; never close/settle invoices. Implementations MUST be
    idempotent on ``idempotency_key`` (natural key:
    ``f"{enrollment_id}-self-cancel-fee"``) so a retried cancel can't
    double-bill."""

    async def record_cancellation_fee(
        self,
        *,
        enrollment: Enrollment,
        fee_cents: int,
        reason: str,
        actor_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]: ...


# --- Preview ------------------------------------------------------------


class PreviewSelfCancelView(BaseModel):
    model_config = {"frozen": True}

    allowed: bool
    notice_met: bool
    fee_cents: int
    effective_timing: str
    policy: dict[str, Any]
    blocked_reason: str | None = None


class PreviewSelfCancel:
    """GET .../cancellation-preview. Ownership failures (wrong parent /
    unknown enrollment) raise ``EnrollmentNotFound`` (404-style) rather than
    ``blocked_reason`` — we never leak another tenant's/parent's enrollment
    existence. ``blocked_reason`` is only for a real, owned enrollment that
    simply isn't in a cancellable state right now."""

    def __init__(
        self,
        *,
        enrollments: SelfCancelEnrollmentQuery,
        students: SelfCancelStudentQuery,
        policies: SelfCancelPolicyRepository,
        occurrences: SelfCancelOccurrenceQuery,
        clock: Clock = lambda: datetime.now(UTC),
    ) -> None:
        self._enrollments = enrollments
        self._students = students
        self._policies = policies
        self._occurrences = occurrences
        self._now = clock

    async def execute(self, *, enrollment_id: str, parent_id: str) -> PreviewSelfCancelView:
        enrollment = await self._owned_enrollment(enrollment_id, parent_id)
        policy = await self._policies.get_or_default()

        if enrollment.status != "active":
            terms = SelfCancelTerms(notice_met=True, fee_cents=0)
            return PreviewSelfCancelView(
                allowed=False,
                notice_met=terms.notice_met,
                fee_cents=terms.fee_cents,
                effective_timing=policy.cancellation_effective_timing,
                policy=_policy_snapshot(policy, terms),
                blocked_reason=f"enrollment is not active (status={enrollment.status})",
            )

        now = self._now()
        next_start = await self._occurrences.next_upcoming_start_for_session(
            enrollment.session_id, now=now
        )
        terms = compute_self_cancel_terms(policy, next_start, now)
        return PreviewSelfCancelView(
            allowed=True,
            notice_met=terms.notice_met,
            fee_cents=terms.fee_cents,
            effective_timing=policy.cancellation_effective_timing,
            policy=_policy_snapshot(policy, terms),
            blocked_reason=None,
        )

    async def _owned_enrollment(self, enrollment_id: str, parent_id: str) -> Enrollment:
        enrollment = await self._enrollments.get(enrollment_id)
        if enrollment is None:
            raise EnrollmentNotFound("enrollment missing", enrollment_id=enrollment_id)
        student = await self._students.get_for_parent(parent_id, enrollment.student_id)
        if student is None:
            raise EnrollmentNotFound("enrollment missing", enrollment_id=enrollment_id)
        return enrollment


# --- Cancel ---------------------------------------------------------------


class SelfCancelEnrollmentCommand(BaseModel):
    model_config = {"frozen": True}

    enrollment_id: str
    parent_id: str
    reason: str = Field(min_length=1)


class SelfCancelEnrollmentResult(BaseModel):
    model_config = {"frozen": True}

    enrollment_id: str
    status: str
    fee_cents: int
    notice_met: bool
    effective_timing: str
    cancelled_at: datetime


class SelfCancelEnrollment:
    """Parent-initiated cancel of their own active enrollment (R4).

    Always writes the full audit trail (``cancelled_by="parent"``,
    ``cancellation_reason``, ``cancellation_policy_snapshot``,
    ``cancelled_at``) in the same atomic CAS write that flips
    active -> cancelled — never a silent state change.
    """

    def __init__(
        self,
        *,
        enrollments: SelfCancelEnrollmentWriter,
        students: SelfCancelStudentQuery,
        policies: SelfCancelPolicyRepository,
        occurrences: SelfCancelOccurrenceQuery,
        billing: SelfCancelBillingPort | None = None,
        clock: Clock = lambda: datetime.now(UTC),
    ) -> None:
        self._enrollments = enrollments
        self._students = students
        self._policies = policies
        self._occurrences = occurrences
        self._billing = billing
        self._now = clock

    async def execute(self, cmd: SelfCancelEnrollmentCommand) -> SelfCancelEnrollmentResult:
        enrollment = await self._enrollments.get(cmd.enrollment_id)
        if enrollment is None:
            raise EnrollmentNotFound("enrollment missing", enrollment_id=cmd.enrollment_id)
        student = await self._students.get_for_parent(cmd.parent_id, enrollment.student_id)
        if student is None:
            raise EnrollmentNotFound("enrollment missing", enrollment_id=cmd.enrollment_id)
        if enrollment.status != "active":
            raise EnrollmentNotCancellable(
                "enrollment is not active",
                enrollment_id=cmd.enrollment_id,
                status=enrollment.status,
            )

        policy = await self._policies.get_or_default()
        now = self._now()
        next_start = await self._occurrences.next_upcoming_start_for_session(
            enrollment.session_id, now=now
        )
        terms = compute_self_cancel_terms(policy, next_start, now)

        if policy.cancellation_effective_timing == "immediate":
            cancelled_at = now
        else:
            cancelled_at = _end_of_month_utc(now)

        snapshot = _policy_snapshot(policy, terms)

        updated = await self._enrollments.mark_cancelled_by_parent(
            cmd.enrollment_id,
            cancellation_reason=cmd.reason,
            cancellation_policy_snapshot=snapshot,
            cancelled_at=cancelled_at,
        )
        if updated is None:
            # Lost the CAS: someone else cancelled this enrollment first
            # (double-submit / two tabs). Never append a second fee line.
            raise EnrollmentNotCancellable(
                "enrollment is no longer active", enrollment_id=cmd.enrollment_id
            )

        if terms.fee_cents > 0 and self._billing is not None:
            await self._billing.record_cancellation_fee(
                enrollment=updated,
                fee_cents=terms.fee_cents,
                reason="Cancellation fee",
                actor_id=cmd.parent_id,
                idempotency_key=f"{cmd.enrollment_id}-self-cancel-fee",
            )

        return SelfCancelEnrollmentResult(
            enrollment_id=updated.enrollment_id,
            status=updated.status,
            fee_cents=terms.fee_cents,
            notice_met=terms.notice_met,
            effective_timing=policy.cancellation_effective_timing,
            cancelled_at=cancelled_at,
        )


# --- Admin audit list -------------------------------------------------


class SelfCancellationAdminView(BaseModel):
    model_config = {"frozen": True}

    enrollment_id: str
    student_id: str
    session_id: str
    cancellation_reason: str | None
    cancellation_policy_snapshot: dict[str, Any] | None
    cancelled_at: datetime | None
    student_full_name: str | None = None
    session_title: str | None = None


class SelfCancellationEnrollmentQuery(Protocol):
    async def list_cancelled_by_parent(self) -> list[Enrollment]: ...


class SelfCancellationStudentQuery(Protocol):
    async def by_ids(self, student_ids: list[str]) -> list[Student]: ...


class SelfCancellationSessionQuery(Protocol):
    async def get_many(self, session_ids: list[str]) -> list[Any]: ...


class ListSelfCancellationsForAdmin:
    """Lists enrollments a parent self-cancelled (R4 audit list), newest
    ``cancelled_at`` first, enriched with student name + session title."""

    def __init__(
        self,
        *,
        enrollments: SelfCancellationEnrollmentQuery,
        students: SelfCancellationStudentQuery,
        sessions: SelfCancellationSessionQuery,
    ) -> None:
        self._enrollments = enrollments
        self._students = students
        self._sessions = sessions

    async def execute(self) -> list[SelfCancellationAdminView]:
        rows = await self._enrollments.list_cancelled_by_parent()
        rows = sorted(
            rows,
            key=lambda e: e.cancelled_at or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )
        student_ids = list({r.student_id for r in rows})
        session_ids = list({r.session_id for r in rows})
        names = {s.student_id: s.full_name for s in await self._students.by_ids(student_ids)}
        titles = {s.session_id: s.title for s in await self._sessions.get_many(session_ids)}
        return [
            SelfCancellationAdminView(
                enrollment_id=r.enrollment_id,
                student_id=r.student_id,
                session_id=r.session_id,
                cancellation_reason=r.cancellation_reason,
                cancellation_policy_snapshot=r.cancellation_policy_snapshot,
                cancelled_at=r.cancelled_at,
                student_full_name=names.get(r.student_id),
                session_title=titles.get(r.session_id),
            )
            for r in rows
        ]


__all__ = [
    "EnrollmentNotCancellable",
    "ListSelfCancellationsForAdmin",
    "PreviewSelfCancel",
    "PreviewSelfCancelView",
    "SelfCancelBillingPort",
    "SelfCancelEnrollment",
    "SelfCancelEnrollmentCommand",
    "SelfCancelEnrollmentQuery",
    "SelfCancelEnrollmentResult",
    "SelfCancelEnrollmentWriter",
    "SelfCancelOccurrenceQuery",
    "SelfCancelPolicyRepository",
    "SelfCancelStudentQuery",
    "SelfCancellationAdminView",
    "SelfCancellationEnrollmentQuery",
    "SelfCancellationSessionQuery",
    "SelfCancellationStudentQuery",
]
