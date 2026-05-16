"""Compose Admin BFF (Wave 3)."""

from __future__ import annotations

from typing import Any

from datetime import date, datetime, time, timezone

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.v2.contexts.billing.application.ports import StripeGateway
from backend.v2.contexts.billing.application.use_cases.finance import (  # FINANCE
    AcademyRevenueQuery,
    MongoExpenseRepository,
    MongoPayoutRepository,
    RecordExpense,
)
from backend.v2.contexts.billing.application.use_cases.issue_refund import IssueRefund
from backend.v2.contexts.billing.infrastructure.mongo_payment_repo import (
    MongoPaymentRepository,
)
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
from backend.v2.contexts.enrollment.infrastructure.mongo_enrollment_repo import (
    MongoEnrollmentRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_enrollment_writer import (
    MongoEnrollmentWriter,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_session_repo import (
    MongoSessionRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_session_writer import (
    MongoSessionWriter,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_student_repo import (
    MongoStudentRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_student_writer import (
    MongoStudentWriter,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_waitlist_repo import (
    MongoWaitlistRepository,
)
from backend.v2.interfaces.admin.deps import AdminUseCases
from backend.v2.shared.comms import CommsService, MongoMessageRepository
from backend.v2.shared.config import get_settings
from backend.v2.shared.events import Outbox
from backend.v2.shared.idempotency import IdempotencyStore


def compose_admin(
    db: AsyncIOMotorDatabase[Any],
    outbox: Outbox,
    idempotency_store: IdempotencyStore,
    stripe: StripeGateway,
) -> AdminUseCases:
    settings = get_settings()
    academy_id = settings.default_academy_id

    # Enrollment repos
    sessions_w = MongoSessionWriter(db)
    sessions_r = MongoSessionRepository(db)
    enrollments_w = MongoEnrollmentWriter(db)
    enrollments_r = MongoEnrollmentRepository(db)
    students_w = MongoStudentWriter(db)
    students_r = MongoStudentRepository(db)
    waitlist = MongoWaitlistRepository(db)

    create_session = CreateSession(sessions=sessions_w, academy_id=academy_id)
    cancel_session = CancelSession(
        sessions=sessions_w,
        enrollments_query=enrollments_r,
        enrollments_writer=enrollments_w,
        outbox=outbox,
        academy_id=academy_id,
    )
    edit_roster_add = EditRosterAdd(
        sessions=sessions_w,
        enrollments=enrollments_w,
        students=students_w,
        academy_id=academy_id,
    )
    cancel_enrollment = CancelEnrollment(
        enrollments=enrollments_w,
        sessions=sessions_w,
        outbox=outbox,
        academy_id=academy_id,
    )
    pause_enrollment = PauseEnrollment(enrollments=enrollments_w)
    resume_enrollment = ResumeEnrollment(enrollments=enrollments_w)
    join_waitlist = JoinWaitlist(waitlist=waitlist, academy_id=academy_id)
    promote = PromoteFromWaitlist(waitlist=waitlist, outbox=outbox, academy_id=academy_id)
    skip = SkipFromWaitlist(waitlist=waitlist)
    remove = RemoveFromWaitlist(waitlist=waitlist)

    # Billing
    payments_repo = MongoPaymentRepository(db)
    issue_refund = IssueRefund(
        payment_repo=payments_repo,
        stripe=stripe,
        outbox=outbox,
        idempotency_store=idempotency_store,
    )

    # Finance (# FINANCE)
    expenses_repo = MongoExpenseRepository(db)
    payouts_repo = MongoPayoutRepository(db)
    record_expense = RecordExpense(expenses=expenses_repo, academy_id=academy_id)
    revenue_query = AcademyRevenueQuery(payments=payments_repo)

    # Comms
    messages_repo = MongoMessageRepository(db)
    comms = CommsService(messages=messages_repo, academy_id=academy_id)

    # Closures for the BFF deps that need composed reads.
    async def list_admin_sessions(on_date: date | None):
        if on_date is None:
            on_date = datetime.now(timezone.utc).date()
        start = datetime.combine(on_date, time.min, tzinfo=timezone.utc)
        end = datetime.combine(on_date, time.max, tzinfo=timezone.utc)
        cursor = sessions_r._find_many(  # type: ignore[attr-defined]
            {"start_at": {"$gte": start, "$lte": end}},
            sort=[("start_at", 1)],
        )
        return [sessions_r._to_domain(doc) async for doc in cursor]  # type: ignore[attr-defined]

    async def list_admin_enrollments_for_session(session_id: str):
        active = await enrollments_r.active_for_session(session_id)
        if not active:
            return []
        students = await students_r.by_ids([e.student_id for e in active])
        by_id = {s.student_id: s for s in students}
        out: list[dict] = []
        for e in active:
            s = by_id.get(e.student_id)
            out.append(
                {
                    "enrollment_id": e.enrollment_id,
                    "session_id": e.session_id,
                    "student_id": e.student_id,
                    "student_name": s.full_name if s else "(unknown)",
                    "parent_id": s.parent_id if s else "",
                    "status": e.status,
                }
            )
        return out

    async def list_waitlist_for_session(session_id: str):
        cursor = waitlist._find_many(  # type: ignore[attr-defined]
            {"session_id": session_id},
            sort=[("joined_at", 1)],
        )
        return [waitlist._to_domain(doc) async for doc in cursor]  # type: ignore[attr-defined]

    async def list_payments_recent():
        cursor = payments_repo._find_many(  # type: ignore[attr-defined]
            {}, sort=[("created_at", -1)], limit=200
        )
        return [payments_repo._to_domain(doc) async for doc in cursor]  # type: ignore[attr-defined]

    return AdminUseCases(
        create_session=create_session,
        cancel_session=cancel_session,
        edit_roster_add=edit_roster_add,
        cancel_enrollment=cancel_enrollment,
        pause_enrollment=pause_enrollment,
        resume_enrollment=resume_enrollment,
        join_waitlist=join_waitlist,
        promote_from_waitlist=promote,
        skip_from_waitlist=skip,
        remove_from_waitlist=remove,
        issue_refund=issue_refund,
        list_payments_recent=list_payments_recent,
        record_expense=record_expense,
        expenses=expenses_repo,
        payouts=payouts_repo,
        revenue_query=revenue_query,
        list_admin_sessions=list_admin_sessions,
        list_admin_enrollments_for_session=list_admin_enrollments_for_session,
        list_waitlist_for_session=list_waitlist_for_session,
        comms=comms,
    )
