"""Parent BFF dependencies."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from backend.v2.composition.pathway import StudentProgressComposition
from backend.v2.contexts.billing.application.use_cases.handle_webhook_event import (
    HandleWebhookEvent,
)
from backend.v2.contexts.billing.application.use_cases.start_checkout import StartCheckout
from backend.v2.contexts.enrollment.application.use_cases.list_parent_available_sessions import (
    ListParentAvailableSessions,
)
from backend.v2.contexts.enrollment.application.use_cases.pause_requests import (
    ListParentPauseRequests,
    RequestEnrollmentPause,
)
from backend.v2.contexts.onboarding.application.use_cases.manage_application import (
    GetApplicationStatus,
    PatchApplication,
    StartApplication,
    TransitionApplication,
)
from backend.v2.contexts.onboarding.application.use_cases.parent_student_waivers import (
    AcceptParentWaiver,
    GetParentWaiverRequirement,
)


@dataclass
class ParentUseCases:
    start_application: StartApplication
    patch_application: PatchApplication
    get_application_status: GetApplicationStatus
    transition_application: TransitionApplication
    start_checkout: StartCheckout
    quote_enrollment: object  # callable
    start_checkout_for_application: object  # callable
    start_autopay_for_enrollment: object  # callable
    open_billing_portal: object  # callable
    get_checkout_status: object  # callable
    handle_webhook_event: HandleWebhookEvent
    list_available_sessions: ListParentAvailableSessions
    list_payments_for_parent: object  # bound to a callable in composition; opaque to routes
    list_credits_for_parent: object  # callable
    list_children_for_parent: object  # callable
    list_enrollments_for_parent: object  # callable
    request_enrollment_pause: RequestEnrollmentPause
    list_parent_pause_requests: ListParentPauseRequests
    list_attendance_for_parent: object  # callable
    list_progress_for_parent: object  # callable
    list_invoices_for_parent: object  # callable
    get_invoice_for_parent: object  # callable
    get_child_schedule: object  # callable
    enroll_child: object  # callable — EnrollChildInSessionType.execute
    cancel_billing_enrollment: object  # callable — CancelBillingEnrollment.execute
    get_parent_waiver_requirement: GetParentWaiverRequirement
    accept_parent_waiver: AcceptParentWaiver
    get_academy_info: object  # callable accepting academy_id
    # Optional so existing ParentUseCases constructions (and tests) that predate
    # the skill pathway keep working. Real parent composition always sets it;
    # the skill routes are the only consumers.
    student_progress: StudentProgressComposition | None = None


def get_parent_use_cases(request: Request) -> ParentUseCases:
    return request.app.state.parent  # type: ignore[no-any-return]
