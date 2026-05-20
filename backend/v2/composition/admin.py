"""Compose Admin BFF (Wave 3)."""

from __future__ import annotations

from typing import Any

from datetime import date, datetime, time, timezone
import csv
import io

from bson import ObjectId as BsonObjectId

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.v2.contexts.billing.application.ports import StripeGateway
from backend.v2.contexts.billing.application.use_cases.admin_payment_ops import (
    ApplyPaymentDiscount,
    GenerateMonthlyPayments,
    MarkPaymentPaid,
    UndoPaymentPaid,
)
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
    TransferEnrollment,
)
from backend.v2.contexts.enrollment.application.use_cases.pause_requests import (
    ApprovePauseRequest,
    DeclinePauseRequest,
    ListAdminPauseRequests,
)
from backend.v2.contexts.enrollment.application.use_cases.admin_directory import (
    ListAdminStudents,
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
from backend.v2.contexts.enrollment.infrastructure.mongo_pause_request_repo import (
    MongoPauseRequestRepository,
)
from backend.v2.contexts.identity.application.use_cases.admin_directory import (
    ListAdminUsers,
)
from backend.v2.contexts.identity.infrastructure.mongo_user_repo import MongoUserRepository
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
    users_r = MongoUserRepository(db, default_academy_id=academy_id)
    sessions_w = MongoSessionWriter(db)
    sessions_r = MongoSessionRepository(db)
    enrollments_w = MongoEnrollmentWriter(db)
    enrollments_r = MongoEnrollmentRepository(db)
    students_w = MongoStudentWriter(db)
    students_r = MongoStudentRepository(db)
    waitlist = MongoWaitlistRepository(db)
    pause_requests = MongoPauseRequestRepository(db)

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
    transfer_enrollment = TransferEnrollment(enrollments=enrollments_w, sessions=sessions_w)
    pause_enrollment = PauseEnrollment(enrollments=enrollments_w)
    resume_enrollment = ResumeEnrollment(enrollments=enrollments_w)
    join_waitlist = JoinWaitlist(waitlist=waitlist, academy_id=academy_id)
    promote = PromoteFromWaitlist(waitlist=waitlist, outbox=outbox, academy_id=academy_id)
    skip = SkipFromWaitlist(waitlist=waitlist)
    remove = RemoveFromWaitlist(waitlist=waitlist)
    list_admin_pause_requests = ListAdminPauseRequests(pause_requests=pause_requests)
    approve_pause_request = ApprovePauseRequest(pause_requests=pause_requests)
    decline_pause_request = DeclinePauseRequest(pause_requests=pause_requests)

    # Billing
    payments_repo = MongoPaymentRepository(db)
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

    # Finance (# FINANCE)
    expenses_repo = MongoExpenseRepository(db)
    payouts_repo = MongoPayoutRepository(db)
    record_expense = RecordExpense(expenses=expenses_repo, academy_id=academy_id)
    revenue_query = AcademyRevenueQuery(payments=payments_repo)

    # Comms
    messages_repo = MongoMessageRepository(db)
    comms = CommsService(messages=messages_repo, academy_id=academy_id)
    list_admin_users = ListAdminUsers(users_r)
    list_admin_students = ListAdminStudents(students_r)

    # Closures for the BFF deps that need composed reads.
    # Day-of-week abbreviations used by the legacy seed schema.
    _DOW_MAP = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}

    async def list_admin_sessions(on_date: date | None):
        if on_date is None:
            on_date = datetime.now(timezone.utc).date()
        start = datetime.combine(on_date, time.min, tzinfo=timezone.utc)
        end = datetime.combine(on_date, time.max, tzinfo=timezone.utc)

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
            doc["start_at"] = datetime.combine(on_date, time(sh, sm), tzinfo=timezone.utc)
            doc["end_at"] = datetime.combine(on_date, time(eh, em), tzinfo=timezone.utc)
            # Normalise to v2 field names so _build_row works uniformly
            if "session_id" not in doc:
                doc["session_id"] = str(doc["_id"])
            if "title" not in doc:
                doc["title"] = str(doc.get("name") or "Session")
            if "capacity" not in doc:
                doc["capacity"] = doc.get("max_students", 15)
            all_docs.append(doc)

        rows: list[dict[str, Any]] = []
        for doc in all_docs:
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
                    "status": "scheduled" if str(doc.get("status") or "scheduled") == "active" else str(doc.get("status") or "scheduled"),
                    "coach_id": str(doc.get("coach_id") or ""),
                    "enrolled_count": enrolled_count,
                    "waitlist_count": waitlist_count,
                }
            )
        return rows

    async def list_admin_enrollments_for_session(session_id: str):
        cursor = enrollments_r._find_many(  # type: ignore[attr-defined]
            {"session_id": session_id, "status": {"$in": ["active", "paused"]}},
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

    async def list_audit_logs():
        cursor = db["audit_logs"].find({"academy_id": academy_id}).sort([("created_at", -1)]).limit(200)
        rows: list[dict[str, Any]] = []
        async for doc in cursor:
            rows.append(
                {
                    "audit_id": str(doc.get("audit_id") or doc.get("_id")),
                    "actor_id": doc.get("actor_id") or doc.get("user_id"),
                    "action": str(doc.get("action") or doc.get("event") or "unknown"),
                    "entity_type": doc.get("entity_type") or doc.get("resource_type"),
                    "entity_id": doc.get("entity_id") or doc.get("resource_id"),
                    "created_at": doc.get("created_at") or datetime.now(timezone.utc),
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

    async def send_dues_reminders():
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
            writer.writerow(["payment_id", "parent_id", "student_id", "period", "amount_cents", "status"])
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
                by_month[month] = by_month.get(month, 0) + int(row["final_amount_cents"]) - int(row["refunded_cents"])
            for month, cents in sorted(by_month.items()):
                writer.writerow([month, cents])
        elif report_name == "attendance":
            writer.writerow(["attendance_id", "session_id", "student_id", "status", "marked_at"])
            cursor = db["attendance"].find({"academy_id": academy_id}).sort([("marked_at", -1)]).limit(1000)
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

    return AdminUseCases(
        list_admin_users=list_admin_users,
        list_admin_students=list_admin_students,
        create_session=create_session,
        cancel_session=cancel_session,
        edit_roster_add=edit_roster_add,
        cancel_enrollment=cancel_enrollment,
        transfer_enrollment=transfer_enrollment,
        pause_enrollment=pause_enrollment,
        resume_enrollment=resume_enrollment,
        join_waitlist=join_waitlist,
        promote_from_waitlist=promote,
        skip_from_waitlist=skip,
        remove_from_waitlist=remove,
        list_admin_pause_requests=list_admin_pause_requests,
        approve_pause_request=approve_pause_request,
        decline_pause_request=decline_pause_request,
        issue_refund=issue_refund,
        list_payments_recent=list_payments_recent,
        generate_monthly_payments=generate_monthly_payments,
        mark_payment_paid=mark_payment_paid,
        apply_payment_discount=apply_payment_discount,
        undo_payment_paid=undo_payment_paid,
        record_expense=record_expense,
        expenses=expenses_repo,
        payouts=payouts_repo,
        revenue_query=revenue_query,
        list_admin_sessions=list_admin_sessions,
        list_admin_enrollments_for_session=list_admin_enrollments_for_session,
        list_waitlist_for_session=list_waitlist_for_session,
        list_audit_logs=list_audit_logs,
        list_dues_followup=list_dues_followup,
        send_dues_reminders=send_dues_reminders,
        export_report_csv=export_report_csv,
        comms=comms,
    )
