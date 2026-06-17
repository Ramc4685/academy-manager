"""Compose Admin BFF (Wave 3)."""

from __future__ import annotations

import csv
import html
import io
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from bson import ObjectId as BsonObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.v2.composition.admin_registration_review import (
    AdminRegistrationReview,
)
from backend.v2.composition.digests import (
    compose_get_digest_delivery_log,
    compose_send_coach_digest_test,
)
from backend.v2.composition.pathway import (
    compose_curriculum,
    compose_student_progress,
)
from backend.v2.contexts.billing.application.ports import StripeGateway
from backend.v2.contexts.billing.application.use_cases.add_invoice_line import (
    AddInvoiceLine,
    AddInvoiceLineCommand,
)
from backend.v2.contexts.billing.application.use_cases.admin_payment_ops import (
    ApplyPaymentDiscount,
    GenerateMonthlyPayments,
    MarkPaymentPaid,
    SendDuesReminders,
    UndoPaymentPaid,
)
from backend.v2.contexts.billing.application.use_cases.charge_invoice_via_autopay import (
    ChargeInvoiceViaAutopay,
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
from backend.v2.contexts.billing.application.use_cases.record_manual_payment import (
    RecordManualPayment,
    RecordManualPaymentCommand,
)
from backend.v2.contexts.billing.application.use_cases.remove_invoice_line import (
    RemoveInvoiceLine,
    RemoveInvoiceLineCommand,
)
from backend.v2.contexts.billing.application.use_cases.send_invoice import SendInvoice
from backend.v2.contexts.billing.application.use_cases.session_type_ops import (
    CreateSessionType,
    ListSessionTypes,
    ListStudentBillingEnrollments,
    MoveStudentSessionType,
    OverrideStudentPrice,
    SoftDeleteSessionType,
    UpdateSessionType,
)
from backend.v2.contexts.billing.application.use_cases.withdrawal_credit import (
    ApproveWithdrawalCredit,
    PreviewWithdrawalCredit,
)
from backend.v2.contexts.billing.domain.ledger import LedgerInvoice, void_invoice
from backend.v2.contexts.billing.domain.product import Product
from backend.v2.contexts.billing.infrastructure.mongo_billing_ledger_repo import (
    MongoBillingLedgerRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_credit_ledger_repo import (
    MongoCreditLedgerRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_parent_billing_customer_repo import (
    MongoParentBillingCustomerRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_payment_repo import (
    MongoPaymentRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_product_repo import (
    MongoProductRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_session_type_repo import (
    MongoSessionTypeRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_student_billing_enrollment_repo import (
    MongoStudentBillingEnrollmentRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_subscription_repo import (
    MongoSubscriptionRepository,
)
from backend.v2.contexts.coaching.application.use_cases.compute_payout import (
    ComputeCoachPayout,
)
from backend.v2.contexts.coaching.application.use_cases.generate_daily_teaching_plan import (
    GenerateDailyTeachingPlan,
)
from backend.v2.contexts.coaching.application.use_cases.manage_coach_rates import (
    ListCoachPayRates,
    SetCoachPayRate,
)
from backend.v2.contexts.coaching.application.use_cases.mark_coach_attendance import (
    MarkCoachAttendance,
)
from backend.v2.contexts.coaching.domain.payout import (
    CoachAttendanceForPayout,
    CoachRate,
    PayableOccurrence,
)
from backend.v2.contexts.coaching.infrastructure.mongo_attendance_repo import (
    MongoCoachAttendanceRepository,
)
from backend.v2.contexts.coaching.infrastructure.mongo_coach_rate_repo import (
    MongoCoachRateRepository,
)
from backend.v2.contexts.communications.application.ports import (
    EmailSendPort,
    ResolvedRecipient,
)
from backend.v2.contexts.communications.application.use_cases.send_campaign import (
    SendCampaign,
)
from backend.v2.contexts.communications.infrastructure.mongo_audience_resolver import (
    MongoAudienceResolver,
)
from backend.v2.contexts.communications.infrastructure.mongo_campaign_repo import (
    MongoCampaignRepository,
)
from backend.v2.contexts.communications.infrastructure.mongo_delivery_repo import (
    MongoDeliveryRepository,
)
from backend.v2.contexts.communications.infrastructure.resend_send_port import (
    ResendEmailSendPort,
)
from backend.v2.contexts.communications.infrastructure.stub_send_port import (
    StubEmailSendPort,
)
from backend.v2.contexts.curriculum.infrastructure.mongo_criterion_repo import (
    MongoCriterionRepository,
)
from backend.v2.contexts.curriculum.infrastructure.mongo_lesson_card_repo import (
    MongoLessonCardRepository,
)
from backend.v2.contexts.curriculum.infrastructure.mongo_video_ref_repo import (
    MongoCurriculumVideoRefRepository,
)
from backend.v2.contexts.enrollment.application.use_cases.admin_directory import (
    ChangeAdminStudentParent,
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
from backend.v2.contexts.enrollment.application.use_cases.get_session_roster import (
    GetSessionRoster,
)
from backend.v2.contexts.enrollment.application.use_cases.list_coach_occurrences_for_date import (
    ListCoachOccurrencesForDate,
)
from backend.v2.contexts.enrollment.application.use_cases.pause_requests import (
    ApprovePauseRequest,
    DeclinePauseRequest,
    ListAdminPauseRequests,
)
from backend.v2.contexts.enrollment.application.use_cases.process_scheduled_resume_actions import (
    ProcessScheduledResumeActions,
)
from backend.v2.contexts.enrollment.application.use_cases.promote_from_waitlist import (
    PromoteFromWaitlist,
)
from backend.v2.contexts.enrollment.domain.events import (
    EnrollmentLifecycleEvent,
    StudentSessionTypeChanged,
    StudentSessionTypeChangedPayload,
)
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
from backend.v2.contexts.enrollment.infrastructure.mongo_scheduled_action_repo import (
    MongoScheduledEnrollmentActionRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_session_repo import (
    MongoSessionRepository,
    session_start_sort_key,
    synthesize_recurring_session_docs,
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
from backend.v2.contexts.finance.application.use_cases.approve_payout_period import (
    ApprovePayoutPeriod,
    MarkPayoutPaid,
)
from backend.v2.contexts.finance.application.use_cases.attendance_trends import (
    GetAttendanceTrends,
)
from backend.v2.contexts.finance.application.use_cases.bulk_payroll import (
    BulkGeneratePayroll,
    BulkRecomputePayroll,
)
from backend.v2.contexts.finance.application.use_cases.coach_utilization import (
    GetCoachUtilization,
)
from backend.v2.contexts.finance.application.use_cases.enrollment_funnel import (
    GetEnrollmentFunnel,
)
from backend.v2.contexts.finance.application.use_cases.generate_payout_period import (
    GeneratePayoutPeriod,
)
from backend.v2.contexts.finance.application.use_cases.list_monthly_payroll import (
    ListMonthlyPayroll,
)
from backend.v2.contexts.finance.application.use_cases.manage_payout_period import (
    ListPayoutAuditEntries,
    OverridePayoutLine,
    RecomputePayoutPeriod,
    ReopenPayoutPeriod,
)
from backend.v2.contexts.finance.domain.payout_period import PersistedPayoutLine
from backend.v2.contexts.finance.infrastructure.mongo_application_funnel_reader import (
    MongoApplicationFunnelReader,
)
from backend.v2.contexts.finance.infrastructure.mongo_attendance_snapshot_reader import (
    MongoAttendanceSnapshotReader,
)
from backend.v2.contexts.finance.infrastructure.mongo_coach_payout_snapshot_reader import (
    MongoCoachPayoutSnapshotReader,
)
from backend.v2.contexts.finance.infrastructure.mongo_payout_audit_log import (
    MongoPayoutAuditLogRepository,
)
from backend.v2.contexts.finance.infrastructure.mongo_payout_period_repo import (
    MongoPayoutPeriodRepository,
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
    CreateAdminUser,
    GetAdminUser,
    ListAdminUsers,
    UpdateAdminUser,
)
from backend.v2.contexts.identity.application.use_cases.stripe_connect import (
    CompleteStripeConnectUseCase,
    DisconnectStripeUseCase,
    StartStripeConnectUseCase,
)
from backend.v2.contexts.identity.infrastructure.mongo_academy_repo import MongoAcademyRepository
from backend.v2.contexts.identity.infrastructure.mongo_membership_repo import (
    MongoMembershipRepository,
)
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
from backend.v2.contexts.onboarding.infrastructure.mongo_application_repo import (
    MongoApplicationRepository,
)
from backend.v2.contexts.onboarding.infrastructure.mongo_waiver_template_repo import (
    MongoWaiverTemplateRepository,
)
from backend.v2.contexts.student_progress.application.use_cases.get_coach_engagement_stats import (
    GetCoachEngagementStats,
)
from backend.v2.contexts.student_progress.application.use_cases.get_pathway_placement import (
    StudentPathwayPlacementRequest,
)
from backend.v2.contexts.student_progress.infrastructure.mongo_skill_progress_repo import (
    MongoStudentSkillProgressRepository,
)
from backend.v2.interfaces.admin.deps import AdminUseCases
from backend.v2.shared.comms import CommsService, MongoMessageRepository
from backend.v2.shared.config import get_settings
from backend.v2.shared.events import Outbox
from backend.v2.shared.idempotency import IdempotencyStore
from backend.v2.shared.ids import new_ulid


class _InvoiceEmailAdapter:
    def __init__(
        self,
        *,
        memberships: MongoMembershipRepository,
        users: MongoUserRepository,
        sender: EmailSendPort,
    ) -> None:
        self._memberships = memberships
        self._users = users
        self._sender = sender

    async def send_invoice_email(
        self,
        *,
        parent_id: str,
        invoice_id: str,
        period: str,
        total_cents: int,
        balance_due_cents: int,
        currency: str,
        checkout_url: str | None,
    ) -> None:
        from backend.v2.shared.tenancy import current_academy_id

        academy_id = current_academy_id()
        membership = await self._memberships.get_membership(academy_id, parent_id)
        if membership is None or not membership.is_active() or "parent" not in membership.roles:
            raise ValueError("invoice parent has no active membership in request academy")

        user = await self._users.get_by_id(parent_id)
        email = str(user.email if user else "").strip()
        if not email:
            raise ValueError("invoice parent email not found")

        display_name = str(user.display_name if user else "")
        amount = f"{currency.upper()} {balance_due_cents / 100:.2f}"
        total = f"{currency.upper()} {total_cents / 100:.2f}"
        safe_invoice = html.escape(invoice_id)
        safe_period = html.escape(period)
        safe_amount = html.escape(amount)
        safe_total = html.escape(total)
        pay_line = (
            f'<p><a href="{html.escape(checkout_url, quote=True)}">Pay invoice</a></p>'
            if checkout_url
            else "<p>Please contact the academy to arrange payment.</p>"
        )
        body = (
            f"<p>Your invoice <strong>{safe_invoice}</strong> for {safe_period} is ready.</p>"
            f"<p>Balance due: <strong>{safe_amount}</strong> "
            f"(invoice total {safe_total}).</p>"
            f"{pay_line}"
        )
        outcome = await self._sender.send(
            recipient=ResolvedRecipient(
                user_id=parent_id,
                email=email,
                display_name=display_name or None,
            ),
            subject=f"Invoice {invoice_id} for {period}",
            body=body,
        )
        if not outcome.ok:
            raise ValueError(outcome.failed_reason or "invoice email delivery failed")


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


def _coerce_report_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _payment_due_date(payment: dict[str, Any], fallback: date) -> date:
    for key in ("due_date", "due_at", "created_at"):
        parsed = _coerce_report_date(payment.get(key))
        if parsed is not None:
            return parsed
    return fallback


def _aging_label(days_late: int) -> str:
    if days_late <= 0:
        return "Current"
    if days_late <= 30:
        return "1-30"
    if days_late <= 60:
        return "31-60"
    return "60+"


def _make_reports_dashboard(db: AsyncIOMotorDatabase[Any]) -> object:
    """Returns an async callable for the owner finance/operations dashboard."""
    from backend.v2.shared.tenancy import current_academy_id

    async def get_reports_dashboard(period: str) -> dict[str, Any]:
        academy_id = current_academy_id()
        start, end = _month_bounds(period)

        cash_collected_cents = 0
        outstanding_dues_cents = 0
        failed_payment_count = 0
        partial_payment_count = 0
        collection_family_ids: set[str] = set()
        aging_totals: dict[str, dict[str, Any]] = {
            label: {"amount_cents": 0, "family_ids": set()}
            for label in ("Current", "1-30", "31-60", "60+")
        }
        payments_cursor = db["payments"].find(
            {
                "academy_id": academy_id,
                "period": period,
                "is_deleted": {"$ne": True},
            }
        )
        async for payment in payments_cursor:
            status = str(payment.get("status") or "")
            if status == "failed":
                failed_payment_count += 1
            elif status == "partially_paid":
                partial_payment_count += 1
            cash_collected_cents += _payment_collected_cents(payment)
            outstanding = _payment_outstanding_cents(payment)
            outstanding_dues_cents += outstanding
            if outstanding:
                family_id = str(
                    payment.get("parent_id")
                    or payment.get("family_id")
                    or payment.get("student_id")
                    or payment.get("payment_id")
                    or ""
                )
                if family_id:
                    collection_family_ids.add(family_id)
                due_date = _payment_due_date(payment, end.date())
                days_late = max((end.date() - due_date).days, 0)
                label = _aging_label(days_late)
                bucket = aging_totals[label]
                bucket["amount_cents"] = int(bucket["amount_cents"]) + outstanding
                family_ids = bucket["family_ids"]
                if isinstance(family_ids, set) and family_id:
                    family_ids.add(family_id)

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

        waitlist_count = 0
        if session_ids:
            waitlist_count = await db["waitlist"].count_documents(
                {
                    "academy_id": academy_id,
                    "session_id": {"$in": session_ids},
                    "status": {"$in": ["waiting", "active"]},
                    "is_deleted": {"$ne": True},
                }
            )

        expenses_total_cents = 0
        expense_categories: dict[str, dict[str, int]] = {}
        expenses_cursor = db["expenses"].find(
            {
                "academy_id": academy_id,
                "incurred_on": {"$gte": start, "$lt": end},
                "$or": [{"deleted_at": None}, {"deleted_at": {"$exists": False}}],
            }
        )
        async for expense in expenses_cursor:
            category = str(expense.get("category") or "other")
            amount = int(expense.get("amount_cents") or 0)
            expenses_total_cents += amount
            category_row = expense_categories.setdefault(
                category,
                {"amount_cents": 0, "count": 0},
            )
            category_row["amount_cents"] += amount
            category_row["count"] += 1
        expense_rows = [
            {"category": category, **values}
            for category, values in sorted(expense_categories.items())
        ]
        rent_cents = int(expense_categories.get("rent", {}).get("amount_cents", 0))
        misc_expenses_cents = expenses_total_cents - rent_cents

        estimated_payroll_cents = 0
        approved_payroll_cents = 0
        paid_payroll_cents = 0
        payout_period_rows = 0
        payout_cursor = db["payout_periods"].find(
            {
                "academy_id": academy_id,
                "period_start": {"$gte": start, "$lt": end},
            }
        )
        async for payout_period in payout_cursor:
            payout_period_rows += 1
            total = int(payout_period.get("total_minor") or 0)
            estimated_payroll_cents += total
            status = str(payout_period.get("status") or "draft")
            if status in {"approved", "paid"}:
                approved_payroll_cents += total
            if status == "paid":
                paid_payroll_cents += int(payout_period.get("paid_amount_minor") or total)
        unpaid_payroll_cents = max(approved_payroll_cents - paid_payroll_cents, 0)

        payroll_for_pnl = (
            approved_payroll_cents
            if approved_payroll_cents > 0
            else estimated_payroll_cents
            if estimated_payroll_cents > 0
            else None
        )
        net_profit_cents = (
            cash_collected_cents - expenses_total_cents - payroll_for_pnl
            if payroll_for_pnl is not None
            else None
        )
        profit_margin = (
            round(net_profit_cents / cash_collected_cents, 4)
            if net_profit_cents is not None and cash_collected_cents > 0
            else None
        )

        empty_states: list[str] = []
        if cash_collected_cents == 0:
            empty_states.append("No collected payment rows found for this month.")
        if recorded_count == 0:
            empty_states.append("No attendance marks found for this month.")
        if not session_ids:
            empty_states.append("No sessions found for this month.")
        if expenses_total_cents == 0:
            empty_states.append("No expenses found for this month.")
        if payout_period_rows == 0:
            empty_states.append("No payout periods generated for this month.")

        aging_buckets = [
            {
                "label": label,
                "amount_cents": int(aging_totals[label]["amount_cents"]),
                "family_count": len(aging_totals[label]["family_ids"]),
            }
            for label in ("Current", "1-30", "31-60", "60+")
        ]

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
                "waitlist_count": waitlist_count,
                "empty": not session_ids,
            },
            "expenses": {
                "total_cents": expenses_total_cents,
                "by_category": expense_rows,
            },
            "collections_risk": {
                "overdue_family_count": len(collection_family_ids),
                "overdue_cents": outstanding_dues_cents,
                "failed_payment_count": failed_payment_count,
                "partial_payment_count": partial_payment_count,
                "aging_buckets": aging_buckets,
            },
            "profit_and_loss": {
                "revenue_cents": cash_collected_cents,
                "coach_payroll_cents": payroll_for_pnl,
                "rent_cents": rent_cents,
                "misc_expenses_cents": misc_expenses_cents,
                "net_profit_cents": net_profit_cents,
                "profit_margin": profit_margin,
            },
            "payroll": {
                "estimated_cents": estimated_payroll_cents if payout_period_rows else None,
                "approved_cents": approved_payroll_cents if payout_period_rows else None,
                "paid_cents": paid_payroll_cents if payout_period_rows else None,
                "unpaid_cents": unpaid_payroll_cents if payout_period_rows else None,
                "blocked_by": None
                if payout_period_rows
                else "No generated payout periods for this month.",
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


class _MongoPayableOccurrenceQuery:
    def __init__(self, db: AsyncIOMotorDatabase[Any]) -> None:
        self._db = db

    async def list_in_period(
        self,
        academy_id: str,
        period_start: datetime,
        period_end: datetime,
    ) -> list[PayableOccurrence]:
        cursor = self._db["session_occurrences"].find(
            {
                "academy_id": academy_id,
                "start_at": {"$gte": period_start, "$lt": period_end},
            },
            sort=[("start_at", 1)],
        )
        docs = [doc async for doc in cursor]
        occurrence_ids = [str(doc["occurrence_id"]) for doc in docs]
        revenue_by_session = await self._expected_revenue_by_session(academy_id, docs)
        attendance_by_occurrence: dict[str, list[CoachAttendanceForPayout]] = {
            occurrence_id: [] for occurrence_id in occurrence_ids
        }
        if occurrence_ids:
            attendance_cursor = self._db["coach_attendance"].find(
                {
                    "academy_id": academy_id,
                    "occurrence_id": {"$in": occurrence_ids},
                },
                sort=[("marked_at", 1)],
            )
            async for row in attendance_cursor:
                occurrence_id = str(row["occurrence_id"])
                attendance_by_occurrence.setdefault(occurrence_id, []).append(
                    CoachAttendanceForPayout(
                        coach_id=str(row["coach_id"]),
                        status=row.get("status", "absent"),
                        role=row.get("role", "lead"),
                        rate_override_minor=(
                            None
                            if row.get("rate_override_minor") is None
                            else int(row["rate_override_minor"])
                        ),
                    )
                )

        return [
            PayableOccurrence(
                occurrence_id=str(doc["occurrence_id"]),
                academy_id=str(doc["academy_id"]),
                start_at=doc["start_at"],
                end_at=doc["end_at"],
                status=_effective_occurrence_status(doc),
                scheduled_coach_id=str(doc["scheduled_coach_id"]),
                actual_coach_id=_optional_str(doc.get("actual_coach_id")),
                substitute_coach_id=_optional_str(doc.get("substitute_coach_id")),
                is_payable=bool(doc.get("is_payable", True)),
                coach_attendance=attendance_by_occurrence.get(str(doc["occurrence_id"]), []),
                expected_revenue_minor=revenue_by_session.get(_occurrence_session_id(doc)),
            )
            for doc in docs
        ]

    async def _expected_revenue_by_session(
        self,
        academy_id: str,
        occurrence_docs: list[dict[str, Any]],
    ) -> dict[str, int]:
        """Expected revenue per session = session price x active enrollments.

        Used as the basis for ``percent_of_revenue`` coach rates. Sessions
        without a configured ``amount_cents`` are omitted, which surfaces
        downstream as ``unpaid_occurrence_ids`` instead of silently paying 0.
        """
        session_ids = sorted(
            {_occurrence_session_id(doc) for doc in occurrence_docs if _occurrence_session_id(doc)}
        )
        if not session_ids:
            return {}

        price_by_session: dict[str, int] = {}
        session_cursor = self._db["sessions"].find(
            {"academy_id": academy_id, "session_id": {"$in": session_ids}},
            {"session_id": 1, "amount_cents": 1},
        )
        async for row in session_cursor:
            amount = row.get("amount_cents")
            if amount is not None:
                price_by_session[str(row["session_id"])] = int(amount)

        if not price_by_session:
            return {}

        enrolled_by_session: dict[str, int] = dict.fromkeys(price_by_session, 0)
        enrollment_cursor = self._db["enrollments"].find(
            {
                "academy_id": academy_id,
                "session_id": {"$in": list(price_by_session)},
                "status": "active",
                "is_deleted": {"$ne": True},
            },
            {"session_id": 1},
        )
        async for row in enrollment_cursor:
            session_id = str(row["session_id"])
            enrolled_by_session[session_id] = enrolled_by_session.get(session_id, 0) + 1

        return {
            session_id: price_by_session[session_id] * enrolled_by_session.get(session_id, 0)
            for session_id in price_by_session
        }


class _MongoCoachRateRepository:
    def __init__(self, db: AsyncIOMotorDatabase[Any]) -> None:
        self._db = db

    async def find_for_coach_at(self, coach_id: str, at_time: datetime) -> CoachRate | None:
        from backend.v2.shared.tenancy import current_academy_id

        doc = await self._db["coach_rates"].find_one(
            {
                "academy_id": current_academy_id(),
                "coach_id": coach_id,
                "effective_from": {"$lte": at_time},
                "$or": [
                    {"effective_until": {"$exists": False}},
                    {"effective_until": None},
                    {"effective_until": {"$gt": at_time}},
                ],
            },
            sort=[("effective_from", -1)],
        )
        if doc is None:
            return None
        return CoachRate(
            rate_id=str(doc.get("rate_id") or doc.get("_id")),
            academy_id=str(doc["academy_id"]),
            coach_id=str(doc["coach_id"]),
            billing_unit=doc.get("billing_unit", "per_session"),
            amount_minor=int(doc.get("amount_minor", doc.get("amount_cents", 0))),
            percent_bps=(None if doc.get("percent_bps") is None else int(doc["percent_bps"])),
            currency=str(doc.get("currency", "USD")).upper(),
            effective_from=doc["effective_from"],
            effective_until=doc.get("effective_until"),
            status=doc.get("status", "active"),
        )


class _FinancePayoutCalculator:
    def __init__(self, compute: ComputeCoachPayout) -> None:
        self._compute = compute

    async def calculate(
        self,
        *,
        coach_id: str,
        academy_id: str,
        period_start: datetime,
        period_end: datetime,
    ) -> object:
        statement = await self._compute.execute(
            coach_id=coach_id,
            academy_id=academy_id,
            period_start=period_start,
            period_end=period_end,
        )
        return statement.model_copy(
            update={
                "lines": [
                    PersistedPayoutLine(
                        occurrence_id=line.occurrence_id,
                        coach_id=line.coach_id,
                        basis=line.basis,
                        minutes=line.minutes,
                        amount_minor=line.amount_minor,
                        currency=line.currency,
                        rate_id=line.rate_id,
                        percent_bps=line.percent_bps,
                        expected_revenue_minor=line.expected_revenue_minor,
                    )
                    for line in statement.lines
                ]
            }
        )


class _MonthlyCoachOccurrenceReaderAdapter:
    """Groups session_occurrences by paying coach for a calendar month.

    Paying coach = actual_coach_id when set, else scheduled_coach_id.
    Clock-derived completion: end_at < now OR status == 'completed'.
    """

    def __init__(self, collection: Any) -> None:
        self._col = collection

    async def coaches_with_occurrences(
        self,
        *,
        academy_id: str,
        period_start: datetime,
        period_end: datetime,
    ) -> list[Any]:
        from dataclasses import dataclass

        @dataclass(frozen=True)
        class _Row:
            coach_id: str
            session_count: int

        now = datetime.now(tz=UTC)
        pipeline = [
            {
                "$match": {
                    "academy_id": academy_id,
                    "start_at": {"$gte": period_start, "$lt": period_end},
                    "is_payable": {"$ne": False},
                    "status": {"$ne": "cancelled"},
                    "$or": [{"status": "completed"}, {"end_at": {"$lt": now}}],
                }
            },
            {"$project": {"coach": {"$ifNull": ["$actual_coach_id", "$scheduled_coach_id"]}}},
            {"$group": {"_id": "$coach", "session_count": {"$sum": 1}}},
        ]
        return [
            _Row(coach_id=str(doc["_id"]), session_count=int(doc["session_count"]))
            async for doc in self._col.aggregate(pipeline)
        ]


def _optional_str(value: object | None) -> str | None:
    return None if value is None else str(value)


def _occurrence_session_id(doc: dict[str, Any]) -> str:
    """Session the occurrence belongs to — enrollments reference the
    template session, so prefer ``template_session_id`` when present."""
    return str(doc.get("template_session_id") or doc.get("session_id") or "")


def _effective_occurrence_status(doc: dict[str, Any]) -> str:
    """A scheduled occurrence whose end time has passed counts as completed.

    Nothing in the app flips ``session_occurrences.status`` to "completed",
    so payout eligibility derives completion from the clock instead.
    Cancelled occurrences stay cancelled.
    """
    status = str(doc.get("status", "scheduled"))
    if status != "scheduled":
        return status
    end_at = doc["end_at"]
    end_utc = end_at if end_at.tzinfo else end_at.replace(tzinfo=UTC)
    return "completed" if end_utc < datetime.now(UTC) else status


def compose_admin(
    db: AsyncIOMotorDatabase[Any],
    outbox: Outbox,
    idempotency_store: IdempotencyStore,
    stripe: StripeGateway,
) -> AdminUseCases:
    settings = get_settings()
    academy_id = settings.primary_academy_id or settings.default_academy_id

    # Enrollment repos
    users_r = MongoUserRepository(db, default_academy_id=academy_id)
    sessions_w = MongoSessionWriter(db)
    sessions_r = MongoSessionRepository(db)
    occurrences_r = MongoSessionOccurrenceRepository(db)
    coach_attendance_repo = MongoCoachAttendanceRepository(db)
    enrollments_w = MongoEnrollmentWriter(db)
    enrollments_r = MongoEnrollmentRepository(db)
    enrollment_events = MongoEnrollmentEventRepository(db)
    students_w = MongoStudentWriter(db)
    students_r = MongoStudentRepository(db)
    waitlist = MongoWaitlistRepository(db)
    pause_requests = MongoPauseRequestRepository(db)
    scheduled_actions = MongoScheduledEnrollmentActionRepository(db)
    subscriptions_repo = MongoSubscriptionRepository(db)
    parent_customers_repo = MongoParentBillingCustomerRepository(db)
    curriculum = compose_curriculum(db)
    student_progress = compose_student_progress(db, outbox)
    generate_daily_teaching_plan = GenerateDailyTeachingPlan(
        occurrences=ListCoachOccurrencesForDate(
            occurrences=occurrences_r,
            sessions=sessions_r,
        ),
        get_roster=GetSessionRoster(enrollments=enrollments_r, students=students_r),
        teaching_focus=student_progress.get_teaching_focus,
        lesson_cards=MongoLessonCardRepository(db),
        video_refs=MongoCurriculumVideoRefRepository(db),
        criteria=MongoCriterionRepository(db),
    )
    get_coach_engagement_stats = GetCoachEngagementStats(
        skill_progress=MongoStudentSkillProgressRepository(db)
    )

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
    approve_pause_request = ApprovePauseRequest(
        pause_requests=pause_requests,
        pause_enrollment=pause_enrollment,
        scheduled_actions=scheduled_actions,
        subscriptions=subscriptions_repo,
        stripe=stripe,
        academy_id=academy_id,
    )
    decline_pause_request = DeclinePauseRequest(pause_requests=pause_requests)
    process_scheduled_resume_actions = ProcessScheduledResumeActions(
        scheduled_actions=scheduled_actions,
        resume_enrollment=resume_enrollment,
        subscriptions=subscriptions_repo,
        stripe=stripe,
    )

    # Billing
    billing_ledger_repo = MongoBillingLedgerRepository(db)
    credits_repo = MongoCreditLedgerRepository(db)
    payments_repo = MongoPaymentRepository(
        db, credit_ledger=credits_repo, ledger_repo=billing_ledger_repo
    )
    session_type_repo = MongoSessionTypeRepository(db)
    student_billing_enrollment_repo = MongoStudentBillingEnrollmentRepository(db)
    create_session_type = CreateSessionType(
        session_types=session_type_repo,
        academy_id=academy_id,
    )
    list_session_types = ListSessionTypes(session_types=session_type_repo)
    update_session_type = UpdateSessionType(session_types=session_type_repo)
    soft_delete_session_type = SoftDeleteSessionType(session_types=session_type_repo)
    list_student_billing_enrollments = ListStudentBillingEnrollments(
        enrollments=student_billing_enrollment_repo
    )
    move_student_session_type = MoveStudentSessionType(
        enrollments=student_billing_enrollment_repo,
        session_types=session_type_repo,
        stripe=stripe,
        event_sink=_SessionTypeChangedEventSink(outbox),
    )
    override_student_price = OverrideStudentPrice(enrollments=student_billing_enrollment_repo)
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
    payout_periods_repo = MongoPayoutPeriodRepository(db)
    coach_payout_calculator = _FinancePayoutCalculator(
        ComputeCoachPayout(
            occurrences=_MongoPayableOccurrenceQuery(db),
            rates=_MongoCoachRateRepository(db),
        )
    )
    generate_payout_period = GeneratePayoutPeriod(
        calculator=coach_payout_calculator,
        repository=payout_periods_repo,
    )
    approve_payout_period = ApprovePayoutPeriod(repository=payout_periods_repo)
    mark_payout_paid = MarkPayoutPaid(repository=payout_periods_repo)
    payout_audit_log = MongoPayoutAuditLogRepository(db)
    recompute_payout_period = RecomputePayoutPeriod(
        calculator=coach_payout_calculator,
        repository=payout_periods_repo,
        audit=payout_audit_log,
    )
    reopen_payout_period = ReopenPayoutPeriod(
        repository=payout_periods_repo,
        audit=payout_audit_log,
    )
    override_payout_line = OverridePayoutLine(
        repository=payout_periods_repo,
        audit=payout_audit_log,
    )
    list_payout_audit_entries = ListPayoutAuditEntries(audit=payout_audit_log)

    async def _describe_payout_occurrences(
        occurrence_ids: list[str],
    ) -> dict[str, dict[str, Any]]:
        """BFF display data for payout lines: when, and which session.

        Returns ``{occurrence_id: {"occurred_at": datetime|None,
        "session_title": str|None}}`` for the ids that exist. Missing
        ids are simply absent from the result.
        """
        from backend.v2.shared.tenancy import current_academy_id

        if not occurrence_ids:
            return {}
        request_academy_id = current_academy_id()
        occ_cursor = db["session_occurrences"].find(
            {"academy_id": request_academy_id, "occurrence_id": {"$in": occurrence_ids}},
            {"occurrence_id": 1, "start_at": 1, "template_session_id": 1, "session_id": 1},
        )
        occ_docs = [doc async for doc in occ_cursor]
        session_ids = sorted(
            {_occurrence_session_id(doc) for doc in occ_docs if _occurrence_session_id(doc)}
        )
        titles: dict[str, str] = {}
        if session_ids:
            session_cursor = db["sessions"].find(
                {"academy_id": request_academy_id, "session_id": {"$in": session_ids}},
                {"session_id": 1, "title": 1, "name": 1},
            )
            async for row in session_cursor:
                titles[str(row["session_id"])] = str(row.get("title") or row.get("name") or "")
        return {
            str(doc["occurrence_id"]): {
                "occurred_at": doc.get("start_at"),
                "session_title": titles.get(_occurrence_session_id(doc)) or None,
            }
            for doc in occ_docs
        }

    coach_rates_repo = MongoCoachRateRepository(db)
    set_coach_pay_rate = SetCoachPayRate(rates=coach_rates_repo)
    list_coach_pay_rates = ListCoachPayRates(rates=coach_rates_repo)
    record_expense = RecordExpense(expenses=expenses_repo, academy_id=academy_id)
    edit_expense = EditExpense(expenses=expenses_repo)
    delete_expense = DeleteExpense(expenses=expenses_repo)
    revenue_query = AcademyRevenueQuery(payments=payments_repo)

    # Comms
    messages_repo = MongoMessageRepository(db)
    comms = CommsService(messages=messages_repo, academy_id=academy_id)

    _s = settings
    _from_addr = (
        f"noreply@{_s.frontend_url.replace('https://', '').replace('http://', '').split('/')[0]}"
        if _s.frontend_url
        else "noreply@academy.app"
    )
    if _s.email_delivery_enabled and _s.resend_api_key:
        _email_sender = ResendEmailSendPort(api_key=_s.resend_api_key, from_address=_from_addr)
    else:
        _email_sender = StubEmailSendPort()

    product_repo = MongoProductRepository(db)

    def _product_dict(product: Product) -> dict[str, Any]:
        return product.model_dump(mode="python")

    async def list_billing_products() -> list[dict[str, Any]]:
        return [_product_dict(p) for p in await product_repo.list_products(active_only=True)]

    async def create_billing_product(
        *,
        name: str,
        default_unit_amount_cents: int,
        line_type: str,
    ) -> dict[str, Any]:
        from backend.v2.shared.tenancy import current_academy_id

        now = datetime.now(UTC)
        product = Product(
            product_id=f"prod-{new_ulid()}",
            academy_id=current_academy_id(),
            name=name,
            default_unit_amount_cents=default_unit_amount_cents,
            line_type=line_type,
            active=True,
            created_at=now,
            updated_at=now,
        )
        return _product_dict(await product_repo.create_product(product))

    async def update_billing_product(product_id: str, **updates: object) -> dict[str, Any]:
        return _product_dict(await product_repo.update_product(product_id, **updates))

    async def deactivate_billing_product(product_id: str) -> None:
        await product_repo.deactivate_product(product_id)

    def _invoice_email_port() -> _InvoiceEmailAdapter | None:
        if not (settings.email_delivery_enabled and settings.resend_api_key):
            return None
        return _InvoiceEmailAdapter(
            memberships=MongoMembershipRepository(db),
            users=MongoUserRepository(db, default_academy_id=academy_id),
            sender=_email_sender,
        )

    async def send_billing_invoice(invoice_id: str) -> dict[str, Any]:
        frontend_url = (settings.frontend_url or "https://app.example.com").rstrip("/")
        invoice_stripe = stripe if hasattr(stripe, "create_invoice_checkout_session") else None
        result = await SendInvoice(
            ledger=billing_ledger_repo,
            stripe=invoice_stripe,  # type: ignore[arg-type]
            email=_invoice_email_port(),
            success_url=f"{frontend_url}/parent/payments?invoice=paid",
            cancel_url=f"{frontend_url}/parent/payments?invoice=cancelled",
        ).execute(invoice_id)
        return {
            "invoice_id": result.invoice.invoice_id,
            "delivery_status": result.invoice.delivery_status,
            "sent_at": result.invoice.sent_at,
            "last_sent_at": result.invoice.last_sent_at,
            "checkout_url": result.checkout_url,
        }

    async def charge_invoice_via_autopay(invoice_id: str) -> dict[str, Any]:
        required = ("get_default_payment_method", "create_off_session_payment_intent")
        if not all(hasattr(stripe, name) for name in required):
            raise RuntimeError("Stripe autopay not configured")
        result = await ChargeInvoiceViaAutopay(
            ledger=billing_ledger_repo,
            stripe=stripe,  # type: ignore[arg-type]
        ).execute(invoice_id)
        return result.model_dump(mode="python")

    async def add_invoice_line(
        *,
        invoice_id: str,
        description: str,
        line_type: str,
        quantity: int,
        unit_amount_cents: int,
        product_id: str | None,
    ) -> dict[str, Any]:
        result = await AddInvoiceLine(ledger=billing_ledger_repo).execute(
            AddInvoiceLineCommand(
                invoice_id=invoice_id,
                description=description,
                line_type=line_type,
                quantity=quantity,
                unit_amount_cents=unit_amount_cents,
                product_id=product_id,
            )
        )
        return {
            "line": result.line.model_dump(mode="python"),
            "invoice": result.invoice.model_dump(mode="python"),
        }

    async def remove_invoice_line(*, invoice_id: str, line_id: str) -> None:
        await RemoveInvoiceLine(ledger=billing_ledger_repo).execute(
            RemoveInvoiceLineCommand(invoice_id=invoice_id, line_id=line_id)
        )

    async def void_billing_invoice(*, invoice_id: str, reason: str) -> None:
        invoice = await billing_ledger_repo.get_invoice(invoice_id)
        if invoice is None:
            raise ValueError("invoice not found")
        if (
            invoice.status in {"partially_paid", "paid"}
            or invoice.balance_due_cents != invoice.total_cents
        ):
            raise ValueError(
                "cannot void invoice with recorded payments; issue refund or credit first"
            )
        voided = void_invoice(invoice, reason=reason, now=datetime.now(UTC))
        await billing_ledger_repo.save_invoice(voided)

    async def record_manual_payment(
        *,
        invoice_id: str,
        amount_cents: int,
        payment_method: str,
        reference_number: str | None,
        notes: str,
    ) -> dict[str, Any]:
        result = await RecordManualPayment(ledger=billing_ledger_repo).execute(
            RecordManualPaymentCommand(
                invoice_id=invoice_id,
                amount_cents=amount_cents,
                payment_method=payment_method,  # type: ignore[arg-type]
                reference_number=reference_number,
                notes=notes,
            )
        )
        return result.model_dump(mode="python")

    async def create_student_invoice(
        *,
        student_id: str,
        parent_id: str,
        period: str,
        due_date: date,
        enrollment_id: str | None,
    ) -> dict[str, Any]:
        from backend.v2.shared.tenancy import current_academy_id

        now = datetime.now(UTC)
        invoice_id = f"inv-{new_ulid()}"
        invoice = LedgerInvoice(
            invoice_id=invoice_id,
            academy_id=current_academy_id(),
            parent_id=parent_id,
            student_id=student_id,
            enrollment_id=enrollment_id,
            period=period,
            status="draft",
            subtotal_cents=0,
            discount_cents=0,
            total_cents=0,
            balance_due_cents=0,
            currency="usd",
            due_date=due_date,
            created_at=now,
            updated_at=now,
        )
        created = await billing_ledger_repo.create_invoice(
            invoice,
            lines=[],
            idempotency_key=f"admin-invoice-{invoice_id}",
        )
        return created.model_dump(mode="json")

    send_campaign = SendCampaign(
        campaigns=MongoCampaignRepository(db),
        deliveries=MongoDeliveryRepository(db),
        resolver=MongoAudienceResolver(db=db),
        sender=_email_sender,
    )
    waivers_repo = MongoAdminWaiverRepository(db)
    list_admin_waivers = ListAdminWaivers(waivers_repo)
    waiver_templates_repo = MongoWaiverTemplateRepository(db)
    manage_admin_waiver_templates = ManageAdminWaiverTemplates(waiver_templates_repo)
    admin_registration_review = AdminRegistrationReview(
        apps=MongoApplicationRepository(db),
        sessions=sessions_w,
        students=students_w,
        enrollments=enrollments_w,
        waitlist=waitlist,
        waiver_templates=waiver_templates_repo,
        enrollment_events=enrollment_events,
        academy_id=academy_id,
    )
    # Identity / Settings
    academy_repo = MongoAcademyRepository(db)
    get_academy_use_case = GetAcademyUseCase(academy_repo)
    update_academy_use_case = UpdateAcademyUseCase(academy_repo)
    get_academy_fees_use_case = GetAcademyFeesUseCase(academy_repo)
    update_academy_fees_use_case = UpdateAcademyFeesUseCase(academy_repo)
    get_academy_notifications_use_case = GetAcademyNotificationsUseCase(
        academy_repo,
        default_coach_digest_enabled=settings.coach_digest_enabled,
        default_coach_digest_hour=settings.coach_digest_hour,
    )
    update_academy_notifications_use_case = UpdateAcademyNotificationsUseCase(
        academy_repo,
        default_coach_digest_enabled=settings.coach_digest_enabled,
        default_coach_digest_hour=settings.coach_digest_hour,
    )
    get_academy_gateway_use_case = GetAcademyGatewayUseCase(academy_repo)
    _connect_callback_uri = settings.stripe_connect_callback_uri or ""
    _state_secret = settings.stripe_connect_state_secret or settings.stripe_webhook_secret or ""
    start_stripe_connect_use_case = StartStripeConnectUseCase(
        gateway=stripe,
        state_secret=_state_secret,
        redirect_uri=_connect_callback_uri,
    )
    complete_stripe_connect_use_case = CompleteStripeConnectUseCase(
        gateway=stripe,
        repo=academy_repo,
        state_secret=_state_secret,
    )
    disconnect_stripe_use_case = DisconnectStripeUseCase(repo=academy_repo)
    change_user_role = ChangeUserRole(users_r)

    list_admin_users = ListAdminUsers(users_r)
    get_admin_user = GetAdminUser(users_r)
    update_admin_user = UpdateAdminUser(users_r)
    create_admin_user = CreateAdminUser(users_r)
    list_admin_students = ListAdminStudents(students_r)
    get_admin_student = GetAdminStudent(students_r)
    update_admin_student = UpdateAdminStudent(students_r)
    change_admin_student_parent = ChangeAdminStudentParent(students_r)

    async def _build_admin_session_rows(docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        from backend.v2.shared.tenancy import current_academy_id

        request_academy_id = current_academy_id()
        rows: list[dict[str, Any]] = []
        for doc in docs:
            session_id = str(doc.get("session_id") or doc.get("_id"))
            enrolled_count = await enrollments_r.collection.count_documents(
                {
                    "academy_id": request_academy_id,
                    "session_id": session_id,
                    "status": "active",
                }
            )
            waitlist_count = await waitlist.collection.count_documents(
                {
                    "academy_id": request_academy_id,
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
                    if str(doc.get("status") or "scheduled") in {"active", "open"}
                    else str(doc.get("status") or "scheduled"),
                    "coach_id": str(doc.get("coach_id") or ""),
                    "enrolled_count": enrolled_count,
                    "waitlist_count": waitlist_count,
                    "days_of_week": list(doc.get("days_of_week") or []),
                    "start_time": doc.get("start_time"),
                    "end_time": doc.get("end_time"),
                    "timezone": doc.get("timezone"),
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

    async def get_admin_session(session_id: str):
        session = await sessions_r.get(session_id)
        if session is None:
            return None
        rows = await _build_admin_session_rows([session.model_dump(mode="python")])
        return rows[0] if rows else None

    def _normalized_series_text(value: object) -> str:
        return " ".join(str(value or "").strip().casefold().split())

    _WEEKDAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
    _WEEKDAY_INDEX = {
        "mon": 0,
        "monday": 0,
        "tue": 1,
        "tuesday": 1,
        "wed": 2,
        "wednesday": 2,
        "thu": 3,
        "thursday": 3,
        "fri": 4,
        "friday": 4,
        "sat": 5,
        "saturday": 5,
        "sun": 6,
        "sunday": 6,
    }

    def _canonical_weekdays(days: object) -> tuple[str, ...]:
        values = list(days or []) if isinstance(days, list) else []
        canonical: set[str] = set()
        passthrough: set[str] = set()
        for day in values:
            raw = str(day).strip()
            index = _WEEKDAY_INDEX.get(raw.casefold())
            if index is None:
                if raw:
                    passthrough.add(raw)
                continue
            canonical.add(_WEEKDAY_NAMES[index])
        return tuple(
            sorted(canonical, key=lambda day: _WEEKDAY_NAMES.index(day)) + sorted(passthrough)
        )

    def _local_interval_utc(
        occurrence_date: date,
        start_time: time,
        end_time: time,
        tz: ZoneInfo,
    ) -> tuple[datetime, datetime]:
        local_start = datetime.combine(occurrence_date, start_time, tzinfo=tz)
        local_end = datetime.combine(occurrence_date, end_time, tzinfo=tz)
        if local_end <= local_start:
            local_end += timedelta(days=1)
        return local_start.astimezone(UTC), local_end.astimezone(UTC)

    def _dated_session_range_filter(start: datetime, end: datetime) -> dict[str, Any]:
        return {
            "start_at": {"$gte": start, "$lte": end},
            "$or": [
                {"days_of_week": {"$exists": False}},
                {"days_of_week": []},
                {"days_of_week": None},
            ],
        }

    def _series_local_clock_signature(
        row: dict[str, Any],
    ) -> tuple[tuple[str, ...], str, str, str] | None:
        timezone_name = str(row.get("timezone") or "America/Chicago")
        days = list(row.get("days_of_week") or [])
        if days and row.get("start_time") and row.get("end_time"):
            return (
                _canonical_weekdays(days),
                str(row.get("start_time") or ""),
                str(row.get("end_time") or ""),
                timezone_name,
            )

        start_at = row.get("start_at")
        end_at = row.get("end_at")
        if not start_at or not end_at:
            return None
        tz = ZoneInfo(timezone_name)
        local_start = _as_utc_datetime(start_at).astimezone(tz)
        local_end = _as_utc_datetime(end_at).astimezone(tz)
        weekday = _WEEKDAY_NAMES[local_start.weekday()]
        return (
            (weekday,),
            local_start.strftime("%H:%M"),
            local_end.strftime("%H:%M"),
            timezone_name,
        )

    def _session_series_signature(row: dict[str, Any]) -> tuple[object, ...] | None:
        clock_signature = _series_local_clock_signature(row)
        if clock_signature is None:
            return None
        days, start_time_value, end_time_value, timezone_name = clock_signature
        return (
            _normalized_series_text(row.get("location")),
            str(row.get("coach_id") or ""),
            days,
            start_time_value,
            end_time_value,
            timezone_name,
        )

    def _recurring_row_rank(row: dict[str, Any]) -> tuple[int, int, datetime]:
        start_at = row["start_at"]
        if getattr(start_at, "tzinfo", None) is None:
            start_at = start_at.replace(tzinfo=UTC)
        return (
            int(row.get("enrolled_count") or 0),
            int(row.get("waitlist_count") or 0),
            -start_at.timestamp(),
        )

    def _dedupe_session_series_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        deduped: list[dict[str, Any]] = []
        index_by_signature: dict[tuple[object, ...], int] = {}
        for row in rows:
            signature = _session_series_signature(row)
            if signature is None:
                deduped.append(row)
                continue
            existing_index = index_by_signature.get(signature)
            if existing_index is None:
                index_by_signature[signature] = len(deduped)
                deduped.append(row)
                continue
            existing = deduped[existing_index]
            if _recurring_row_rank(row) > _recurring_row_rank(existing):
                deduped[existing_index] = row
        return deduped

    def _series_occurrence_candidates(session) -> list[dict[str, Any]]:
        if not session.days_of_week or not session.start_time or not session.end_time:
            return []
        if session.status == "cancelled":
            return []
        timezone_name = session.timezone or "America/Chicago"
        tz = ZoneInfo(timezone_name)
        target_days = {
            _WEEKDAY_INDEX[str(day).casefold()]
            for day in session.days_of_week
            if str(day).casefold() in _WEEKDAY_INDEX
        }
        if not target_days:
            return []
        local_start = datetime.now(UTC).astimezone(tz).date()
        local_end = (datetime.now(UTC) + timedelta(days=60)).astimezone(tz).date()
        start_time = time.fromisoformat(session.start_time)
        end_time = time.fromisoformat(session.end_time)
        rows: list[dict[str, Any]] = []
        current = local_start
        while current <= local_end:
            if current.weekday() in target_days:
                starts_at, ends_at = _local_interval_utc(current, start_time, end_time, tz)
                occurrence_id = (
                    f"{session.session_id}:{current.isoformat()}:{start_time.strftime('%H:%M')}"
                )
                rows.append(
                    {
                        "occurrence_id": occurrence_id,
                        "academy_id": session.academy_id,
                        "session_id": session.session_id,
                        "template_session_id": session.session_id,
                        "start_at": starts_at,
                        "end_at": ends_at,
                        "status": "scheduled",
                        "scheduled_coach_id": session.coach_id,
                        "actual_coach_id": None,
                        "substitute_coach_id": None,
                        "is_billable": True,
                        "is_payable": True,
                    }
                )
            current += timedelta(days=1)
        return rows

    def _series_occurrence_candidate_for_date(
        session,
        occurrence_date: date,
    ) -> dict[str, Any]:
        if session.status == "cancelled":
            raise ValueError("Replacement cannot be added to a cancelled session")
        timezone_name = session.timezone or "America/Chicago"
        tz = ZoneInfo(timezone_name)
        target_days = {
            _WEEKDAY_INDEX[str(day).casefold()]
            for day in session.days_of_week
            if str(day).casefold() in _WEEKDAY_INDEX
        }
        if not target_days:
            raise ValueError("Session does not have a supported recurring weekday")
        now = datetime.now(UTC)
        local_today = now.astimezone(tz).date()
        local_window_end = (now + timedelta(days=60)).astimezone(tz).date()
        if occurrence_date < local_today or occurrence_date > local_window_end:
            raise ValueError("Replacement date must be within today through 60 days ahead")
        if occurrence_date.weekday() not in target_days:
            raise ValueError("Replacement date must match the session weekday")

        start_time = time.fromisoformat(session.start_time)
        end_time = time.fromisoformat(session.end_time)
        starts_at, ends_at = _local_interval_utc(occurrence_date, start_time, end_time, tz)
        occurrence_id = (
            f"{session.session_id}:{occurrence_date.isoformat()}:{start_time.strftime('%H:%M')}"
        )
        return {
            "occurrence_id": occurrence_id,
            "academy_id": session.academy_id,
            "session_id": session.session_id,
            "template_session_id": session.session_id,
            "start_at": starts_at,
            "end_at": ends_at,
            "status": "scheduled",
            "scheduled_coach_id": session.coach_id,
            "actual_coach_id": None,
            "substitute_coach_id": None,
            "is_billable": True,
            "is_payable": True,
        }

    def _dated_occurrence_candidate_for_date(
        session,
        occurrence_date: date,
        *,
        matched_session_doc: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if session.status == "cancelled":
            raise ValueError("Replacement cannot be added to a cancelled session")
        timezone_name = session.timezone or "America/Chicago"
        tz = ZoneInfo(timezone_name)
        starts_at = _as_utc_datetime(session.start_at)
        ends_at = _as_utc_datetime(session.end_at)
        local_start = starts_at.astimezone(tz)
        local_end = ends_at.astimezone(tz)
        now = datetime.now(UTC)
        local_today = now.astimezone(tz).date()
        local_window_end = (now + timedelta(days=60)).astimezone(tz).date()
        if occurrence_date < local_today or occurrence_date > local_window_end:
            raise ValueError("Replacement date must be within today through 60 days ahead")
        if occurrence_date.weekday() != local_start.weekday():
            raise ValueError("Replacement date must match the session weekday")
        if matched_session_doc is not None:
            session_id = str(
                matched_session_doc.get("session_id") or matched_session_doc.get("_id")
            )
            starts_at = _as_utc_datetime(matched_session_doc["start_at"])
            ends_at = _as_utc_datetime(matched_session_doc["end_at"])
            return {
                "occurrence_id": session_id,
                "academy_id": session.academy_id,
                "session_id": session_id,
                "template_session_id": session_id,
                "start_at": starts_at,
                "end_at": ends_at,
                "status": str(matched_session_doc.get("status") or "scheduled"),
                "scheduled_coach_id": str(matched_session_doc.get("coach_id") or session.coach_id),
                "actual_coach_id": None,
                "substitute_coach_id": None,
                "is_billable": True,
                "is_payable": True,
            }
        starts_at, ends_at = _local_interval_utc(
            occurrence_date,
            local_start.timetz().replace(tzinfo=None),
            local_end.timetz().replace(tzinfo=None),
            tz,
        )
        occurrence_id = (
            f"{session.session_id}:{occurrence_date.isoformat()}:{local_start.strftime('%H:%M')}"
        )
        return {
            "occurrence_id": occurrence_id,
            "academy_id": session.academy_id,
            "session_id": session.session_id,
            "template_session_id": session.session_id,
            "start_at": starts_at,
            "end_at": ends_at,
            "status": "scheduled",
            "scheduled_coach_id": session.coach_id,
            "actual_coach_id": None,
            "substitute_coach_id": None,
            "is_billable": True,
            "is_payable": True,
        }

    def _session_domain_row(session) -> dict[str, Any]:
        return session.model_dump(mode="python")

    async def _matching_dated_series_session_doc(
        session,
        occurrence_date: date,
    ) -> dict[str, Any] | None:
        target_signature = _session_series_signature(_session_domain_row(session))
        if target_signature is None:
            return None
        timezone_name = session.timezone or "America/Chicago"
        tz = ZoneInfo(timezone_name)
        cursor = sessions_r._find_many(  # type: ignore[attr-defined]
            {
                "coach_id": session.coach_id,
                "location": session.location,
                "$or": [
                    {"days_of_week": {"$exists": False}},
                    {"days_of_week": []},
                    {"days_of_week": None},
                ],
            },
            sort=[("start_at", 1)],
        )
        async for doc in cursor:
            if str(doc.get("status") or "scheduled") == "cancelled":
                continue
            if _session_series_signature(doc) != target_signature:
                continue
            starts_at = doc.get("start_at")
            if starts_at is None:
                continue
            if _as_utc_datetime(starts_at).astimezone(tz).date() == occurrence_date:
                return doc
        return None

    async def _dated_series_session_ids(session) -> list[str]:
        target_signature = _session_series_signature(_session_domain_row(session))
        if target_signature is None:
            return [session.session_id]
        cursor = sessions_r._find_many(  # type: ignore[attr-defined]
            {
                "coach_id": session.coach_id,
                "location": session.location,
                "$or": [
                    {"days_of_week": {"$exists": False}},
                    {"days_of_week": []},
                    {"days_of_week": None},
                ],
            },
            sort=[("start_at", 1)],
        )
        ids: list[str] = []
        async for doc in cursor:
            if str(doc.get("status") or "scheduled") == "cancelled":
                continue
            if _session_series_signature(doc) != target_signature:
                continue
            session_id = str(doc.get("session_id") or doc.get("_id") or "")
            if session_id and session_id not in ids:
                ids.append(session_id)
        if session.session_id not in ids:
            ids.insert(0, session.session_id)
        return ids

    async def _replacement_occurrence_candidate_for_date(
        session,
        occurrence_date: date,
    ) -> dict[str, Any]:
        if session.days_of_week and session.start_time and session.end_time:
            return _series_occurrence_candidate_for_date(session, occurrence_date)
        matched_doc = await _matching_dated_series_session_doc(session, occurrence_date)
        if matched_doc is None:
            raise ValueError("Replacement date must match a scheduled session date")
        return _dated_occurrence_candidate_for_date(
            session,
            occurrence_date,
            matched_session_doc=matched_doc,
        )

    def _as_utc_datetime(value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

    async def _is_clean_future_occurrence(doc: dict[str, Any], *, now: datetime) -> bool:
        starts_at = doc.get("start_at")
        if starts_at is None or _as_utc_datetime(starts_at) < now:
            return False
        if str(doc.get("status") or "scheduled") != "scheduled":
            return False
        if doc.get("actual_coach_id") or doc.get("substitute_coach_id"):
            return False
        academy_id = str(doc.get("academy_id") or "")
        occurrence_id = str(doc.get("occurrence_id") or "")
        if await db["attendance"].count_documents(
            {"academy_id": academy_id, "occurrence_id": occurrence_id}, limit=1
        ):
            return False
        if await db["coach_attendance"].count_documents(
            {"academy_id": academy_id, "occurrence_id": occurrence_id}, limit=1
        ):
            return False
        if await db["payout_period_lines"].count_documents(
            {"academy_id": academy_id, "occurrence_id": occurrence_id}, limit=1
        ):
            return False
        return True

    async def maintain_session_occurrences(session) -> None:
        from backend.v2.shared.tenancy import current_academy_id

        candidates = _series_occurrence_candidates(session)
        if not candidates and session.status != "cancelled":
            return
        academy_id = current_academy_id()
        now = datetime.now(UTC)
        window_end = now + timedelta(days=60, hours=23, minutes=59, seconds=59)
        cursor = db["session_occurrences"].find(
            {
                "academy_id": academy_id,
                "$or": [
                    {"session_id": session.session_id},
                    {"template_session_id": session.session_id},
                ],
                "start_at": {"$gte": now, "$lte": window_end},
            }
        )
        existing = {str(doc["occurrence_id"]): doc async for doc in cursor}
        candidate_ids = {row["occurrence_id"] for row in candidates}
        for occurrence_id, doc in existing.items():
            if occurrence_id in candidate_ids:
                continue
            if await _is_clean_future_occurrence(doc, now=now):
                await db["session_occurrences"].delete_one(
                    {"academy_id": academy_id, "occurrence_id": occurrence_id}
                )

        for row in candidates:
            existing_doc = existing.get(str(row["occurrence_id"]))
            if existing_doc is not None and not await _is_clean_future_occurrence(
                existing_doc, now=now
            ):
                continue
            await db["session_occurrences"].update_one(
                {"academy_id": academy_id, "occurrence_id": row["occurrence_id"]},
                {
                    "$set": {
                        "session_id": row["session_id"],
                        "template_session_id": row["template_session_id"],
                        "start_at": row["start_at"],
                        "end_at": row["end_at"],
                        "status": row["status"],
                        "scheduled_coach_id": row["scheduled_coach_id"],
                        "actual_coach_id": None,
                        "substitute_coach_id": None,
                        "is_billable": True,
                        "is_payable": True,
                    },
                    "$setOnInsert": {
                        "academy_id": academy_id,
                        "occurrence_id": row["occurrence_id"],
                    },
                },
                upsert=True,
            )

    async def list_admin_sessions(
        on_date: date | None, *, window: str | None = None, coach_id: str | None = None
    ):
        # window="upcoming" returns all dated sessions from now through +30d.
        # Used by the transfer-enrollment dropdown so the user can pick any
        # upcoming session, not just today's.
        if window == "upcoming":
            now = datetime.now(UTC)
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(
                days=30,
                hours=23,
                minutes=59,
                seconds=59,
                microseconds=999999,
            )
            v2_cursor = sessions_r._find_many(  # type: ignore[attr-defined]
                _dated_session_range_filter(start, end),
                sort=[("start_at", 1)],
            )
            upcoming_docs = [doc async for doc in v2_cursor]
            template_cursor = sessions_r._find_many(  # type: ignore[attr-defined]
                {"days_of_week": {"$exists": True}},
            )
            template_docs = [doc async for doc in template_cursor]
            upcoming_docs.extend(
                synthesize_recurring_session_docs(
                    template_docs,
                    range_start=start,
                    range_end=end,
                    first_per_template=True,
                )
            )
            upcoming_docs.sort(key=session_start_sort_key)
            rows = await _build_admin_session_rows(upcoming_docs)
            rows = _dedupe_session_series_rows(rows)
            if coach_id:
                rows = [
                    r
                    for r in rows
                    if (r.get("coach_id") if isinstance(r, dict) else getattr(r, "coach_id", None))
                    == coach_id
                ]
            return rows

        if on_date is None:
            on_date = datetime.now(UTC).date()
        start = datetime.combine(on_date, time.min, tzinfo=UTC)
        end = datetime.combine(on_date, time.max, tzinfo=UTC)

        # Query both v2 sessions (start_at field) and legacy recurring templates
        # (days_of_week field). The two schemas coexist during migration.
        all_docs: list[dict[str, Any]] = []

        # v2 schema: individual session instances with start_at/end_at
        v2_cursor = sessions_r._find_many(  # type: ignore[attr-defined]
            _dated_session_range_filter(start, end),
            sort=[("start_at", 1)],
        )
        async for doc in v2_cursor:
            all_docs.append(doc)

        legacy_cursor = sessions_r._find_many(  # type: ignore[attr-defined]
            {"days_of_week": {"$exists": True}},
        )
        template_docs = [doc async for doc in legacy_cursor]
        all_docs.extend(
            synthesize_recurring_session_docs(
                template_docs,
                range_start=start,
                range_end=end,
                local_start_date=on_date,
                local_end_date=on_date,
                filter_by_utc_range=False,
            )
        )
        all_docs.sort(key=session_start_sort_key)

        rows = await _build_admin_session_rows(all_docs)
        rows = _dedupe_session_series_rows(rows)
        if coach_id:
            rows = [
                r
                for r in rows
                if (r.get("coach_id") if isinstance(r, dict) else getattr(r, "coach_id", None))
                == coach_id
            ]
        return rows

    async def list_admin_enrollments_for_session(session_id: str):
        cursor = enrollments_r._find_many(  # type: ignore[attr-defined]
            {"session_id": session_id, "status": "active"},
            sort=[("created_at", 1), ("enrollment_id", 1)],
        )
        enrollment_docs = [doc async for doc in cursor]
        if not enrollment_docs:
            return []
        active = [enrollments_r._to_domain(doc) for doc in enrollment_docs]  # type: ignore[attr-defined]
        student_ids = [e.student_id for e in active]
        students = await students_r.by_ids(student_ids)
        by_id = {s.student_id: s for s in students}
        student_detail_by_id: dict[str, dict[str, Any]] = {}
        if student_ids:
            async for student_doc in db["students"].find(
                {"academy_id": academy_id, "student_id": {"$in": student_ids}}
            ):
                student_detail_by_id[str(student_doc.get("student_id"))] = student_doc
        dues_status_by_id: dict[str, str] = {}
        if hasattr(students_r, "_dues_statuses"):
            dues_status_by_id = await students_r._dues_statuses(academy_id, student_ids)  # type: ignore[attr-defined]
        default_program_id: str | None = None
        try:
            default_program = await curriculum.resolve_default_program.execute()
            default_program_id = default_program.program_id
        except Exception:
            default_program_id = None
        out: list[dict] = []
        by_enrollment_id = {
            str(doc["enrollment_id"]): doc for doc in enrollment_docs if "enrollment_id" in doc
        }
        for e in active:
            doc = by_enrollment_id.get(e.enrollment_id, {})
            s = by_id.get(e.student_id)
            full_name = s.full_name if s else "(unknown)"
            student_doc = student_detail_by_id.get(e.student_id, {})
            placement_fields: dict[str, Any] = {
                "pathway_program_id": default_program_id,
                "pathway_level_id": None,
                "pathway_level_sequence": None,
                "pathway_level_name": None,
                "pathway_placement_status": "unplaced",
                "pathway_skills_total": 0,
                "pathway_skills_completed": 0,
                "pathway_skills_ready_for_test": 0,
                "pathway_completion_percentage": 0,
                "pathway_next_action": "place_in_level",
            }
            if default_program_id is not None:
                placement = await student_progress.get_pathway_placement.execute(
                    StudentPathwayPlacementRequest(
                        student_id=e.student_id,
                        program_id=default_program_id,
                    )
                )
                placement_fields = {
                    "pathway_program_id": placement.program_id,
                    "pathway_level_id": placement.level_id,
                    "pathway_level_sequence": placement.level_sequence,
                    "pathway_level_name": placement.level_name,
                    "pathway_placement_status": placement.placement_status,
                    "pathway_skills_total": placement.skills_total,
                    "pathway_skills_completed": placement.skills_completed,
                    "pathway_skills_ready_for_test": placement.skills_ready_for_test,
                    "pathway_completion_percentage": placement.completion_percentage,
                    "pathway_next_action": placement.next_action,
                }
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
                    "level": student_doc.get("level"),
                    **placement_fields,
                    "dues_status": dues_status_by_id.get(e.student_id, "current"),
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
        coach_attendance_rows = await coach_attendance_repo.list_for_occurrences(
            [occurrence.occurrence_id]
        )
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
            "coach_attendance": [
                row.model_dump(exclude={"academy_id"}) for row in coach_attendance_rows
            ],
        }

    async def list_session_occurrences(session_id: str) -> list[dict[str, Any]]:
        session = await sessions_r.get(session_id)
        if session is not None and not (
            session.days_of_week and session.start_time and session.end_time
        ):
            occurrence_by_id = {}
            for series_session_id in await _dated_series_session_ids(session):
                for occurrence in await occurrences_r.list_for_session(series_session_id):
                    occurrence_by_id[occurrence.occurrence_id] = occurrence
            occurrences = sorted(
                occurrence_by_id.values(),
                key=lambda occurrence: occurrence.start_at,
            )
            return [await _occurrence_row(occurrence) for occurrence in occurrences]
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

    async def _clear_or_reject_replacement_payout_snapshots(
        *,
        academy_id: str,
        occurrence_id: str,
    ) -> None:
        payout_line_cursor = db["payout_period_lines"].find(
            {"academy_id": academy_id, "occurrence_id": occurrence_id},
            {"period_id": 1},
        )
        payout_period_ids = sorted(
            {str(row["period_id"]) async for row in payout_line_cursor if row.get("period_id")}
        )
        if not payout_period_ids:
            return
        period_cursor = db["payout_periods"].find(
            {
                "academy_id": academy_id,
                "period_id": {"$in": payout_period_ids},
            },
            {"period_id": 1, "status": 1},
        )
        draft_period_ids: list[str] = []
        async for period in period_cursor:
            status = str(period.get("status") or "draft")
            if status in {"approved", "paid"}:
                raise ValueError(
                    "Replacement coach cannot be changed after payout is approved or paid"
                )
            draft_period_ids.append(str(period["period_id"]))
        if draft_period_ids:
            await db["payout_period_lines"].delete_many(
                {"academy_id": academy_id, "period_id": {"$in": draft_period_ids}}
            )
            await db["payout_periods"].delete_many(
                {"academy_id": academy_id, "period_id": {"$in": draft_period_ids}}
            )

    async def update_session_occurrence_replacement(
        *,
        occurrence_id: str,
        replacement_coach_id: str | None,
        actor_id: str,
        reason: str,
    ) -> dict[str, Any] | None:
        from backend.v2.shared.tenancy import current_academy_id

        academy_id = current_academy_id()
        await _clear_or_reject_replacement_payout_snapshots(
            academy_id=academy_id,
            occurrence_id=occurrence_id,
        )

        update_fields: dict[str, Any] = {
            "actual_coach_id": replacement_coach_id,
            "substitute_coach_id": None,
            "replacement_reason": reason,
            "replacement_updated_by": actor_id,
            "updated_at": datetime.now(UTC),
        }
        result = await db["session_occurrences"].update_one(
            {"academy_id": academy_id, "occurrence_id": occurrence_id},
            {"$set": update_fields},
        )
        if result.matched_count == 0:
            return None
        occurrence = await occurrences_r.get(occurrence_id)
        return None if occurrence is None else await _occurrence_row(occurrence)

    async def add_session_replacement(
        *,
        session_id: str,
        occurrence_date: date,
        replacement_coach_id: str,
        actor_id: str,
        reason: str,
    ) -> dict[str, Any] | None:
        from backend.v2.shared.tenancy import current_academy_id

        academy_id = current_academy_id()
        session = await sessions_r.get(session_id)
        if session is None:
            return None
        candidate = await _replacement_occurrence_candidate_for_date(session, occurrence_date)
        await db["session_occurrences"].update_one(
            {"academy_id": academy_id, "occurrence_id": candidate["occurrence_id"]},
            {
                "$setOnInsert": {
                    **candidate,
                    "academy_id": academy_id,
                }
            },
            upsert=True,
        )
        return await update_session_occurrence_replacement(
            occurrence_id=str(candidate["occurrence_id"]),
            replacement_coach_id=replacement_coach_id,
            actor_id=actor_id,
            reason=reason,
        )

    class _AdminOccurrenceLookup:
        async def get(self, occurrence_id: str):
            occurrence = await occurrences_r.get(occurrence_id)
            if occurrence is None:
                return None
            from backend.v2.contexts.coaching.application.ports import OccurrenceDetails

            return OccurrenceDetails(
                occurrence_id=occurrence.occurrence_id,
                session_id=occurrence.template_session_id or occurrence.session_id,
                starts_at=occurrence.start_at,
                status=occurrence.status,
                scheduled_coach_id=occurrence.scheduled_coach_id,
                actual_coach_id=occurrence.actual_coach_id,
                substitute_coach_id=occurrence.substitute_coach_id,
                template_session_id=occurrence.template_session_id,
            )

    mark_coach_attendance = MarkCoachAttendance(
        coach_attendance=coach_attendance_repo,
        occurrence_lookup=_AdminOccurrenceLookup(),
        academy_id=academy_id,
    )

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
        from backend.v2.shared.tenancy import current_academy_id

        request_academy_id = current_academy_id()
        cursor = (
            db["payments"]
            .find({"academy_id": request_academy_id, "is_deleted": {"$ne": True}})
            .sort([("created_at", -1)])
            .limit(200)
        )
        legacy = [
            payments_repo._to_admin_row(payment, None)  # type: ignore[attr-defined]
            async for payment in cursor
        ]
        ledger_rows: list[dict[str, Any]] = []
        async for doc in db["ledger_payments"].find(
            {"academy_id": request_academy_id},
            sort=[("created_at", -1)],
            limit=200,
        ):
            ledger_rows.append(
                {
                    "payment_id": str(doc.get("payment_id") or ""),
                    "parent_id": str(doc.get("parent_id") or ""),
                    "session_id": None,
                    "amount_cents": int(doc.get("amount_cents") or 0),
                    "final_amount_cents": int(doc.get("amount_cents") or 0),
                    "currency": str(doc.get("currency") or "usd"),
                    "status": str(doc.get("status") or ""),
                    "refunded_cents": int(doc.get("refunded_cents") or 0),
                    "stripe_payment_intent_id": doc.get("stripe_payment_intent_id"),
                    "payment_method": doc.get("payment_method"),
                    "created_at": doc["created_at"],
                }
            )
        combined = ledger_rows + legacy
        combined.sort(
            key=lambda r: (r.get("created_at") if isinstance(r, dict) else None)
            or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )
        return combined[:200]

    async def reconcile_stripe_billing(
        *,
        parent_id: str,
        enrollment_id: str,
        stripe_customer_id: str | None,
        stripe_checkout_session_id: str,
        reason: str,
        actor_id: str,
    ) -> dict[str, Any]:
        reason = reason.strip()
        if not reason:
            raise ValueError("reason is required")
        checkout = await stripe.retrieve_checkout_session(stripe_checkout_session_id)
        metadata = checkout.get("metadata") if isinstance(checkout.get("metadata"), dict) else {}
        metadata = metadata or {}
        checkout_academy_id = metadata.get("academy_id")
        if checkout_academy_id and str(checkout_academy_id) != academy_id:
            raise ValueError("Stripe Checkout Session belongs to a different academy")
        checkout_parent_id = str(
            metadata.get("parent_id") or checkout.get("client_reference_id") or ""
        )
        if checkout_parent_id and checkout_parent_id != parent_id:
            raise ValueError("Stripe Checkout Session belongs to a different parent")
        checkout_enrollment_id = str(metadata.get("enrollment_id") or "")
        if checkout_enrollment_id and checkout_enrollment_id != enrollment_id:
            raise ValueError("Stripe Checkout Session belongs to a different enrollment")

        enrollment = await db["enrollments"].find_one(
            {
                "academy_id": academy_id,
                "enrollment_id": enrollment_id,
                "$or": [{"parent_id": parent_id}, {"parent_user_id": parent_id}],
            }
        )
        if enrollment is None:
            raise ValueError("enrollment not found for parent in this academy")

        now = datetime.now(UTC)
        customer_id = str(stripe_customer_id or checkout.get("customer") or "")
        stripe_subscription_id = str(checkout.get("subscription") or "")
        stripe_invoice_id = str(checkout.get("invoice") or "")
        stripe_payment_intent_id = str(checkout.get("payment_intent") or "")
        payment_status = str(checkout.get("payment_status") or "")
        checkout_status = str(checkout.get("status") or "")
        if not stripe_payment_intent_id and stripe_invoice_id:
            invoice = await stripe.retrieve_invoice(stripe_invoice_id)
            stripe_payment_intent_id = str(invoice.get("payment_intent") or "")
        if customer_id:
            await parent_customers_repo.set_stripe_customer_id(
                parent_id=parent_id,
                stripe_customer_id=customer_id,
            )

        app_subscription_id = str(
            metadata.get("app_subscription_id") or metadata.get("subscription_id") or ""
        )
        if stripe_subscription_id:
            subscription_filter: dict[str, Any] = {"academy_id": academy_id}
            if app_subscription_id:
                subscription_filter["subscription_id"] = app_subscription_id
            else:
                subscription_filter["enrollment_id"] = enrollment_id
            await db["subscriptions"].update_one(
                subscription_filter,
                {
                    "$set": {
                        "academy_id": academy_id,
                        "parent_id": parent_id,
                        "enrollment_id": enrollment_id,
                        "session_id": str(enrollment.get("session_id") or ""),
                        "stripe_subscription_id": stripe_subscription_id,
                        "status": "active" if payment_status == "paid" else "incomplete",
                        "payment_mode": "monthly",
                        "updated_at": now,
                    },
                    "$setOnInsert": {
                        "subscription_id": app_subscription_id or str(new_ulid()),
                        "created_at": now,
                    },
                },
                upsert=True,
            )
            await db["enrollments"].update_one(
                {"academy_id": academy_id, "enrollment_id": enrollment_id},
                {
                    "$set": {
                        "payment_mode": "monthly",
                        "subscription_status": "active"
                        if payment_status == "paid"
                        else "incomplete",
                        "stripe_subscription_id": stripe_subscription_id,
                        "updated_at": now,
                    }
                },
            )

        payment_id: str | None = None
        mismatch_state: str | None = None
        if payment_status == "paid" and checkout_status == "complete":
            amount_total = int(checkout.get("amount_total") or 0)
            payment = await db["payments"].find_one(
                {
                    "academy_id": academy_id,
                    "enrollment_id": enrollment_id,
                    "status": {"$in": ["pending", "partially_paid"]},
                    "is_deleted": {"$ne": True},
                },
                sort=[("created_at", -1), ("payment_id", 1)],
            )
            if payment is not None:
                final_amount = int(
                    payment.get(
                        "final_amount_cents",
                        int(payment.get("amount_cents") or payment.get("gross_amount_cents") or 0)
                        - int(payment.get("discount_cents") or 0),
                    )
                )
                if amount_total and final_amount and amount_total != final_amount:
                    mismatch_state = "Mongo pending amount differs from Stripe paid amount"
                else:
                    payment_id = str(payment.get("payment_id") or payment.get("_id"))
                    await db["payments"].update_one(
                        {"_id": payment["_id"]},
                        {
                            "$set": {
                                "status": "succeeded",
                                "payment_method": "stripe",
                                "stripe_checkout_session_id": stripe_checkout_session_id,
                                "stripe_subscription_id": stripe_subscription_id or None,
                                "stripe_invoice_id": stripe_invoice_id or None,
                                "stripe_payment_intent_id": stripe_payment_intent_id or None,
                                "amount_received_cents": amount_total or final_amount,
                                "paid_amount_cents": amount_total or final_amount,
                                "balance_due_cents": 0,
                                "paid_at": now,
                                "updated_at": now,
                            }
                        },
                    )
            else:
                mismatch_state = "Stripe paid but no pending Mongo payment found"

        audit_id = str(new_ulid())
        await db["audit_logs"].insert_one(
            {
                "audit_id": audit_id,
                "academy_id": academy_id,
                "actor_id": actor_id,
                "action": "billing.stripe_reconcile",
                "entity_type": "enrollment",
                "entity_id": enrollment_id,
                "created_at": now,
                "reason": reason,
                "metadata": {
                    "parent_id": parent_id,
                    "payment_id": payment_id,
                    "stripe_customer_id": customer_id,
                    "stripe_checkout_session_id": stripe_checkout_session_id,
                    "stripe_subscription_id": stripe_subscription_id,
                    "stripe_invoice_id": stripe_invoice_id,
                    "stripe_payment_intent_id": stripe_payment_intent_id,
                    "payment_status": payment_status,
                    "checkout_status": checkout_status,
                    "mismatch_state": mismatch_state,
                },
            }
        )
        return {
            "ok": True,
            "mismatch_state": mismatch_state,
            "payment_id": payment_id,
            "stripe_customer_id": customer_id or None,
            "stripe_checkout_session_id": stripe_checkout_session_id,
            "stripe_subscription_id": stripe_subscription_id or None,
            "stripe_invoice_id": stripe_invoice_id or None,
            "stripe_payment_intent_id": stripe_payment_intent_id or None,
            "audit_id": audit_id,
        }

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
        from backend.v2.shared.tenancy import current_academy_id

        request_academy_id = current_academy_id()
        cursor = (
            db["audit_logs"]
            .find({"academy_id": request_academy_id})
            .sort([("created_at", -1)])
            .limit(200)
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
        from backend.v2.shared.tenancy import current_academy_id

        request_academy_id = current_academy_id()
        cursor = (
            db["payments"]
            .find(
                {
                    "academy_id": request_academy_id,
                    "status": "pending",
                    "is_deleted": {"$ne": True},
                }
            )
            .sort([("created_at", -1)])
            .limit(500)
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
            users = db["users"].find({"academy_id": request_academy_id, "$or": or_filter})
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
        from backend.v2.shared.tenancy import current_academy_id

        def _invoice_line_response(line: dict[str, Any]) -> dict[str, Any]:
            payload: dict[str, Any] = {
                "line_id": str(line.get("line_id") or ""),
                "invoice_id": str(line.get("invoice_id") or ""),
                "description": str(line.get("description", "")),
                "amount_cents": int(line.get("amount_cents", 0)),
            }
            for key in (
                "line_type",
                "quantity",
                "unit_amount_cents",
                "source_type",
                "source_id",
            ):
                if line.get(key) is not None:
                    payload[key] = line[key]
            return payload

        request_academy_id = current_academy_id()
        invoice = await db["invoices"].find_one(
            {
                "academy_id": request_academy_id,
                "$or": [{"invoice_id": invoice_id}, {"invoice_number": invoice_id}],
            }
        )
        if invoice is not None:
            inv_id = str(invoice.get("invoice_id") or invoice_id)
            lines = [
                _invoice_line_response(line)
                async for line in db["invoice_lines"].find(
                    {"academy_id": request_academy_id, "invoice_id": inv_id}
                )
            ]
            allocations = [
                {
                    "payment_id": str(row.get("payment_id", "")),
                    "amount_cents": int(row.get("amount_cents", 0)),
                }
                async for row in db["payment_allocations"].find(
                    {"academy_id": request_academy_id, "invoice_id": inv_id}
                )
            ]
            credit_usage = [
                {
                    "credit_id": str(row.get("credit_id", "")),
                    "amount_cents": int(row.get("amount_cents", 0)),
                }
                async for row in db["credit_applications"].find(
                    {"academy_id": request_academy_id, "invoice_id": inv_id}
                )
            ]
            total = int(invoice.get("total_cents", 0))
            due = int(invoice.get("balance_due_cents", 0))
            return {
                "invoice_id": inv_id,
                "invoice_number": str(invoice.get("invoice_number") or inv_id),
                "period": str(invoice.get("period") or ""),
                "lines": lines,
                "subtotal_cents": int(invoice.get("subtotal_cents", total)),
                "discount_cents": int(invoice.get("discount_cents", 0)),
                "total_cents": total,
                "balance_due_cents": due,
                "due_amount_cents": due,
                "paid_amount_cents": max(total - due, 0),
                "status": str(invoice.get("status", "open")),
                "allocations": allocations,
                "credit_usage": credit_usage,
                "invoice_pdf_artifact_id": invoice.get("invoice_pdf_artifact_id")
                or invoice.get("pdf_artifact_id"),
                "receipt_artifact_id": invoice.get("receipt_artifact_id"),
                "delivery_status": str(invoice.get("delivery_status") or "not_sent"),
                "sent_at": invoice.get("sent_at"),
                "last_sent_at": invoice.get("last_sent_at"),
            }

        payment = await db["payments"].find_one(
            {
                "academy_id": request_academy_id,
                "$or": [{"payment_id": invoice_id}, {"invoice_number": invoice_id}],
            }
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
                    "line_type": "tuition",
                    "quantity": 1,
                    "unit_amount_cents": int(
                        payment.get("gross_amount_cents") or row["amount_cents"]
                    ),
                    "source_type": "legacy_payment",
                    "source_id": str(row["payment_id"]),
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
        from backend.v2.contexts.billing.domain.errors import PaymentNotFound
        from backend.v2.shared.tenancy import current_academy_id

        request_academy_id = current_academy_id()
        owned_invoice = await db["invoices"].find_one(
            {
                "academy_id": request_academy_id,
                "$or": [{"invoice_id": invoice_id}, {"invoice_number": invoice_id}],
            },
            {"_id": 1},
        )
        owned_payment = await db["payments"].find_one(
            {
                "academy_id": request_academy_id,
                "$or": [{"payment_id": invoice_id}, {"invoice_number": invoice_id}],
            },
            {"_id": 1},
        )
        if owned_invoice is None and owned_payment is None:
            raise PaymentNotFound("invoice not found", payment_id=invoice_id)

        artifact_id = str(new_ulid())
        now = datetime.now(UTC)
        await db["billing_artifacts"].insert_one(
            {
                "academy_id": request_academy_id,
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
                "academy_id": request_academy_id,
                "$or": [{"invoice_id": invoice_id}, {"invoice_number": invoice_id}],
            },
            {"$set": {field: artifact_id, "updated_at": now}},
        )
        await db["payments"].update_one(
            {
                "academy_id": request_academy_id,
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
            from backend.v2.shared.tenancy import current_academy_id

            request_academy_id = current_academy_id()
            rows = await list_dues_followup()
            if parent_ids is not None:
                selected = set(parent_ids)
                rows = [row for row in rows if str(row["parent_id"]) in selected]
            generated = 0
            if generate_invoice_artifacts:
                for row in rows:
                    payment_cursor = (
                        db["payments"]
                        .find(
                            {
                                "academy_id": request_academy_id,
                                "status": {"$in": ["pending", "partially_paid"]},
                                "$or": [
                                    {"parent_id": row["parent_id"]},
                                    {"parent_user_id": row["parent_id"]},
                                ],
                                "is_deleted": {"$ne": True},
                            }
                        )
                        .sort([("created_at", -1)])
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
        from backend.v2.shared.tenancy import current_academy_id

        request_academy_id = current_academy_id()
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
                .find({"academy_id": request_academy_id})
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
            raise ValueError(f"unknown report export: {report_name}")
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
        process_scheduled_resume_actions=process_scheduled_resume_actions,
        issue_refund=issue_refund,
        quote_enrollment=quote_enrollment,
        preview_withdrawal_credit=preview_withdrawal_credit,
        approve_withdrawal_credit=approve_withdrawal_credit,
        list_payments_recent=list_payments_recent,
        list_billing_invoices=billing_ledger_repo.list_invoices_for_academy,
        get_billing_invoice_detail=get_billing_invoice_detail,
        generate_billing_invoice_artifact=generate_billing_invoice_artifact,
        send_billing_invoice=send_billing_invoice,
        charge_invoice_via_autopay=charge_invoice_via_autopay,
        add_invoice_line=add_invoice_line,
        remove_invoice_line=remove_invoice_line,
        void_billing_invoice=void_billing_invoice,
        record_manual_payment=record_manual_payment,
        create_student_invoice=create_student_invoice,
        list_billing_products=list_billing_products,
        create_billing_product=create_billing_product,
        update_billing_product=update_billing_product,
        deactivate_billing_product=deactivate_billing_product,
        generate_monthly_payments=generate_monthly_payments,
        mark_payment_paid=mark_payment_paid,
        apply_payment_discount=apply_payment_discount,
        undo_payment_paid=undo_payment_paid,
        reconcile_stripe_billing=reconcile_stripe_billing,
        record_expense=record_expense,
        edit_expense=edit_expense,
        delete_expense=delete_expense,
        expenses=expenses_repo,
        payouts=payouts_repo,
        revenue_query=revenue_query,
        payout_periods=payout_periods_repo,
        list_monthly_payroll=ListMonthlyPayroll(
            reader=_MonthlyCoachOccurrenceReaderAdapter(db["session_occurrences"]),
            periods=payout_periods_repo,
            calculator=coach_payout_calculator,
        ),
        bulk_generate_payroll=BulkGeneratePayroll(
            reader=_MonthlyCoachOccurrenceReaderAdapter(db["session_occurrences"]),
            periods=payout_periods_repo,
            generate=generate_payout_period,
        ),
        bulk_recompute_payroll=BulkRecomputePayroll(
            periods=payout_periods_repo,
            recompute=recompute_payout_period,
        ),
        generate_payout_period=generate_payout_period,
        approve_payout_period=approve_payout_period,
        mark_payout_paid=mark_payout_paid,
        recompute_payout_period=recompute_payout_period,
        reopen_payout_period=reopen_payout_period,
        override_payout_line=override_payout_line,
        list_payout_audit_entries=list_payout_audit_entries,
        describe_payout_occurrences=_describe_payout_occurrences,
        set_coach_pay_rate=set_coach_pay_rate,
        list_coach_pay_rates=list_coach_pay_rates,
        list_admin_sessions=list_admin_sessions,
        get_admin_session=get_admin_session,
        maintain_session_occurrences=maintain_session_occurrences,
        list_session_occurrences=list_session_occurrences,
        get_session_occurrence=occurrences_r.get,
        generate_daily_teaching_plan=generate_daily_teaching_plan,
        get_coach_engagement_stats=get_coach_engagement_stats,
        update_session_occurrence_coach=update_session_occurrence_coach,
        add_session_replacement=add_session_replacement,
        update_session_occurrence_replacement=update_session_occurrence_replacement,
        mark_coach_attendance=mark_coach_attendance,
        list_admin_enrollments_for_session=list_admin_enrollments_for_session,
        list_waitlist_for_session=list_waitlist_for_session,
        list_audit_logs=list_audit_logs,
        list_dues_followup=list_dues_followup,
        send_dues_reminders=send_dues_reminders,
        export_report_csv=export_report_csv,
        get_reports_kpis=_make_reports_kpis(db),
        list_enrollment_events=_make_list_enrollment_events(db),
        comms=comms,
        send_campaign=send_campaign,
        list_admin_waivers=list_admin_waivers,
        admin_registration_review=admin_registration_review,
        manage_admin_waiver_templates=manage_admin_waiver_templates,
        get_academy_use_case=get_academy_use_case,
        update_academy_use_case=update_academy_use_case,
        get_academy_fees_use_case=get_academy_fees_use_case,
        update_academy_fees_use_case=update_academy_fees_use_case,
        get_academy_notifications_use_case=get_academy_notifications_use_case,
        update_academy_notifications_use_case=update_academy_notifications_use_case,
        send_coach_digest_test=compose_send_coach_digest_test(db),
        get_digest_delivery_log=compose_get_digest_delivery_log(db),
        get_academy_gateway_use_case=get_academy_gateway_use_case,
        start_stripe_connect_use_case=start_stripe_connect_use_case,
        complete_stripe_connect_use_case=complete_stripe_connect_use_case,
        disconnect_stripe_use_case=disconnect_stripe_use_case,
        change_user_role=change_user_role,
        get_admin_user=get_admin_user,
        update_admin_user=update_admin_user,
        create_admin_user=create_admin_user,
        get_admin_student=get_admin_student,
        update_admin_student=update_admin_student,
        change_admin_student_parent=change_admin_student_parent,
        create_session_type=create_session_type,
        list_session_types=list_session_types,
        update_session_type=update_session_type,
        soft_delete_session_type=soft_delete_session_type,
        list_student_billing_enrollments=list_student_billing_enrollments,
        move_student_session_type=move_student_session_type,
        override_student_price=override_student_price,
        list_blocked_scheduled_resume_actions=lambda: scheduled_actions.list_by_status(
            "blocked_capacity",
            limit=100,
        ),
    )
    admin.get_reports_dashboard = _make_reports_dashboard(db)  # type: ignore[attr-defined]

    # Analytics use cases (Phase 2) are request-tenant scoped. These are
    # closures rather than long-lived use case instances because the use case
    # constructors take academy_id.
    async def get_enrollment_funnel(period: str | None = None):
        from backend.v2.shared.tenancy import current_academy_id

        return await GetEnrollmentFunnel(
            application_reader=MongoApplicationFunnelReader(db),
            academy_id=current_academy_id(),
        ).execute(period)

    async def get_attendance_trends(periods: list[str]):
        from backend.v2.shared.tenancy import current_academy_id

        return await GetAttendanceTrends(
            snapshot_repo=MongoAttendanceSnapshotReader(db),
            academy_id=current_academy_id(),
        ).execute(periods)

    async def get_coach_utilization(periods: list[str]):
        from backend.v2.shared.tenancy import current_academy_id

        return await GetCoachUtilization(
            snapshot_repo=MongoCoachPayoutSnapshotReader(db),
            academy_id=current_academy_id(),
        ).execute(periods)

    admin.get_enrollment_funnel = get_enrollment_funnel  # type: ignore[attr-defined]
    admin.get_attendance_trends = get_attendance_trends  # type: ignore[attr-defined]
    admin.get_coach_utilization = get_coach_utilization  # type: ignore[attr-defined]

    admin.curriculum = curriculum  # type: ignore[attr-defined]
    admin.student_progress = student_progress  # type: ignore[attr-defined]

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


class _SessionTypeChangedEventSink:
    def __init__(self, outbox: Outbox) -> None:
        self._outbox = outbox

    async def record_session_type_changed(
        self,
        *,
        academy_id: str,
        enrollment_id: str,
        student_id: str,
        parent_id: str,
        from_session_type_id: str | None,
        to_session_type_id: str,
        net_cents: int,
        actor_id: str,
        reason: str | None,
    ) -> None:
        await self._outbox.append(
            StudentSessionTypeChanged(
                aggregate_id=enrollment_id,
                academy_id=academy_id,
                payload=StudentSessionTypeChangedPayload(
                    enrollment_id=enrollment_id,
                    student_id=student_id,
                    parent_id=parent_id,
                    from_session_type_id=from_session_type_id,
                    to_session_type_id=to_session_type_id,
                    net_cents=net_cents,
                    actor_id=actor_id,
                    reason=reason,
                ),
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
