"""Compose Admin BFF (Wave 3)."""

from __future__ import annotations

import csv
import io
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from bson import ObjectId as BsonObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.v2.contexts.billing.application.ports import StripeGateway
from backend.v2.contexts.billing.application.use_cases.admin_payment_ops import (
    ApplyPaymentDiscount,
    GenerateMonthlyPayments,
    MarkPaymentPaid,
    SendDuesReminders,
    UndoPaymentPaid,
)
from backend.v2.contexts.billing.application.use_cases.finance import (  # FINANCE
    AcademyRevenueQuery,
    DeleteExpense,
    EditExpense,
    MongoExpenseRepository,
    MongoPayoutRepository,
    RecordExpense,
)
from backend.v2.contexts.billing.application.use_cases.issue_refund import IssueRefund
from backend.v2.contexts.billing.application.use_cases.quote_enrollment import (
    QuoteEnrollment,
    QuoteEnrollmentCommand,
)
from backend.v2.contexts.billing.application.use_cases.withdrawal_credit import (
    ApproveWithdrawalCredit,
    PreviewWithdrawalCredit,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_ledger_repo import (
    MongoBillingLedgerRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_credit_ledger_repo import (
    MongoCreditLedgerRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_payment_repo import (
    MongoPaymentRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_subscription_repo import (
    MongoSubscriptionRepository,
)
from backend.v2.contexts.enrollment.application.use_cases.admin_directory import (
    GetAdminStudent,
    ListAdminStudents,
    UpdateAdminStudent,
)
from backend.v2.contexts.enrollment.application.use_cases.admin_writes import (
    CancelEnrollment,
    CancelSession,
    CreateSession,
    EditRosterAdd,
    EditSession,
    JoinWaitlist,
    PauseEnrollment,
    RemoveFromWaitlist,
    ResumeEnrollment,
    SkipFromWaitlist,
    TransferEnrollment,
    WithdrawEnrollment,
)
from backend.v2.contexts.enrollment.application.use_cases.pause_requests import (
    ApprovePauseRequest,
    DeclinePauseRequest,
    ListAdminPauseRequests,
)
from backend.v2.contexts.enrollment.application.use_cases.promote_from_waitlist import (
    PromoteFromWaitlist,
)
from backend.v2.contexts.enrollment.domain.events import EnrollmentLifecycleEvent
from backend.v2.contexts.enrollment.infrastructure.mongo_enrollment_event_repo import (
    MongoEnrollmentEventRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_enrollment_repo import (
    MongoEnrollmentRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_enrollment_writer import (
    MongoEnrollmentWriter,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_occurrence_repo import (
    MongoSessionOccurrenceRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_pause_request_repo import (
    MongoPauseRequestRepository,
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
from backend.v2.contexts.identity.application.change_user_role_use_case import ChangeUserRole
from backend.v2.contexts.identity.application.get_academy_fees_use_case import GetAcademyFeesUseCase
from backend.v2.contexts.identity.application.get_academy_gateway_use_case import (
    GetAcademyGatewayUseCase,
)
from backend.v2.contexts.identity.application.get_academy_notifications_use_case import (
    GetAcademyNotificationsUseCase,
)
from backend.v2.contexts.identity.application.get_academy_use_case import GetAcademyUseCase
from backend.v2.contexts.identity.application.update_academy_fees_use_case import (
    UpdateAcademyFeesUseCase,
)
from backend.v2.contexts.identity.application.update_academy_notifications_use_case import (
    UpdateAcademyNotificationsUseCase,
)
from backend.v2.contexts.identity.application.update_academy_use_case import UpdateAcademyUseCase
from backend.v2.contexts.identity.application.use_cases.admin_directory import (
    GetAdminUser,
    ListAdminUsers,
    UpdateAdminUser,
)
from backend.v2.contexts.identity.infrastructure.mongo_academy_repo import MongoAcademyRepository
from backend.v2.contexts.identity.infrastructure.mongo_user_repo import MongoUserRepository
from backend.v2.contexts.onboarding.application.use_cases.admin_waiver_templates import (
    ManageAdminWaiverTemplates,
)
from backend.v2.contexts.onboarding.application.use_cases.admin_waivers import (
    ListAdminWaivers,
)
from backend.v2.contexts.onboarding.infrastructure.mongo_admin_waiver_repo import (
    MongoAdminWaiverRepository,
)
from backend.v2.contexts.onboarding.infrastructure.mongo_waiver_template_repo import (
    MongoWaiverTemplateRepository,
)
from backend.v2.interfaces.admin.deps import AdminUseCases
from backend.v2.shared.comms import CommsService, MongoMessageRepository
from backend.v2.shared.config import get_settings
from backend.v2.shared.events import Outbox
from backend.v2.shared.idempotency import IdempotencyStore
from backend.v2.shared.ids import new_ulid


def _make_reports_kpis(db: AsyncIOMotorDatabase[Any]) -> object:
    """Returns an async callable that computes KPIs on-demand from live collections."""
    from datetime import UTC, datetime, timedelta

    from backend.v2.shared.tenancy import current_academy_id

    async def get_reports_kpis() -> dict[str, int | float]:
        academy_id = current_academy_id()
        now = datetime.now(UTC)
        period_str = now.strftime("%Y-%m")
        cutoff_30d = now - timedelta(days=30)

        # active_students: distinct students with active enrollment
        pipeline_students = [
            {"$match": {"academy_id": academy_id, "status": "active"}},
            {"$group": {"_id": "$student_id"}},
            {"$count": "n"},
        ]
        res = await db.enrollments.aggregate(pipeline_students).to_list(length=1)
        active_students: int = res[0]["n"] if res else 0

        # attendance_rate_30d
        pipeline_att = [
            {
                "$match": {
                    "academy_id": academy_id,
                    "marked_at": {"$gte": cutoff_30d},
                    "status": {"$in": ["present", "absent", "late"]},
                }
            },
            {
                "$group": {
                    "_id": None,
                    "present": {
                        "$sum": {"$cond": [{"$in": ["$status", ["present", "late"]]}, 1, 0]}
                    },
                    "total": {"$sum": 1},
                }
            },
        ]
        res2 = await db.attendance.aggregate(pipeline_att).to_list(length=1)
        if res2 and res2[0]["total"] > 0:
            attendance_rate_30d = round(res2[0]["present"] / res2[0]["total"], 4)
        else:
            attendance_rate_30d = 0.0

        # dues_collected_mtd
        pipeline_dues = [
            {
                "$match": {
                    "academy_id": academy_id,
                    "status": {"$in": ["succeeded", "paid"]},
                    "period": period_str,
                }
            },
            {"$group": {"_id": None, "total": {"$sum": "$amount_cents"}}},
        ]
        res3 = await db.payments.aggregate(pipeline_dues).to_list(length=1)
        dues_collected_mtd_cents: int = res3[0]["total"] if res3 else 0

        # pending_waivers
        active_student_ids_cursor = db.enrollments.find(
            {"academy_id": academy_id, "status": "active"}, {"student_id": 1}
        )
        active_ids = {doc["student_id"] async for doc in active_student_ids_cursor}
        signed_cursor = db.waiver_acceptances.find(
            {
                "academy_id": academy_id,
                "student_id": {"$in": list(active_ids)},
                "is_deleted": {"$ne": True},
            },
            {"student_id": 1},
        )
        signed_ids = {doc["student_id"] async for doc in signed_cursor}
        pending_waivers = len(active_ids - signed_ids)

        return {
            "active_students": active_students,
            "attendance_rate_30d": attendance_rate_30d,
            "dues_collected_mtd_cents": dues_collected_mtd_cents,
            "pending_waivers": pending_waivers,
        }

    return get_reports_kpis


def _month_bounds(period: str) -> tuple[datetime, datetime]:
    year_str, month_str = period.split("-", 1)
    year = int(year_str)
    month = int(month_str)
    start = datetime(year, month, 1, tzinfo=UTC)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=UTC)
    else:
        end = datetime(year, month + 1, 1, tzinfo=UTC)
    return start, end


def _payment_final_amount_cents(payment: dict[str, Any]) -> int:
    for key in ("final_amount_cents", "amount_cents", "gross_amount_cents"):
        value = payment.get(key)
        if value is not None:
            return int(value)
    return 0


def _payment_collected_cents(payment: dict[str, Any]) -> int:
    status = str(payment.get("status") or "")
    if status in {"partially_paid", "pending", "failed"}:
        return max(
            int(payment.get("paid_amount_cents") or payment.get("amount_received_cents") or 0),
            0,
        )
    if status in {"succeeded", "paid", "partially_refunded", "refunded"}:
        paid = int(
            payment.get("paid_amount_cents")
            or payment.get("amount_received_cents")
            or _payment_final_amount_cents(payment)
        )
        return max(paid - int(payment.get("refunded_cents") or 0), 0)
    return 0


def _payment_outstanding_cents(payment: dict[str, Any]) -> int:
    status = str(payment.get("status") or "")
    if status not in {"pending", "failed", "partially_paid"}:
        return 0
    balance = payment.get("balance_due_cents")
    if balance is not None:
        return max(int(balance), 0)
    return max(_payment_final_amount_cents(payment) - _payment_collected_cents(payment), 0)


def _make_reports_dashboard(db: AsyncIOMotorDatabase[Any]) -> object:
    """Returns an async callable for the owner finance/operations dashboard."""
    from backend.v2.shared.tenancy import current_academy_id

    async def get_reports_dashboard(period: str) -> dict[str, Any]:
        academy_id = current_academy_id()
        start, end = _month_bounds(period)

        cash_collected_cents = 0
        outstanding_dues_cents = 0
        payment_rows = 0
        payments_cursor = db["payments"].find(
            {
                "academy_id": academy_id,
                "period": period,
                "is_deleted": {"$ne": True},
            }
        )
        async for payment in payments_cursor:
            payment_rows += 1
            cash_collected_cents += _payment_collected_cents(payment)
            outstanding_dues_cents += _payment_outstanding_cents(payment)

        present_count = 0
        recorded_count = 0
        attendance_cursor = db["attendance"].find(
            {
                "academy_id": academy_id,
                "marked_at": {"$gte": start, "$lt": end},
                "status": {"$in": ["present", "late", "absent"]},
            }
        )
        async for attendance in attendance_cursor:
            recorded_count += 1
            if str(attendance.get("status")) in {"present", "late"}:
                present_count += 1
        attendance_rate = round(present_count / recorded_count, 4) if recorded_count else None

        session_ids: list[str] = []
        scheduled_count = 0
        completed_count = 0
        cancelled_count = 0
        capacity = 0
        sessions_cursor = db["sessions"].find(
            {
                "academy_id": academy_id,
                "start_at": {"$gte": start, "$lt": end},
                "is_deleted": {"$ne": True},
            }
        )
        async for session in sessions_cursor:
            session_id = str(session.get("session_id") or session.get("_id"))
            session_ids.append(session_id)
            status = str(session.get("status") or "scheduled")
            if status == "completed":
                completed_count += 1
            elif status == "cancelled":
                cancelled_count += 1
            else:
                scheduled_count += 1
            if status != "cancelled":
                capacity += int(session.get("capacity") or session.get("max_students") or 0)

        enrolled_seats = 0
        if session_ids:
            enrollments_cursor = db["enrollments"].find(
                {
                    "academy_id": academy_id,
                    "session_id": {"$in": session_ids},
                    "status": "active",
                    "is_deleted": {"$ne": True},
                },
                {"student_id": 1},
            )
            async for _enrollment in enrollments_cursor:
                enrolled_seats += 1
        capacity_utilization = round(enrolled_seats / capacity, 4) if capacity else None

        empty_states: list[str] = []
        if cash_collected_cents == 0:
            empty_states.append("No collected payment rows found for this month.")
        if recorded_count == 0:
            empty_states.append("No attendance marks found for this month.")
        if not session_ids:
            empty_states.append("No sessions found for this month.")

        return {
            "period": period,
            "cash_collected_cents": cash_collected_cents,
            "outstanding_dues_cents": outstanding_dues_cents,
            "attendance": {
                "present_count": present_count,
                "recorded_count": recorded_count,
                "attendance_rate": attendance_rate,
                "empty": recorded_count == 0,
            },
            "sessions": {
                "scheduled_count": scheduled_count,
                "completed_count": completed_count,
                "cancelled_count": cancelled_count,
                "enrolled_seats": enrolled_seats,
                "capacity": capacity,
                "capacity_utilization": capacity_utilization,
                "empty": not session_ids,
            },
            "empty_states": empty_states,
        }

    return get_reports_dashboard


def _make_list_enrollment_events(db: Any) -> object:
    from backend.v2.shared.tenancy import current_academy_id

    async def list_enrollment_events(enrollment_id: str) -> list[dict]:
        academy_id = current_academy_id()
        cursor = db.enrollment_events.find(
            {"enrollment_id": enrollment_id, "academy_id": academy_id},
            sort=[("occurred_at", 1)],
        )
        results = []
        async for doc in cursor:
            results.append(
                {
                    "event_id": str(doc.get("event_id") or doc.get("_id", "")),
                    "event_type": str(doc.get("event_type", "")),
                    "effective_date": str(doc.get("effective_at", ""))[:10],
                    "actor_id": str(doc.get("actor_id", "")),
                    "reason": doc.get("reason"),
                    "billing_result": doc.get("billing_result"),
                    "credit_id": doc.get("credit_id"),
                }
            )
        return results

    return list_enrollment_events


def compose_admin(
    db: AsyncIOMotorDatabase[Any],
    outbox: Outbox,
    idempotency_store: IdempotencyStore,
    stripe: StripeGateway,
) -> AdminUseCases:
    settings = get_settings()
    academy_id = settings.default_academy_id

    # Enrollment repos
    users_r = MongoUserRepository(db, default_academy_id=academy_id)
    sessions_w = MongoSessionWriter(db)
    sessions_r = MongoSessionRepository(db)
    occurrences_r = MongoSessionOccurrenceRepository(db)
    enrollments_w = MongoEnrollmentWriter(db)
    enrollments_r = MongoEnrollmentRepository(db)
    enrollment_events = MongoEnrollmentEventRepository(db)
    students_w = MongoStudentWriter(db)
    students_r = MongoStudentRepository(db)
    waitlist = MongoWaitlistRepository(db)
    pause_requests = MongoPauseRequestRepository(db)

    create_session = CreateSession(sessions=sessions_w, academy_id=academy_id)
    edit_session = EditSession(sessions=sessions_w)
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
        enrollment_events=enrollment_events,
        academy_id=academy_id,
    )
    cancel_enrollment = CancelEnrollment(
        enrollments=enrollments_w,
        sessions=sessions_w,
        outbox=outbox,
        enrollment_events=enrollment_events,
        academy_id=academy_id,
    )
    transfer_enrollment = TransferEnrollment(
        enrollments=enrollments_w,
        sessions=sessions_w,
        enrollment_events=enrollment_events,
    )
    pause_enrollment = PauseEnrollment(
        enrollments=enrollments_w,
        sessions=sessions_w,
        students=students_r,
        waitlist=waitlist,
        enrollment_events=enrollment_events,
    )
    resume_enrollment = ResumeEnrollment(
        enrollments=enrollments_w,
        sessions=sessions_w,
        waitlist=waitlist,
        enrollment_events=enrollment_events,
    )
    withdraw_enrollment = WithdrawEnrollment(
        enrollments=enrollments_w,
        enrollment_events=enrollment_events,
    )
    join_waitlist = JoinWaitlist(
        waitlist=waitlist,
        enrollment_events=enrollment_events,
        academy_id=academy_id,
    )
    promote = PromoteFromWaitlist(
        waitlist=waitlist,
        sessions=sessions_w,
        enrollments=enrollments_w,
        outbox=outbox,
        enrollment_events=enrollment_events,
        academy_id=academy_id,
    )
    skip = SkipFromWaitlist(waitlist=waitlist)
    remove = RemoveFromWaitlist(waitlist=waitlist)
    list_admin_pause_requests = ListAdminPauseRequests(pause_requests=pause_requests)
    approve_pause_request = ApprovePauseRequest(pause_requests=pause_requests)
    decline_pause_request = DeclinePauseRequest(pause_requests=pause_requests)

    # Billing
    billing_ledger_repo = MongoBillingLedgerRepository(db)
    credits_repo = MongoCreditLedgerRepository(db)
    payments_repo = MongoPaymentRepository(db, credit_ledger=credits_repo)
    subscriptions_repo = MongoSubscriptionRepository(db)
    issue_refund = IssueRefund(
        payment_repo=payments_repo,
        stripe=stripe,
        outbox=outbox,
        idempotency_store=idempotency_store,
    )
    generate_monthly_payments = GenerateMonthlyPayments(payments=payments_repo)
    mark_payment_paid = MarkPaymentPaid(payments=payments_repo)
    apply_payment_discount = ApplyPaymentDiscount(payments=payments_repo)
    undo_payment_paid = UndoPaymentPaid(payments=payments_repo)
    preview_withdrawal_credit = PreviewWithdrawalCredit(
        payments=payments_repo,
        enrollments=enrollments_w,
    )
    approve_withdrawal_credit = ApproveWithdrawalCredit(
        payments=payments_repo,
        credits=credits_repo,
        enrollments=enrollments_w,
        subscriptions=subscriptions_repo,
        stripe=stripe,
        enrollment_events=_EnrollmentLifecycleEventSink(enrollment_events),
        academy_id=academy_id,
    )

    # Finance (# FINANCE)
    expenses_repo = MongoExpenseRepository(db)
    payouts_repo = MongoPayoutRepository(db)
    record_expense = RecordExpense(expenses=expenses_repo, academy_id=academy_id)
    edit_expense = EditExpense(expenses=expenses_repo)
    delete_expense = DeleteExpense(expenses=expenses_repo)
    revenue_query = AcademyRevenueQuery(payments=payments_repo)

    # Comms
    messages_repo = MongoMessageRepository(db)
    comms = CommsService(messages=messages_repo, academy_id=academy_id)
    waivers_repo = MongoAdminWaiverRepository(db)
    list_admin_waivers = ListAdminWaivers(waivers_repo)
    waiver_templates_repo = MongoWaiverTemplateRepository(db)
    manage_admin_waiver_templates = ManageAdminWaiverTemplates(waiver_templates_repo)
    # Identity / Settings
    academy_repo = MongoAcademyRepository(db)
    get_academy_use_case = GetAcademyUseCase(academy_repo)
    update_academy_use_case = UpdateAcademyUseCase(academy_repo)
    get_academy_fees_use_case = GetAcademyFeesUseCase(academy_repo)
    update_academy_fees_use_case = UpdateAcademyFeesUseCase(academy_repo)
    get_academy_notifications_use_case = GetAcademyNotificationsUseCase(academy_repo)
    update_academy_notifications_use_case = UpdateAcademyNotificationsUseCase(academy_repo)
    get_academy_gateway_use_case = GetAcademyGatewayUseCase(academy_repo)
    change_user_role = ChangeUserRole(users_r)

    list_admin_users = ListAdminUsers(users_r)
    get_admin_user = GetAdminUser(users_r)
    update_admin_user = UpdateAdminUser(users_r)
    list_admin_students = ListAdminStudents(students_r)
    get_admin_student = GetAdminStudent(students_r)
    update_admin_student = UpdateAdminStudent(students_r)

    # Closures for the BFF deps that need composed reads.
    # Day-of-week abbreviations used by the legacy seed schema.
    _DOW_MAP = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}

    async def _build_admin_session_rows(docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for doc in docs:
            session_id = str(doc.get("session_id") or doc.get("_id"))
            enrolled_count = await enrollments_r.collection.count_documents(
                {
                    "academy_id": academy_id,
                    "session_id": session_id,
                    "status": "active",
                }
            )
            waitlist_count = await waitlist.collection.count_documents(
                {
                    "academy_id": academy_id,
                    "session_id": session_id,
                    "status": "waiting",
                }
            )
            rows.append(
                {
                    "session_id": session_id,
                    "title": str(doc.get("title") or doc.get("name") or "Session"),
                    "location": str(doc.get("location") or ""),
                    "start_at": doc["start_at"],
                    "end_at": doc["end_at"],
                    "capacity": int(doc.get("capacity") or doc.get("max_students") or 15),
                    "status": "scheduled"
                    if str(doc.get("status") or "scheduled") == "active"
                    else str(doc.get("status") or "scheduled"),
                    "coach_id": str(doc.get("coach_id") or ""),
                    "enrolled_count": enrolled_count,
                    "waitlist_count": waitlist_count,
                }
            )

        # Batch coach-name enrichment (one DB call, no N+1).
        coach_ids = list({r["coach_id"] for r in rows if r["coach_id"]})
        coach_map: dict[str, str] = {}
        if coach_ids:
            oid_ids = [BsonObjectId(c) for c in coach_ids if BsonObjectId.is_valid(c)]
            or_filter: list[dict[str, object]] = [
                {"user_id": {"$in": coach_ids}},
                {"firebase_uid": {"$in": coach_ids}},
            ]
            if oid_ids:
                or_filter.append({"_id": {"$in": oid_ids}})
            users_cursor = db["users"].find({"$or": or_filter})
            async for user_doc in users_cursor:
                name = str(
                    user_doc.get("display_name")
                    or f"{user_doc.get('first_name', '')} {user_doc.get('last_name', '')}".strip()
                    or ""
                )
                for key in (
                    str(user_doc.get("user_id") or ""),
                    str(user_doc.get("firebase_uid") or ""),
                    str(user_doc.get("_id") or ""),
                ):
                    if key and key in coach_ids:
                        coach_map[key] = name

            for row in rows:
                row["coach_name"] = coach_map.get(row["coach_id"])

        return rows

    async def list_admin_sessions(on_date: date | None, *, window: str | None = None):
        # window="upcoming" returns all dated sessions from now through +30d.
        # Used by the transfer-enrollment dropdown so the user can pick any
        # upcoming session, not just today's.
        if window == "upcoming":
            now = datetime.now(UTC)
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(days=30)
            v2_cursor = sessions_r._find_many(  # type: ignore[attr-defined]
                {"start_at": {"$gte": start, "$lte": end}},
                sort=[("start_at", 1)],
            )
            upcoming_docs = [doc async for doc in v2_cursor]
            # Legacy synthesis intentionally skipped — only relevant when a
            # single date is queried. Fresh seeds emit dated v2 instances.
            return await _build_admin_session_rows(upcoming_docs)

        if on_date is None:
            on_date = datetime.now(UTC).date()
        start = datetime.combine(on_date, time.min, tzinfo=UTC)
        end = datetime.combine(on_date, time.max, tzinfo=UTC)

        # Query both v2 sessions (start_at field) and legacy recurring templates
        # (days_of_week field). The two schemas coexist during migration.
        all_docs: list[dict[str, Any]] = []

        # v2 schema: individual session instances with start_at/end_at
        v2_cursor = sessions_r._find_many(  # type: ignore[attr-defined]
            {"start_at": {"$gte": start, "$lte": end}},
            sort=[("start_at", 1)],
        )
        async for doc in v2_cursor:
            all_docs.append(doc)

        # Legacy schema: recurring templates with days_of_week + start_time/end_time
        today_dow = on_date.weekday()  # Mon=0 … Sun=6
        legacy_cursor = sessions_r._find_many(  # type: ignore[attr-defined]
            {"days_of_week": {"$exists": True}, "start_at": {"$exists": False}},
        )
        async for doc in legacy_cursor:
            dow_strs: list[str] = list(doc.get("days_of_week") or [])
            dow_ints = [_DOW_MAP[d] for d in dow_strs if d in _DOW_MAP]
            if today_dow not in dow_ints:
                continue
            # Synthetic start_at/end_at for the queried date
            st_str = str(doc.get("start_time") or "00:00")
            et_str = str(doc.get("end_time") or "00:00")
            sh, sm = int(st_str[:2]), int(st_str[3:5])
            eh, em = int(et_str[:2]), int(et_str[3:5])
            doc = dict(doc)
            doc["start_at"] = datetime.combine(on_date, time(sh, sm), tzinfo=UTC)
            doc["end_at"] = datetime.combine(on_date, time(eh, em), tzinfo=UTC)
            # Normalise to v2 field names so _build_row works uniformly
            if "session_id" not in doc:
                doc["session_id"] = str(doc["_id"])
            if "title" not in doc:
                doc["title"] = str(doc.get("name") or "Session")
            if "capacity" not in doc:
                doc["capacity"] = doc.get("max_students", 15)
            all_docs.append(doc)

        return await _build_admin_session_rows(all_docs)

    async def list_admin_enrollments_for_session(session_id: str):
        cursor = enrollments_r._find_many(  # type: ignore[attr-defined]
            {"session_id": session_id, "status": "active"},
            sort=[("created_at", 1), ("enrollment_id", 1)],
        )
        enrollment_docs = [doc async for doc in cursor]
        if not enrollment_docs:
            return []
        active = [enrollments_r._to_domain(doc) for doc in enrollment_docs]  # type: ignore[attr-defined]
        students = await students_r.by_ids([e.student_id for e in active])
        by_id = {s.student_id: s for s in students}
        out: list[dict] = []
        by_enrollment_id = {
            str(doc["enrollment_id"]): doc for doc in enrollment_docs if "enrollment_id" in doc
        }
        for e in active:
            doc = by_enrollment_id.get(e.enrollment_id, {})
            s = by_id.get(e.student_id)
            full_name = s.full_name if s else "(unknown)"
            out.append(
                {
                    "enrollment_id": e.enrollment_id,
                    "session_id": e.session_id,
                    "student_id": e.student_id,
                    "student_name": full_name,
                    "full_name": full_name,
                    "parent_id": s.parent_id if s else "",
                    "status": e.status,
                    # Prefer the semantic enrolled_at field (v2/seed); fall back
                    # to created_at for any legacy docs that only have that.
                    "enrolled_at": doc.get("enrolled_at") or doc.get("created_at"),
                }
            )
        return out

    async def _occurrence_row(occurrence) -> dict[str, Any]:
        attendance_cursor = db.attendance.find(
            {"academy_id": academy_id, "occurrence_id": occurrence.occurrence_id},
            sort=[("marked_at", -1)],
        )
        marked_by: set[str] = set()
        last_marked_at = None
        count = 0
        async for attendance in attendance_cursor:
            count += 1
            if last_marked_at is None:
                last_marked_at = attendance.get("marked_at")
            marker = attendance.get("marked_by")
            if marker:
                marked_by.add(str(marker))
        return {
            "occurrence_id": occurrence.occurrence_id,
            "session_id": occurrence.template_session_id or occurrence.session_id,
            "start_at": occurrence.start_at,
            "end_at": occurrence.end_at,
            "status": occurrence.status,
            "scheduled_coach_id": occurrence.scheduled_coach_id,
            "actual_coach_id": occurrence.actual_coach_id,
            "substitute_coach_id": occurrence.substitute_coach_id,
            "attendance_marked_count": count,
            "attendance_marked_by": sorted(marked_by),
            "attendance_last_marked_at": last_marked_at,
        }

    async def list_session_occurrences(session_id: str) -> list[dict[str, Any]]:
        occurrences = await occurrences_r.list_for_session(session_id)
        return [await _occurrence_row(occurrence) for occurrence in occurrences]

    async def update_session_occurrence_coach(
        *,
        occurrence_id: str,
        actual_coach_id: str | None,
        substitute_coach_id: str | None,
        actor_id: str,
        reason: str,
    ) -> dict[str, Any] | None:
        _ = actor_id
        occurrence = await occurrences_r.update_coach_assignment(
            occurrence_id=occurrence_id,
            actual_coach_id=actual_coach_id,
            substitute_coach_id=substitute_coach_id,
            assignment_reason=reason,
        )
        return None if occurrence is None else await _occurrence_row(occurrence)

    async def list_waitlist_for_session(session_id: str):
        cursor = waitlist._find_many(  # type: ignore[attr-defined]
            {"session_id": session_id},
            sort=[("joined_at", 1)],
        )
        entries = [waitlist._to_domain(doc) async for doc in cursor]  # type: ignore[attr-defined]
        students = await students_r.by_ids([e.student_id for e in entries])
        by_id = {s.student_id: s for s in students}
        rows = []
        for idx, entry in enumerate(entries, start=1):
            student = by_id.get(entry.student_id)
            rows.append(
                {
                    "waitlist_id": entry.waitlist_id,
                    "session_id": entry.session_id,
                    "student_id": entry.student_id,
                    "parent_id": entry.parent_id,
                    "joined_at": entry.joined_at,
                    "added_at": entry.joined_at,
                    "status": entry.status,
                    "position": idx,
                    "full_name": student.full_name if student else "(unknown)",
                }
            )
        return rows

    async def list_payments_recent():
        return await payments_repo.list_recent_admin()

    _quote_enrollment_uc = QuoteEnrollment(
        sessions=payments_repo,
        snapshots=payments_repo,
        occurrences=payments_repo,
    )

    async def quote_enrollment(
        *, session_id: str, student_id: str | None = None, start_date: str | None = None
    ):
        return await _quote_enrollment_uc.execute(
            QuoteEnrollmentCommand(
                session_id=session_id,
                billing_start_at=_start_date_to_datetime(start_date),
                calculated_by="admin",
                student_id=student_id,
            )
        )

    async def list_audit_logs():
        cursor = (
            db["audit_logs"].find({"academy_id": academy_id}).sort([("created_at", -1)]).limit(200)
        )
        rows: list[dict[str, Any]] = []
        async for doc in cursor:
            rows.append(
                {
                    "audit_id": str(doc.get("audit_id") or doc.get("_id")),
                    "actor_id": doc.get("actor_id") or doc.get("user_id"),
                    "action": str(doc.get("action") or doc.get("event") or "unknown"),
                    "entity_type": doc.get("entity_type") or doc.get("resource_type"),
                    "entity_id": doc.get("entity_id") or doc.get("resource_id"),
                    "created_at": doc.get("created_at") or datetime.now(UTC),
                }
            )
        return rows

    async def list_dues_followup():
        cursor = payments_repo._find_many(  # type: ignore[attr-defined]
            {"status": "pending", "is_deleted": {"$ne": True}},
            sort=[("created_at", -1)],
            limit=500,
        )
        totals: dict[str, dict[str, Any]] = {}
        async for payment in cursor:
            row = payments_repo._to_admin_row(payment, None)  # type: ignore[attr-defined]
            parent_id = str(row["parent_id"])
            entry = totals.setdefault(
                parent_id,
                {
                    "parent_id": parent_id,
                    "parent_name": None,
                    "email": None,
                    "pending_count": 0,
                    "total_due_cents": 0,
                },
            )
            entry["pending_count"] += 1
            entry["total_due_cents"] += int(row["final_amount_cents"])
        if totals:
            parent_id_list = list(totals)
            oid_ids = [BsonObjectId(p) for p in parent_id_list if BsonObjectId.is_valid(p)]
            or_filter: list[dict[str, object]] = [
                {"user_id": {"$in": parent_id_list}},
                {"firebase_uid": {"$in": parent_id_list}},
            ]
            if oid_ids:
                or_filter.append({"_id": {"$in": oid_ids}})
            users = db["users"].find({"academy_id": academy_id, "$or": or_filter})
            async for user in users:
                for key in (
                    str(user.get("user_id") or ""),
                    str(user.get("firebase_uid") or ""),
                    str(user["_id"]),
                ):
                    if key and key in totals:
                        totals[key]["parent_name"] = str(
                            user.get("display_name")
                            or f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
                            or ""
                        )
                        totals[key]["email"] = user.get("email")
        return sorted(totals.values(), key=lambda row: int(row["total_due_cents"]), reverse=True)

    async def get_billing_invoice_detail(invoice_id: str) -> dict[str, Any]:
        invoice = await db["invoices"].find_one(
            {
                "academy_id": academy_id,
                "$or": [{"invoice_id": invoice_id}, {"invoice_number": invoice_id}],
            }
        )
        if invoice is not None:
            inv_id = str(invoice.get("invoice_id") or invoice_id)
            lines = [
                {
                    "description": str(line.get("description", "")),
                    "amount_cents": int(line.get("amount_cents", 0)),
                }
                async for line in db["invoice_lines"].find(
                    {"academy_id": academy_id, "invoice_id": inv_id}
                )
            ]
            allocations = [
                {
                    "payment_id": str(row.get("payment_id", "")),
                    "amount_cents": int(row.get("amount_cents", 0)),
                }
                async for row in db["payment_allocations"].find(
                    {"academy_id": academy_id, "invoice_id": inv_id}
                )
            ]
            credit_usage = [
                {
                    "credit_id": str(row.get("credit_id", "")),
                    "amount_cents": int(row.get("amount_cents", 0)),
                }
                async for row in db["credit_applications"].find(
                    {"academy_id": academy_id, "invoice_id": inv_id}
                )
            ]
            total = int(invoice.get("total_cents", 0))
            due = int(invoice.get("balance_due_cents", 0))
            return {
                "invoice_number": str(invoice.get("invoice_number") or inv_id),
                "period": str(invoice.get("period") or ""),
                "lines": lines,
                "due_amount_cents": due,
                "paid_amount_cents": max(total - due, 0),
                "status": str(invoice.get("status", "open")),
                "allocations": allocations,
                "credit_usage": credit_usage,
                "invoice_pdf_artifact_id": invoice.get("invoice_pdf_artifact_id")
                or invoice.get("pdf_artifact_id"),
                "receipt_artifact_id": invoice.get("receipt_artifact_id"),
            }

        payment = await payments_repo._find_one(  # type: ignore[attr-defined]
            {"$or": [{"payment_id": invoice_id}, {"invoice_number": invoice_id}]}
        )
        if payment is None:
            from backend.v2.contexts.billing.domain.errors import PaymentNotFound

            raise PaymentNotFound("invoice not found", payment_id=invoice_id)
        row = payments_repo._to_admin_row(payment, None)  # type: ignore[attr-defined]
        final_amount = int(row["final_amount_cents"])
        paid_amount = int(row.get("paid_amount_cents") or 0)
        if paid_amount == 0 and str(row["status"]) == "succeeded":
            paid_amount = final_amount
        due = int(row.get("balance_due_cents") or max(final_amount - paid_amount, 0))
        allocations = []
        if paid_amount:
            allocations.append({"payment_id": str(row["payment_id"]), "amount_cents": paid_amount})
        credit_usage = []
        applied_credit = int(payment.get("applied_credit_cents", 0))
        if applied_credit:
            credit_usage.append({"credit_id": "account_credit", "amount_cents": applied_credit})
        return {
            "invoice_number": str(payment.get("invoice_number") or row["payment_id"]),
            "period": str(payment.get("period") or ""),
            "lines": [
                {
                    "description": f"Tuition {payment.get('period') or ''}".strip(),
                    "amount_cents": int(payment.get("gross_amount_cents") or row["amount_cents"]),
                }
            ],
            "due_amount_cents": due,
            "paid_amount_cents": paid_amount,
            "status": str(row["status"]),
            "allocations": allocations,
            "credit_usage": credit_usage,
            "invoice_pdf_artifact_id": payment.get("invoice_pdf_artifact_id"),
            "receipt_artifact_id": payment.get("receipt_artifact_id"),
        }

    async def generate_billing_invoice_artifact(
        invoice_id: str, artifact_type: str
    ) -> dict[str, Any]:
        artifact_id = str(new_ulid())
        now = datetime.now(UTC)
        await db["billing_artifacts"].insert_one(
            {
                "academy_id": academy_id,
                "artifact_id": artifact_id,
                "invoice_id": invoice_id,
                "artifact_type": artifact_type,
                "status": "generated",
                "created_at": now,
            }
        )
        field = "receipt_artifact_id" if artifact_type == "receipt" else "invoice_pdf_artifact_id"
        await db["invoices"].update_one(
            {
                "academy_id": academy_id,
                "$or": [{"invoice_id": invoice_id}, {"invoice_number": invoice_id}],
            },
            {"$set": {field: artifact_id, "updated_at": now}},
        )
        await db["payments"].update_one(
            {
                "academy_id": academy_id,
                "$or": [{"payment_id": invoice_id}, {"invoice_number": invoice_id}],
            },
            {"$set": {field: artifact_id, "updated_at": now}},
        )
        return {"artifact_id": artifact_id, "artifact_type": artifact_type, "status": "generated"}

    class _DuesReminderSender:
        async def send_dues_reminders(
            self,
            *,
            parent_ids: list[str] | None,
            generate_invoice_artifacts: bool,
        ) -> dict[str, object]:
            rows = await list_dues_followup()
            if parent_ids is not None:
                selected = set(parent_ids)
                rows = [row for row in rows if str(row["parent_id"]) in selected]
            generated = 0
            if generate_invoice_artifacts:
                for row in rows:
                    payment_cursor = payments_repo._find_many(  # type: ignore[attr-defined]
                        {
                            "status": {"$in": ["pending", "partially_paid"]},
                            "$or": [
                                {"parent_id": row["parent_id"]},
                                {"parent_user_id": row["parent_id"]},
                            ],
                            "is_deleted": {"$ne": True},
                        },
                        sort=[("created_at", -1)],
                    )
                    async for payment in payment_cursor:
                        await generate_billing_invoice_artifact(
                            str(payment.get("payment_id") or payment.get("invoice_number")),
                            "invoice_pdf",
                        )
                        generated += 1
            return {
                "sent": 0,
                "blocked": True,
                "reason": f"Local/test safety block: {len(rows)} reminder(s) were not sent.",
                "selected_parent_ids": parent_ids or [str(row["parent_id"]) for row in rows],
                "generated_invoice_artifacts": generated,
            }

    send_dues_reminders = SendDuesReminders(sender=_DuesReminderSender())

    async def _legacy_send_dues_reminders():
        rows = await list_dues_followup()
        return {
            "sent": 0,
            "blocked": True,
            "reason": f"Local/test safety block: {len(rows)} reminder(s) were not sent.",
        }

    async def export_report_csv(report_name: str):
        out = io.StringIO()
        writer = csv.writer(out)
        if report_name == "pending-payments":
            writer.writerow(
                ["payment_id", "parent_id", "student_id", "period", "amount_cents", "status"]
            )
            for row in await list_payments_recent():
                if row["status"] == "pending":
                    writer.writerow(
                        [
                            row["payment_id"],
                            row["parent_id"],
                            row.get("student_id"),
                            row.get("period"),
                            row["final_amount_cents"],
                            row["status"],
                        ]
                    )
        elif report_name == "revenue":
            writer.writerow(["month", "revenue_cents"])
            by_month: dict[str, int] = {}
            for row in await list_payments_recent():
                if row["status"] not in {"succeeded", "partially_refunded", "refunded"}:
                    continue
                created_at = row["created_at"]
                month = created_at.strftime("%Y-%m") if hasattr(created_at, "strftime") else ""
                by_month[month] = (
                    by_month.get(month, 0)
                    + int(row["final_amount_cents"])
                    - int(row["refunded_cents"])
                )
            for month, cents in sorted(by_month.items()):
                writer.writerow([month, cents])
        elif report_name == "attendance":
            writer.writerow(["attendance_id", "session_id", "student_id", "status", "marked_at"])
            cursor = (
                db["attendance"]
                .find({"academy_id": academy_id})
                .sort([("marked_at", -1)])
                .limit(1000)
            )
            async for row in cursor:
                writer.writerow(
                    [
                        row.get("attendance_id") or row.get("_id"),
                        row.get("session_id"),
                        row.get("student_id"),
                        row.get("status"),
                        row.get("marked_at"),
                    ]
                )
        else:
            writer.writerow(["error"])
            writer.writerow([f"unknown report {report_name}"])
        return out.getvalue()

    admin = AdminUseCases(
        list_admin_users=list_admin_users,
        list_admin_students=list_admin_students,
        create_session=create_session,
        edit_session=edit_session,
        cancel_session=cancel_session,
        edit_roster_add=edit_roster_add,
        cancel_enrollment=cancel_enrollment,
        transfer_enrollment=transfer_enrollment,
        pause_enrollment=pause_enrollment,
        resume_enrollment=resume_enrollment,
        withdraw_enrollment=withdraw_enrollment,
        join_waitlist=join_waitlist,
        promote_from_waitlist=promote,
        skip_from_waitlist=skip,
        remove_from_waitlist=remove,
        list_admin_pause_requests=list_admin_pause_requests,
        approve_pause_request=approve_pause_request,
        decline_pause_request=decline_pause_request,
        issue_refund=issue_refund,
        quote_enrollment=quote_enrollment,
        preview_withdrawal_credit=preview_withdrawal_credit,
        approve_withdrawal_credit=approve_withdrawal_credit,
        list_payments_recent=list_payments_recent,
        list_billing_invoices=billing_ledger_repo.list_invoices_for_academy,
        get_billing_invoice_detail=get_billing_invoice_detail,
        generate_billing_invoice_artifact=generate_billing_invoice_artifact,
        generate_monthly_payments=generate_monthly_payments,
        mark_payment_paid=mark_payment_paid,
        apply_payment_discount=apply_payment_discount,
        undo_payment_paid=undo_payment_paid,
        record_expense=record_expense,
        edit_expense=edit_expense,
        delete_expense=delete_expense,
        expenses=expenses_repo,
        payouts=payouts_repo,
        revenue_query=revenue_query,
        list_admin_sessions=list_admin_sessions,
        list_session_occurrences=list_session_occurrences,
        update_session_occurrence_coach=update_session_occurrence_coach,
        list_admin_enrollments_for_session=list_admin_enrollments_for_session,
        list_waitlist_for_session=list_waitlist_for_session,
        list_audit_logs=list_audit_logs,
        list_dues_followup=list_dues_followup,
        send_dues_reminders=send_dues_reminders,
        export_report_csv=export_report_csv,
        get_reports_kpis=_make_reports_kpis(db),
        list_enrollment_events=_make_list_enrollment_events(db),
        comms=comms,
        list_admin_waivers=list_admin_waivers,
        manage_admin_waiver_templates=manage_admin_waiver_templates,
        get_academy_use_case=get_academy_use_case,
        update_academy_use_case=update_academy_use_case,
        get_academy_fees_use_case=get_academy_fees_use_case,
        update_academy_fees_use_case=update_academy_fees_use_case,
        get_academy_notifications_use_case=get_academy_notifications_use_case,
        update_academy_notifications_use_case=update_academy_notifications_use_case,
        get_academy_gateway_use_case=get_academy_gateway_use_case,
        change_user_role=change_user_role,
        get_admin_user=get_admin_user,
        update_admin_user=update_admin_user,
        get_admin_student=get_admin_student,
        update_admin_student=update_admin_student,
    )
    admin.get_reports_dashboard = _make_reports_dashboard(db)  # type: ignore[attr-defined]
    return admin


class _EnrollmentLifecycleEventSink:
    def __init__(self, enrollment_events: MongoEnrollmentEventRepository) -> None:
        self._enrollment_events = enrollment_events

    async def record_withdrawal(
        self,
        *,
        academy_id: str,
        enrollment_id: str,
        session_id: str,
        student_id: str,
        actor_id: str,
        reason: str,
        effective_at: datetime,
        occurred_at: datetime,
        billing_policy: str,
        billing_result: str,
        credit_id: str | None,
    ) -> None:
        await self._enrollment_events.record(
            EnrollmentLifecycleEvent(
                event_id=str(new_ulid()),
                academy_id=academy_id,
                event_type="withdrawn",
                enrollment_id=enrollment_id,
                session_id=session_id,
                student_id=student_id,
                actor_id=actor_id,
                reason=reason,
                effective_at=effective_at,
                occurred_at=occurred_at,
                billing_policy=billing_policy,
                billing_result=billing_result,
                credit_id=credit_id,
            )
        )


def _start_date_to_datetime(value: str | None) -> datetime:
    if not value:
        return datetime.now(UTC)
    local = datetime.combine(
        datetime.fromisoformat(value).date(),
        time.min,
        tzinfo=ZoneInfo("America/Chicago"),
    )
    return local.astimezone(UTC)
