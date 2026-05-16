"""Admin BFF dependencies — heavy composition surface."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from backend.v2.contexts.billing.application.use_cases.finance import (  # FINANCE
    AcademyRevenueQuery,
    MongoExpenseRepository,
    MongoPayoutRepository,
    RecordExpense,
)
from backend.v2.contexts.billing.application.use_cases.issue_refund import IssueRefund
from backend.v2.contexts.enrollment.application.use_cases.admin_writes import (
    CancelEnrollment,
    CancelSession,
    CreateSession,
    EditRosterAdd,
    JoinWaitlist,
    PauseEnrollment,
    RemoveFromWaitlist,
    ResumeEnrollment,
    SkipFromWaitlist,
)
from backend.v2.contexts.enrollment.application.use_cases.promote_from_waitlist import (
    PromoteFromWaitlist,
)
from backend.v2.shared.comms import CommsService


@dataclass
class AdminUseCases:
    # sessions / roster
    create_session: CreateSession
    cancel_session: CancelSession
    edit_roster_add: EditRosterAdd
    cancel_enrollment: CancelEnrollment
    pause_enrollment: PauseEnrollment
    resume_enrollment: ResumeEnrollment
    # waitlist
    join_waitlist: JoinWaitlist
    promote_from_waitlist: PromoteFromWaitlist
    skip_from_waitlist: SkipFromWaitlist
    remove_from_waitlist: RemoveFromWaitlist
    # billing
    issue_refund: IssueRefund
    list_payments_recent: object  # callable
    # finance (# FINANCE)
    record_expense: RecordExpense
    expenses: MongoExpenseRepository
    payouts: MongoPayoutRepository
    revenue_query: AcademyRevenueQuery
    # reads
    list_admin_sessions: object  # callable
    list_admin_enrollments_for_session: object  # callable
    list_waitlist_for_session: object  # callable
    # comms
    comms: CommsService


def get_admin_use_cases(request: Request) -> AdminUseCases:
    return request.app.state.admin  # type: ignore[no-any-return]
