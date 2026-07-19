"""Admin BFF dependencies — heavy composition surface."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from fastapi import Request

from backend.v2.composition.admin_registration_review import (
    AdminRegistrationReview,
)
from backend.v2.composition.pathway import CurriculumComposition, StudentProgressComposition
from backend.v2.contexts.billing.application.use_cases.admin_payment_ops import (
    ApplyPaymentDiscount,
    GenerateMonthlyPayments,
    MarkPaymentPaid,
    SendDuesReminders,
    UndoPaymentPaid,
)
from backend.v2.contexts.billing.application.use_cases.billing_setup_registration import (
    ListBillingSetup,
)
from backend.v2.contexts.billing.application.use_cases.connect_onboarding import (
    StartConnectOnboarding,
)
from backend.v2.contexts.billing.application.use_cases.finance import (  # FINANCE
    DeleteExpense,
    EditExpense,
    MongoExpenseRepository,
    MongoPayoutRepository,
    RecordExpense,
)
from backend.v2.contexts.billing.application.use_cases.issue_refund import IssueRefund
from backend.v2.contexts.billing.application.use_cases.send_add_card_reminder import (
    SendAddCardReminder,
)
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
from backend.v2.contexts.coaching.application.use_cases.generate_daily_teaching_plan import (
    GenerateDailyTeachingPlan,
)
from backend.v2.contexts.communications.application.use_cases.send_campaign import (
    SendCampaign,
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
    OverrideEnrollmentFee,
    PauseEnrollment,
    RemoveFromWaitlist,
    ResumeEnrollment,
    SkipFromWaitlist,
    TransferEnrollment,
    WithdrawEnrollment,
)
from backend.v2.contexts.enrollment.application.use_cases.makeup_requests import (
    ApproveMakeupRequest,
    DenyMakeupRequest,
    ExpireMakeupRequests,
    ListAbsencesForAdmin,
    ListMakeupRequestsForAdmin,
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
from backend.v2.contexts.enrollment.application.use_cases.self_cancel import (
    ListSelfCancellationsForAdmin,
)
from backend.v2.contexts.enrollment.application.use_cases.self_service_policies import (
    GetSelfServicePolicy,
    UpdateSelfServicePolicy,
)
from backend.v2.contexts.enrollment.application.use_cases.trial_requests import (
    ApproveTrialRequest,
    DenyTrialRequest,
    ListTrialRequestsForAdmin,
)
from backend.v2.contexts.finance.application.ports import PayoutPeriodRepository
from backend.v2.contexts.finance.application.use_cases.approve_payout_period import (
    ApprovePayoutPeriod,
    MarkPayoutPaid,
)
from backend.v2.contexts.finance.application.use_cases.bulk_payroll import (
    BulkGeneratePayroll,
    BulkRecomputePayroll,
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
from backend.v2.contexts.identity.application.use_cases.manage_user_roles import (
    AddUserRole,
    RemoveUserRole,
)
from backend.v2.contexts.identity.application.use_cases.send_login_invite import (
    SendLoginInvite,
)
from backend.v2.contexts.identity.application.use_cases.stripe_connect import (
    CompleteStripeConnectUseCase,
    DisconnectStripeUseCase,
    StartStripeConnectUseCase,
)
from backend.v2.contexts.onboarding.application.use_cases.admin_waiver_templates import (
    ManageAdminWaiverTemplates,
)
from backend.v2.contexts.onboarding.application.use_cases.admin_waivers import (
    ListAdminWaivers,
)
from backend.v2.contexts.student_progress.application.use_cases.get_coach_engagement_stats import (
    GetCoachEngagementStats,
)
from backend.v2.shared.comms import CommsService


class AdminRevenueQuery(Protocol):
    async def execute(self, parent_id_filter: str | None = None) -> dict[str, int]: ...


@dataclass
class AdminUseCases:
    # directory
    list_admin_users: ListAdminUsers
    list_admin_students: ListAdminStudents
    # billing setup (Stripe registration status + invite/charge/autopay)
    list_billing_setup: ListBillingSetup
    send_add_card_reminder: SendAddCardReminder
    charge_billing_setup_balance: object
    enable_billing_setup_autopay: object
    record_billing_setup_invite: object
    # sessions / roster
    create_session: CreateSession
    edit_session: EditSession
    cancel_session: CancelSession
    edit_roster_add: EditRosterAdd
    cancel_enrollment: CancelEnrollment
    transfer_enrollment: TransferEnrollment
    override_enrollment_fee: OverrideEnrollmentFee
    pause_enrollment: PauseEnrollment
    resume_enrollment: ResumeEnrollment
    withdraw_enrollment: WithdrawEnrollment
    # waitlist
    join_waitlist: JoinWaitlist
    promote_from_waitlist: PromoteFromWaitlist
    skip_from_waitlist: SkipFromWaitlist
    remove_from_waitlist: RemoveFromWaitlist
    # pause requests
    list_admin_pause_requests: ListAdminPauseRequests
    approve_pause_request: ApprovePauseRequest
    decline_pause_request: DeclinePauseRequest
    # billing
    issue_refund: IssueRefund
    quote_enrollment: object  # callable
    preview_withdrawal_credit: PreviewWithdrawalCredit
    approve_withdrawal_credit: ApproveWithdrawalCredit
    list_payments_recent: object  # callable
    list_billing_invoices: object  # async (limit: int = 100) -> list[dict]
    get_billing_invoice_detail: object  # async (invoice_id: str) -> dict
    generate_billing_invoice_artifact: object  # async (invoice_id: str, artifact_type: str) -> dict
    generate_monthly_payments: GenerateMonthlyPayments
    mark_payment_paid: MarkPaymentPaid
    apply_payment_discount: ApplyPaymentDiscount
    undo_payment_paid: UndoPaymentPaid
    # finance (# FINANCE)
    record_expense: RecordExpense
    edit_expense: EditExpense
    delete_expense: DeleteExpense
    expenses: MongoExpenseRepository
    payouts: MongoPayoutRepository
    revenue_query: AdminRevenueQuery
    # reads
    list_admin_sessions: object  # callable
    list_session_occurrences: object  # async (session_id: str) -> list[dict]
    update_session_occurrence_coach: object  # async (...) -> dict | None
    mark_coach_attendance: object  # MarkCoachAttendance
    list_admin_enrollments_for_session: object  # callable
    list_waitlist_for_session: object  # callable
    list_audit_logs: object  # callable
    list_dues_followup: object  # callable
    send_dues_reminders: SendDuesReminders
    export_report_csv: object  # callable
    get_reports_kpis: object  # async () -> dict[str, int | float]
    list_enrollment_events: object  # async (enrollment_id: str) -> list[dict]
    list_billing_deferral_warnings: object  # async (*, today: date, limit: int)
    # comms
    comms: CommsService
    # waivers
    list_admin_waivers: ListAdminWaivers
    # settings
    get_academy_use_case: GetAcademyUseCase
    update_academy_use_case: UpdateAcademyUseCase
    get_academy_fees_use_case: GetAcademyFeesUseCase
    update_academy_fees_use_case: UpdateAcademyFeesUseCase
    get_academy_notifications_use_case: GetAcademyNotificationsUseCase
    update_academy_notifications_use_case: UpdateAcademyNotificationsUseCase
    get_academy_gateway_use_case: GetAcademyGatewayUseCase
    change_user_role: ChangeUserRole
    # recurring tuition discounts (#244)
    set_tuition_discount: object | None = None  # SetTuitionDiscount
    remove_tuition_discount: object | None = None  # RemoveTuitionDiscount
    tuition_discounts: object | None = None  # MongoTuitionDiscountRepository
    tuition_discount_summary: object | None = None  # MongoTuitionDiscountSummaryQuery
    reconcile_stripe_billing: object | None = None  # callable
    get_billing_reconciliation_report: object | None = None  # callable
    list_billing_webhook_events: object | None = None  # callable
    get_admin_user: GetAdminUser | None = None
    update_admin_user: UpdateAdminUser | None = None
    create_admin_user: CreateAdminUser | None = None
    send_login_invite: SendLoginInvite | None = None
    add_user_role: AddUserRole | None = None
    remove_user_role: RemoveUserRole | None = None
    get_admin_student: GetAdminStudent | None = None
    update_admin_student: UpdateAdminStudent | None = None
    change_admin_student_parent: ChangeAdminStudentParent | None = None
    get_admin_session: object | None = None  # async (session_id: str) -> dict | None
    maintain_session_occurrences: object | None = None  # async (session) -> None
    add_session_replacement: object | None = None  # async (...) -> dict | None
    update_session_occurrence_replacement: object | None = None  # async (...) -> dict | None
    manage_admin_waiver_templates: ManageAdminWaiverTemplates | None = None
    admin_registration_review: AdminRegistrationReview | None = None
    payout_periods: PayoutPeriodRepository | None = None
    list_monthly_payroll: ListMonthlyPayroll | None = None
    bulk_generate_payroll: BulkGeneratePayroll | None = None
    bulk_recompute_payroll: BulkRecomputePayroll | None = None
    generate_payout_period: GeneratePayoutPeriod | None = None
    approve_payout_period: ApprovePayoutPeriod | None = None
    mark_payout_paid: MarkPayoutPaid | None = None
    recompute_payout_period: RecomputePayoutPeriod | None = None
    reopen_payout_period: ReopenPayoutPeriod | None = None
    override_payout_line: OverridePayoutLine | None = None
    list_payout_audit_entries: ListPayoutAuditEntries | None = None
    describe_payout_occurrences: object | None = None  # async (ids) -> dict[str, dict]
    set_coach_pay_rate: object | None = None  # SetCoachPayRate
    list_coach_pay_rates: object | None = None  # ListCoachPayRates
    repair_coach_pay_rate_window: object | None = None  # RepairCoachRateWindow
    create_session_type: CreateSessionType | None = None
    list_session_types: ListSessionTypes | None = None
    update_session_type: UpdateSessionType | None = None
    soft_delete_session_type: SoftDeleteSessionType | None = None
    list_student_billing_enrollments: ListStudentBillingEnrollments | None = None
    move_student_session_type: MoveStudentSessionType | None = None
    override_student_price: OverrideStudentPrice | None = None
    process_scheduled_resume_actions: ProcessScheduledResumeActions | None = None
    list_blocked_scheduled_resume_actions: object | None = None
    get_enrollment_funnel: object | None = (
        None  # async (period: str | None) -> EnrollmentFunnelResult
    )
    get_attendance_trends: object | None = (
        None  # async (periods: list[str]) -> AttendanceTrendsResult
    )
    get_coach_utilization: object | None = (
        None  # async (periods: list[str]) -> CoachUtilizationResult
    )
    get_session_economics: object | None = None  # async (period: str) -> dict[str, Any]
    get_projected_income: object | None = None  # async (period: str) -> dict[str, Any]
    # financial reports (payment visibility phase 3)
    get_refunds_report: object | None = None  # async (period: str) -> dict[str, Any]
    get_revenue_by_category_report: object | None = None  # async (period: str) -> dict[str, Any]
    get_deposit_slip_report: object | None = None  # async (period: str) -> dict[str, Any]
    curriculum: CurriculumComposition | None = None
    student_progress: StudentProgressComposition | None = None
    generate_daily_teaching_plan: GenerateDailyTeachingPlan | None = None
    get_session_occurrence: object | None = None  # async (occurrence_id: str) -> occurrence | None
    get_coach_engagement_stats: GetCoachEngagementStats | None = None
    send_campaign: SendCampaign | None = None
    start_stripe_connect_use_case: StartStripeConnectUseCase | None = None
    complete_stripe_connect_use_case: CompleteStripeConnectUseCase | None = None
    disconnect_stripe_use_case: DisconnectStripeUseCase | None = None
    # Accounts-v2 Connect onboarding (Slice I) — supersedes the legacy OAuth
    # trio above for actually unblocking billing; see academy_routes.py.
    start_connect_onboarding_use_case: StartConnectOnboarding | None = None
    # Coach teaching-plan digest: test-send + delivery log (Stream 2 C/D).
    send_coach_digest_test: object | None = None  # SendCoachDigestTest
    get_digest_delivery_log: object | None = None  # GetDigestDeliveryLog
    send_billing_invoice: object | None = None
    charge_invoice_via_autopay: object | None = None
    # Billing Health (#235): observability + recovery actions.
    list_reconciliation_runs: object | None = None  # async () -> list[dict]
    run_reconciliation: object | None = None  # async () -> dict
    list_failed_payment_attempts: object | None = None  # async () -> list[dict]
    list_invoice_attempts: object | None = None  # async (invoice_id) -> list[dict]
    list_dunning_failures: object | None = None  # async () -> list[dict]
    process_dunning_retries: object | None = None  # ProcessDunningRetries
    replay_webhook_event: object | None = None  # async (event_id) -> bool
    # Legacy invoice ↔ Stripe charge review queue (#242 WI-3).
    list_legacy_match_queue: object | None = None  # async () -> list[dict]
    confirm_legacy_match: object | None = None  # async (**kwargs) -> dict
    # Payment visibility (Phase 1): filtered list, money-received feed, last payment per family.
    list_payments_filtered: object | None = None  # async (**filters) -> dict
    list_payment_feed: object | None = None  # async (limit: int) -> list[dict]
    list_last_payment_by_family: object | None = None  # async () -> list[dict]
    add_invoice_line: object | None = None
    remove_invoice_line: object | None = None
    void_billing_invoice: object | None = None
    record_manual_payment: object | None = None
    issue_invoice_refund: object | None = None
    list_billing_audit: object | None = None
    create_student_invoice: object | None = None
    list_billing_products: object | None = None
    create_billing_product: object | None = None
    update_billing_product: object | None = None
    deactivate_billing_product: object | None = None
    # Parent self-service policy (#absence/makeup/cancel Slice 1)
    self_service_policy: GetSelfServicePolicy | None = None
    update_self_service_policy: UpdateSelfServicePolicy | None = None
    # Admin makeup review + absence queue (R2, Task 5)
    list_makeup_requests_for_admin: ListMakeupRequestsForAdmin | None = None
    approve_makeup_request: ApproveMakeupRequest | None = None
    deny_makeup_request: DenyMakeupRequest | None = None
    list_absences_for_admin: ListAbsencesForAdmin | None = None
    # Makeup expiry job (R2, Task 6)
    expire_makeup_requests: ExpireMakeupRequests | None = None
    # Trial requests + conversion tracking (R3, Task 7)
    list_trial_requests_for_admin: ListTrialRequestsForAdmin | None = None
    approve_trial_request: ApproveTrialRequest | None = None
    deny_trial_request: DenyTrialRequest | None = None
    # Self-cancel audit list (R4, Task 8)
    list_self_cancellations_for_admin: ListSelfCancellationsForAdmin | None = None
    # Platform-charge fallback escape hatch (2026-07-04 incident follow-up):
    # audited admin toggle for billing_settings.allow_platform_charge_fallback.
    get_platform_charge_fallback: object | None = None  # GetPlatformChargeFallback
    set_platform_charge_fallback: object | None = None  # SetPlatformChargeFallback


def get_admin_use_cases(request: Request) -> AdminUseCases:
    return request.app.state.admin  # type: ignore[no-any-return]
