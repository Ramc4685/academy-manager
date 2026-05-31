"""Admin BFF dependencies — heavy composition surface."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from backend.v2.composition.admin_registration_review import (
    AdminRegistrationReview,
)
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
from backend.v2.contexts.enrollment.application.use_cases.pause_requests import (
    ApprovePauseRequest,
    DeclinePauseRequest,
    ListAdminPauseRequests,
)
from backend.v2.contexts.enrollment.application.use_cases.promote_from_waitlist import (
    PromoteFromWaitlist,
)
from backend.v2.contexts.finance.application.use_cases.approve_payout_period import (
    ApprovePayoutPeriod,
    MarkPayoutPaid,
)
from backend.v2.contexts.finance.application.use_cases.generate_payout_period import (
    GeneratePayoutPeriod,
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
from backend.v2.contexts.onboarding.application.use_cases.admin_waiver_templates import (
    ManageAdminWaiverTemplates,
)
from backend.v2.contexts.onboarding.application.use_cases.admin_waivers import (
    ListAdminWaivers,
)
from backend.v2.shared.comms import CommsService


@dataclass
class AdminUseCases:
    # directory
    list_admin_users: ListAdminUsers
    list_admin_students: ListAdminStudents
    # sessions / roster
    create_session: CreateSession
    edit_session: EditSession
    cancel_session: CancelSession
    edit_roster_add: EditRosterAdd
    cancel_enrollment: CancelEnrollment
    transfer_enrollment: TransferEnrollment
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
    revenue_query: AcademyRevenueQuery
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
    get_admin_user: GetAdminUser | None = None
    update_admin_user: UpdateAdminUser | None = None
    create_admin_user: CreateAdminUser | None = None
    get_admin_student: GetAdminStudent | None = None
    update_admin_student: UpdateAdminStudent | None = None
    change_admin_student_parent: ChangeAdminStudentParent | None = None
    manage_admin_waiver_templates: ManageAdminWaiverTemplates | None = None
    admin_registration_review: AdminRegistrationReview | None = None
    payout_periods: object | None = None
    generate_payout_period: GeneratePayoutPeriod | None = None
    approve_payout_period: ApprovePayoutPeriod | None = None
    mark_payout_paid: MarkPayoutPaid | None = None
    create_session_type: CreateSessionType | None = None
    list_session_types: ListSessionTypes | None = None
    update_session_type: UpdateSessionType | None = None
    soft_delete_session_type: SoftDeleteSessionType | None = None
    list_student_billing_enrollments: ListStudentBillingEnrollments | None = None
    move_student_session_type: MoveStudentSessionType | None = None
    override_student_price: OverrideStudentPrice | None = None


def get_admin_use_cases(request: Request) -> AdminUseCases:
    return request.app.state.admin  # type: ignore[no-any-return]
