"""Compose the Parent BFF use cases."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Protocol, TypeVar
from zoneinfo import ZoneInfo

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import OperationFailure

from backend.v2.composition.pathway import (
    CurriculumComposition,
    StudentProgressComposition,
    compose_curriculum,
    compose_student_progress,
)
from backend.v2.composition.roster_notifications import compose_roster_notifier
from backend.v2.contexts.billing.application.ports import (
    StripeCheckoutSessionNotExpirable,
    StripeGateway,
)
from backend.v2.contexts.billing.application.use_cases.add_invoice_line import (
    AddInvoiceLine,
    AddInvoiceLineCommand,
)
from backend.v2.contexts.billing.application.use_cases.enroll_child_in_session_type import (
    CancelBillingEnrollment,
    EnrollChildInSessionType,
)
from backend.v2.contexts.billing.application.use_cases.handle_webhook_event import (
    HandleWebhookEvent,
)
from backend.v2.contexts.billing.application.use_cases.issue_refund import IssueRefund
from backend.v2.contexts.billing.application.use_cases.parent_billing import (
    AutopayConsentCaptureContext,
    CreateCustomerPortalSession,
    CreateCustomerPortalSessionCommand,
    GetCheckoutStatus,
    StartSubscriptionCheckout,
    StartSubscriptionCheckoutCommand,
    _success_url_with_checkout_session_placeholder,
)
from backend.v2.contexts.billing.application.use_cases.quote_enrollment import (
    QuoteEnrollment,
    QuoteEnrollmentCommand,
)
from backend.v2.contexts.billing.application.use_cases.record_checkout_mint_failure import (
    CHECKOUT_FAILURE_ACCOUNT_NOT_READY,
    CHECKOUT_FAILURE_STRIPE_ERROR,
    record_checkout_mint_failure,
)
from backend.v2.contexts.billing.application.use_cases.send_invoice import SendInvoice
from backend.v2.contexts.billing.application.use_cases.start_checkout import (
    StartCheckout,
    StartCheckoutCommand,
    StartCheckoutResult,
)
from backend.v2.contexts.billing.domain.errors import InvoicePayLinkUnavailable, QuoteExpired
from backend.v2.contexts.billing.domain.ledger import InvoiceLine
from backend.v2.contexts.billing.infrastructure.mongo_autopay_consent_repo import (
    MongoAutopayConsentRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_counter_repo import (
    MongoBillingCounterRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_ledger_repo import (
    MongoBillingLedgerRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_settings_repo import (
    MongoBillingSettingsRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_connected_account_repo import (
    MongoConnectedAccountRepository,
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
from backend.v2.contexts.billing.infrastructure.mongo_session_type_repo import (
    MongoSessionTypeRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_stripe_dedup import (
    MongoStripeEventDedup,
)
from backend.v2.contexts.billing.infrastructure.mongo_stripe_invoice_processing_repo import (
    MongoStripeInvoiceProcessingRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_student_billing_enrollment_repo import (
    MongoStudentBillingEnrollmentRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_subscription_repo import (
    MongoSubscriptionRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_unretired_checkout_repo import (
    MongoUnretiredCheckoutSessionRepository,
)
from backend.v2.contexts.enrollment.application.use_cases.absence_notices import (
    ListParentAbsences,
    SubmitAbsenceNotice,
)
from backend.v2.contexts.enrollment.application.use_cases.admin_directory import (
    UpdateAdminStudentCommand,
)
from backend.v2.contexts.enrollment.application.use_cases.confirm_enrollment import (
    ConfirmEnrollment,
)
from backend.v2.contexts.enrollment.application.use_cases.get_child_schedule import (
    GetChildSchedule,
)
from backend.v2.contexts.enrollment.application.use_cases.list_parent_available_sessions import (
    ListParentAvailableSessions,
)
from backend.v2.contexts.enrollment.application.use_cases.makeup_requests import (
    ListEligibleMakeupTargets,
    ListParentMakeups,
    SubmitMakeupRequest,
)
from backend.v2.contexts.enrollment.application.use_cases.pause_requests import (
    ListParentPauseRequests,
    RequestEnrollmentPause,
)
from backend.v2.contexts.enrollment.application.use_cases.promote_from_waitlist import (
    PromoteFromWaitlist,
)
from backend.v2.contexts.enrollment.application.use_cases.self_cancel import (
    PreviewSelfCancel,
    SelfCancelBillingPort,
    SelfCancelEnrollment,
)
from backend.v2.contexts.enrollment.application.use_cases.trial_requests import (
    ListParentTrialRequests,
    SubmitTrialRequest,
)
from backend.v2.contexts.enrollment.domain.errors import SessionNotFound
from backend.v2.contexts.enrollment.infrastructure.mongo_absence_notice_repo import (
    MongoAbsenceNoticeRepository,
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
from backend.v2.contexts.enrollment.infrastructure.mongo_makeup_request_repo import (
    MongoMakeupRequestRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_occurrence_repo import (
    MongoSessionOccurrenceRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_occurrence_roster_repo import (
    MongoOccurrenceRosterRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_pause_request_repo import (
    MongoPauseRequestRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_self_service_policy_repo import (
    MongoSelfServicePolicyRepository,
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
from backend.v2.contexts.enrollment.infrastructure.mongo_trial_request_repo import (
    MongoTrialRequestRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_waitlist_repo import (
    MongoWaitlistRepository,
)
from backend.v2.contexts.identity.application.use_cases.admin_directory import (
    UpdateAdminUserCommand,
)
from backend.v2.contexts.identity.infrastructure.mongo_user_repo import MongoUserRepository
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
from backend.v2.contexts.onboarding.domain.errors import (
    ApplicationNotEditable,
    IncompleteApplication,
    MissingSelectedSession,
)
from backend.v2.contexts.onboarding.infrastructure.mongo_application_repo import (
    MongoApplicationRepository,
)
from backend.v2.contexts.onboarding.infrastructure.mongo_parent_waiver_repo import (
    MongoParentWaiverRepository,
)
from backend.v2.contexts.onboarding.infrastructure.mongo_registration_waiver_repo import (
    MongoRegistrationWaiverRepository,
)
from backend.v2.shared.comms import Message, MongoMessageRepository
from backend.v2.shared.config import get_settings
from backend.v2.shared.events import Outbox
from backend.v2.shared.idempotency import IdempotencyStore
from backend.v2.shared.profile.completeness import (
    MEDICAL_NONE_SENTINEL,
    ChildFacts,
    ParentFacts,
    evaluate,
)
from backend.v2.shared.security.redirect import InvalidRedirectUrl, validate_redirect_url
from backend.v2.shared.tenancy import (
    TenantContextUnset,
    current_academy_id,
    current_tenant_origins,
    tenant_scope,
)

from .event_handlers import HandlerDeps, install_handlers

T = TypeVar("T")
log = logging.getLogger(__name__)


@dataclass
class ParentComposition:
    start_application: StartApplication
    patch_application: PatchApplication
    get_application_status: GetApplicationStatus
    transition_application: TransitionApplication
    start_checkout: StartCheckout
    quote_enrollment: object
    start_checkout_for_application: object
    start_autopay_for_enrollment: object
    open_billing_portal: object
    get_checkout_status: object
    handle_webhook_event: HandleWebhookEvent
    list_available_sessions: ListParentAvailableSessions
    list_payments_for_parent: object  # callable
    list_credits_for_parent: object
    list_children_for_parent: object
    list_enrollments_for_parent: object
    request_enrollment_pause: RequestEnrollmentPause
    list_parent_pause_requests: ListParentPauseRequests
    submit_absence_notice: SubmitAbsenceNotice
    list_parent_absences: ListParentAbsences
    submit_makeup_request: SubmitMakeupRequest
    list_parent_makeups: ListParentMakeups
    list_eligible_makeup_targets: ListEligibleMakeupTargets
    submit_trial_request: SubmitTrialRequest
    list_parent_trial_requests: ListParentTrialRequests
    preview_self_cancel: PreviewSelfCancel
    self_cancel_enrollment: SelfCancelEnrollment
    list_attendance_for_parent: object
    list_progress_for_parent: object
    list_invoices_for_parent: object
    get_invoice_for_parent: object
    start_invoice_payment_for_parent: object
    start_balance_payment_for_parent: object
    get_child_schedule: object
    enroll_child: object
    cancel_billing_enrollment: object
    get_parent_waiver_requirement: GetParentWaiverRequirement
    accept_parent_waiver: AcceptParentWaiver
    get_academy_info: object  # callable accepting academy_id
    get_registration_waiver: object  # callable -> Waiver | None
    student_progress: StudentProgressComposition
    curriculum: CurriculumComposition
    # Self-service profile (issue #380)
    get_parent_profile: object  # callable
    update_parent_profile: object  # callable
    confirm_parent_email: object  # callable
    update_parent_child: object  # callable
    # Messages inbox (UIM13). Defaulted, so these must stay last: a dataclass
    # cannot place a non-default field after a defaulted one.
    list_messages: object = None  # Callable[[str], Awaitable[list[Message]]]
    mark_message_read: object = None  # Callable[[str, str], Awaitable[None]]


class _MongoTransactionRunner:
    def __init__(self, db: AsyncIOMotorDatabase[Any]) -> None:
        self._db = db

    async def run(self, work: Callable[[Any | None], Awaitable[T]]) -> T:
        try:
            session_context = await self._db.client.start_session()
        except (AttributeError, NotImplementedError):
            return await work(None)
        except OperationFailure as exc:
            if self._is_transaction_unavailable(exc):
                return await work(None)
            raise

        async with session_context as session:
            try:
                transaction_context = session.start_transaction()
            except (AttributeError, NotImplementedError):
                return await work(None)
            except OperationFailure as exc:
                if self._is_transaction_unavailable(exc):
                    return await work(None)
                raise
            try:
                async with transaction_context:
                    return await work(session)
            except OperationFailure as exc:
                if self._is_transaction_unavailable(exc):
                    # The transaction context manager already aborted the
                    # transaction on exception exit; work(None) must be safe
                    # to re-invoke since the standalone-Mongo failure occurs
                    # on the FIRST operation inside work, before any writes.
                    return await work(None)
                raise

    @staticmethod
    def _is_transaction_unavailable(exc: OperationFailure) -> bool:
        message = str(exc).lower()
        return ("transaction" in message or "session" in message) and (
            "not supported" in message
            or "replica set" in message
            or "mongos" in message
            or "transaction numbers are only allowed" in message
        )


class _StripeCheckoutAttemptRetirement:
    """Kills a checkout attempt an application no longer owns.

    Onboarding declares the need (``SupersededCheckoutRetirement``); the wiring
    lives here because expiring a Stripe Checkout Session and parking its
    pending Payment are both Billing concerns. Without this, a superseded
    session stays payable and one enrollment has two ways to be charged.

    Failures are deliberately swallowed: Stripe REJECTS expiring a session that
    is already complete or expired, which is exactly the "parent paid on the
    old tab" race. Raising there would unpick the resume/re-stamp we just
    committed and leave the application in a worse state than the one this
    call exists to prevent.
    """

    def __init__(
        self,
        *,
        stripe: StripeGateway,
        payments: Any,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        unretired: Any = None,
    ) -> None:
        self._stripe = stripe
        self._payments = payments
        self._now = clock
        # Worklist for sessions that stayed payable because Stripe could not be
        # reached. Optional so the older two-argument construction in tests
        # keeps working; when it is None the failure is still logged loudly.
        self._unretired = unretired

    async def retire_checkout_attempt(
        self, *, checkout_session_id: str | None, payment_id: str | None
    ) -> None:
        if checkout_session_id:
            await self._expire_session(checkout_session_id, payment_id)
        if not payment_id:
            return
        payment = await self._payments.get(payment_id)
        if payment is None or payment.status != "pending":
            # Already succeeded / failed / expired. Leave it exactly as it is —
            # parking a succeeded payment here would erase a real charge.
            return
        # Reuses the status the `checkout.session.expired` webhook writes, so
        # that webhook's own `status == "pending"` guard makes it a no-op when
        # the superseded session's expiry event lands later.
        await self._payments.save(
            payment.model_copy(update={"status": "expired", "updated_at": self._now()})
        )

    async def _expire_session(self, checkout_session_id: str, payment_id: str | None) -> None:
        # Resolved OUTSIDE the try on purpose: a gateway that does not
        # implement the port is a wiring bug and must blow up, not be filed
        # away as another benign "already paid" expiry failure.
        expire = self._stripe.expire_checkout_session
        try:
            await expire(checkout_session_id)
        except StripeCheckoutSessionNotExpirable as exc:
            # The ONLY benign failure: Stripe will not expire a session that is
            # already complete or expired, which is precisely the race this call
            # has to survive (the parent paid on the old tab). Nothing is left
            # payable, so INFO is honest here.
            log.info(
                "checkout retirement: session %s is already terminal at Stripe err=%s",
                checkout_session_id,
                exc,
            )
        except Exception as exc:
            # Everything else — connection dropped, timeout, 5xx, rate limit,
            # or an error type we do not recognise — leaves the session OPEN and
            # PAYABLE. Before #549 this shared the INFO log above and vanished.
            # It must not unpick the state the caller just committed, so it is
            # still swallowed, but it is recorded where a reconciliation pass
            # can find it and logged at a level that can page someone.
            log.warning(
                "checkout retirement: session %s could NOT be expired and may still be "
                "payable (payment %s) err=%s",
                checkout_session_id,
                payment_id,
                exc,
            )
            await self._record_unretired(checkout_session_id, payment_id, exc)
            return
        await self._clear_unretired(checkout_session_id)

    async def _record_unretired(
        self, checkout_session_id: str, payment_id: str | None, exc: Exception
    ) -> None:
        if self._unretired is None:
            return
        try:
            await self._unretired.record(
                checkout_session_id=checkout_session_id,
                payment_id=payment_id,
                reason=type(exc).__name__,
                error=str(exc),
                occurred_at=self._now(),
            )
        except Exception:
            # The worklist write is the last line of defence; if it fails there
            # is nothing further to fall back on, but it must not take down the
            # caller's already-committed state.
            log.exception(
                "checkout retirement: failed to record un-retired session %s",
                checkout_session_id,
            )

    async def _clear_unretired(self, checkout_session_id: str) -> None:
        if self._unretired is None:
            return
        try:
            await self._unretired.clear(checkout_session_id)
        except Exception:
            log.exception(
                "checkout retirement: failed to clear un-retired session %s",
                checkout_session_id,
            )


# Statuses a parent may start (or re-start) checkout from. DRAFT is the normal
# case, including after a cancel — the wizard's start call RESUMES an abandoned
# attempt back to DRAFT rather than minting a second application. CHECKOUT_PENDING
# survives here for the concurrent/retried POST: two tabs, or a client retry, on
# the SAME application. That path does not move the status, it re-points the
# application at the newer payment and retires the one it replaced. Every other
# status either has no legal outbound CHECKOUT_PENDING transition (see
# _TRANSITIONS in the onboarding manage_application use case) or is past payment.
_CHECKOUT_STARTABLE_STATUSES = frozenset({"DRAFT", "CHECKOUT_PENDING"})


def compose_parent_webhook_handler(
    db: AsyncIOMotorDatabase[Any],
    outbox: Outbox,
    stripe: StripeGateway,
    *,
    academy_id: str | None = None,
) -> HandleWebhookEvent:
    settings = get_settings()
    academy_id = _require_academy_id(academy_id)

    credits_repo = MongoCreditLedgerRepository(db)
    billing_ledger_repo = MongoBillingLedgerRepository(db)
    billing_counters_repo = MongoBillingCounterRepository(db)
    billing_settings_repo = MongoBillingSettingsRepository(db)
    payments_repo = MongoPaymentRepository(db, credit_ledger=credits_repo)
    subscriptions_repo = MongoSubscriptionRepository(db)
    parent_customers_repo = MongoParentBillingCustomerRepository(db)
    autopay_consents_repo = MongoAutopayConsentRepository(db)
    student_billing_enrollments = MongoStudentBillingEnrollmentRepository(db)
    connected_accounts_repo = MongoConnectedAccountRepository(db)
    dedup = MongoStripeEventDedup(db)
    invoice_processing = MongoStripeInvoiceProcessingRepository(db)
    transaction_runner = _MongoTransactionRunner(db)

    class _EnrollmentAutopayState:
        """Routes the webhook/legacy-convergence path through the SAME guarded
        per-enrollment autopay-status write that pause/resume use — the single
        source of truth on `student_billing_enrollments` (BLOCKING #1)."""

        async def set_autopay_state(
            self,
            *,
            enrollment_id: str,
            autopay_enrollment_status: str,
            session: Any | None = None,
        ) -> bool:
            return await student_billing_enrollments.set_autopay_enrollment_status(
                enrollment_id=enrollment_id,
                status=autopay_enrollment_status,  # type: ignore[arg-type]
                session=session,
            )

        async def mark_autopay_active_from_setup(
            self, *, enrollment_id: str, session: Any | None = None
        ) -> bool:
            return await student_billing_enrollments.mark_autopay_active_from_setup(
                enrollment_id=enrollment_id,
                session=session,
            )

    class _EnrollmentBillingIdentity:
        async def get_billing_identity(self, enrollment_id: str) -> dict[str, str | None] | None:
            enrollment = await db["enrollments"].find_one(
                {"academy_id": academy_id, "enrollment_id": enrollment_id}
            )
            if enrollment is None:
                return None
            return {
                "academy_id": academy_id,
                "parent_id": str(
                    enrollment.get("parent_id") or enrollment.get("parent_user_id") or ""
                ),
                "student_id": str(enrollment.get("student_id") or "") or None,
                "enrollment_id": enrollment_id,
                "session_id": str(enrollment.get("session_id") or "") or None,
            }

    return HandleWebhookEvent(
        stripe=stripe,
        dedup=dedup,
        payments=payments_repo,
        subscriptions=subscriptions_repo,
        billing_enrollments=student_billing_enrollments,
        billing_ledger=billing_ledger_repo,
        billing_counters=billing_counters_repo,
        billing_settings=billing_settings_repo,
        parent_customers=parent_customers_repo,
        enrollment_autopay=_EnrollmentAutopayState(),
        consent_repo=autopay_consents_repo,
        transaction_runner=transaction_runner,
        enrollment_identity=_EnrollmentBillingIdentity(),
        invoice_processing=invoice_processing,
        connected_accounts=_ConnectAccountResolver(connected_accounts_repo, academy_id),
        outbox=outbox,
        academy_id=academy_id,
        expected_livemode=True
        if settings.env == "prod"
        else False
        if settings.env == "test"
        else None,
    )


def compose_parent(
    db: AsyncIOMotorDatabase[Any],
    outbox: Outbox,
    idempotency_store: IdempotencyStore,
    stripe: StripeGateway,
    *,
    academy_id: str | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> ParentComposition:
    """`clock` is the seam the checkout-start path prices against.

    Every quote is "what is left of THIS month", so a test that leans on the
    wall clock silently changes shape as the month runs out (a session quoted
    at $0 skips Stripe entirely). Injecting it keeps those tests pinned instead
    of flaky in the last minutes of a month.
    """
    settings = get_settings()
    academy_id = _require_academy_id(academy_id)
    ensure_multi_academy_composable(settings)

    def request_academy_id() -> str:
        # Request-time tenant for use cases that stamp academy_id at execute
        # time. In multi-academy mode missing context is always a bug — fail
        # closed. The boot fallback only exists so single-academy non-HTTP
        # callers (outbox event handlers, schedulers) behave exactly as today.
        try:
            return current_academy_id()
        except TenantContextUnset:
            if settings.tenancy_mode == "multi_academy":
                raise
            return academy_id

    # Billing
    credits_repo = MongoCreditLedgerRepository(db)
    billing_ledger_repo = MongoBillingLedgerRepository(db)
    billing_counters_repo = MongoBillingCounterRepository(db)
    billing_settings_repo = MongoBillingSettingsRepository(db)
    # The composed clock must reach the payment repo: quotes are minted with
    # `clock` and consume() judges the snapshot TTL with the repo's clock, so
    # letting the repo default to the wall clock would make the two disagree
    # (a pinned test clock, for instance, would see every quote as expired).
    payments_repo = MongoPaymentRepository(db, credit_ledger=credits_repo, clock=clock)
    subscriptions_repo = MongoSubscriptionRepository(db)
    parent_customers_repo = MongoParentBillingCustomerRepository(db)
    autopay_consents_repo = MongoAutopayConsentRepository(db)
    student_billing_enrollments = MongoStudentBillingEnrollmentRepository(db)
    connected_accounts_repo = MongoConnectedAccountRepository(db)
    session_types_repo = MongoSessionTypeRepository(db)
    dedup = MongoStripeEventDedup(db)
    invoice_processing = MongoStripeInvoiceProcessingRepository(db)
    transaction_runner = _MongoTransactionRunner(db)

    # Request-time tenant (issue #532): checkout-path use cases stamp the
    # academy at execute time via request_academy_id, so a second academy's
    # parent can never mint payments stamped with the boot academy.
    start_checkout = StartCheckout(
        payment_repo=payments_repo,
        stripe=stripe,
        academy_id=request_academy_id,
        connected_accounts=connected_accounts_repo,
        settings=billing_settings_repo,
    )
    start_subscription_checkout = StartSubscriptionCheckout(
        subscriptions=subscriptions_repo,
        stripe=stripe,
        academy_id=request_academy_id,
        connected_accounts=connected_accounts_repo,
        settings=billing_settings_repo,
    )
    create_portal = CreateCustomerPortalSession(stripe=stripe)
    issue_refund = IssueRefund(
        payment_repo=payments_repo,
        stripe=stripe,
        outbox=outbox,
        idempotency_store=idempotency_store,
    )

    class _EnrollmentAutopayState:
        """Routes the webhook/legacy-convergence path through the SAME guarded
        per-enrollment autopay-status write that pause/resume use — the single
        source of truth on `student_billing_enrollments` (BLOCKING #1)."""

        async def set_autopay_state(
            self,
            *,
            enrollment_id: str,
            autopay_enrollment_status: str,
            session: Any | None = None,
        ) -> bool:
            return await student_billing_enrollments.set_autopay_enrollment_status(
                enrollment_id=enrollment_id,
                status=autopay_enrollment_status,  # type: ignore[arg-type]
                session=session,
            )

        async def mark_autopay_active_from_setup(
            self, *, enrollment_id: str, session: Any | None = None
        ) -> bool:
            return await student_billing_enrollments.mark_autopay_active_from_setup(
                enrollment_id=enrollment_id,
                session=session,
            )

    class _EnrollmentBillingIdentity:
        async def get_billing_identity(self, enrollment_id: str) -> dict[str, str | None] | None:
            enrollment = await db["enrollments"].find_one(
                {"academy_id": academy_id, "enrollment_id": enrollment_id}
            )
            if enrollment is None:
                return None
            return {
                "academy_id": academy_id,
                "parent_id": str(
                    enrollment.get("parent_id") or enrollment.get("parent_user_id") or ""
                ),
                "student_id": str(enrollment.get("student_id") or "") or None,
                "enrollment_id": enrollment_id,
                "session_id": str(enrollment.get("session_id") or "") or None,
            }

    enrollment_autopay_state = _EnrollmentAutopayState()
    enrollment_identity = _EnrollmentBillingIdentity()
    checkout_status = GetCheckoutStatus(
        payments=payments_repo,
        subscriptions=subscriptions_repo,
        stripe=stripe,
        parent_customers=parent_customers_repo,
        enrollment_autopay=enrollment_autopay_state,
        consent_repo=autopay_consents_repo,
        outbox=outbox,
        transaction_runner=transaction_runner,
        academy_id=request_academy_id,
    )

    handle_webhook = HandleWebhookEvent(
        stripe=stripe,
        dedup=dedup,
        payments=payments_repo,
        subscriptions=subscriptions_repo,
        billing_enrollments=student_billing_enrollments,
        billing_ledger=billing_ledger_repo,
        billing_counters=billing_counters_repo,
        billing_settings=billing_settings_repo,
        parent_customers=parent_customers_repo,
        enrollment_autopay=enrollment_autopay_state,
        consent_repo=autopay_consents_repo,
        transaction_runner=transaction_runner,
        enrollment_identity=enrollment_identity,
        invoice_processing=invoice_processing,
        connected_accounts=_ConnectAccountResolver(connected_accounts_repo, academy_id),
        outbox=outbox,
        academy_id=academy_id,
        expected_livemode=True
        if settings.env == "prod"
        else False
        if settings.env == "test"
        else None,
    )
    quote_enrollment_uc = QuoteEnrollment(
        sessions=payments_repo,
        snapshots=payments_repo,
        occurrences=payments_repo,
        clock=clock,
    )

    # Enrollment
    sessions_query = MongoSessionRepository(db)
    sessions_writer = MongoSessionWriter(db)
    enrollments_writer = MongoEnrollmentWriter(db)
    enrollments_query = MongoEnrollmentRepository(db)
    enrollment_events = MongoEnrollmentEventRepository(db)
    students_writer = MongoStudentWriter(db)
    students_query = MongoStudentRepository(db)
    # No boot-time academy fallback passed here — compose_parent must stay free
    # of that setting (see test_no_raw_tenant_mongo_access.py); every read/write
    # below is either unscoped by user_id or takes academy_id explicitly at
    # call time via current_academy_id().
    users_query = MongoUserRepository(db)
    occurrences_query = MongoSessionOccurrenceRepository(db)
    waitlist = MongoWaitlistRepository(db)
    pause_requests = MongoPauseRequestRepository(db)
    absence_notices_repo = MongoAbsenceNoticeRepository(db)
    self_service_policies_repo = MongoSelfServicePolicyRepository(db)
    makeup_requests_repo = MongoMakeupRequestRepository(db)
    occurrence_roster_repo = MongoOccurrenceRosterRepository(db)
    trial_requests_repo = MongoTrialRequestRepository(db)

    get_child_schedule_uc = GetChildSchedule(
        enrollments=enrollments_query,
        occurrences=occurrences_query,
        sessions=sessions_query,
        students=students_query,
    )

    submit_absence_notice = SubmitAbsenceNotice(
        students=students_query,
        occurrences=occurrences_query,
        enrollments=enrollments_query,
        notices=absence_notices_repo,
        policies=self_service_policies_repo,
    )
    list_parent_absences = ListParentAbsences(notices=absence_notices_repo)

    submit_makeup_request = SubmitMakeupRequest(
        students=students_query,
        occurrences=occurrences_query,
        enrollments=enrollments_query,
        notices=absence_notices_repo,
        makeups=makeup_requests_repo,
        policies=self_service_policies_repo,
    )
    list_parent_makeups = ListParentMakeups(makeups=makeup_requests_repo)
    list_eligible_makeup_targets = ListEligibleMakeupTargets(
        students=students_query,
        occurrences=occurrences_query,
        sessions=sessions_query,
        enrollments=enrollments_query,
        occurrence_roster=occurrence_roster_repo,
        policies=self_service_policies_repo,
    )
    submit_trial_request = SubmitTrialRequest(
        students=students_query,
        sessions=sessions_query,
        trials=trial_requests_repo,
    )
    list_parent_trial_requests = ListParentTrialRequests(trials=trial_requests_repo)

    class _SelfCancelFeeBillingPort(SelfCancelBillingPort):
        """Adapts self-cancel (R4) to the billing context's REAL production
        line-append path (``AddInvoiceLine`` -> ``LedgerRepository.save_line``)
        — never Stripe, never invoice close/settle. Idempotent: before
        appending, checks the resolved invoice's existing lines for one
        already carrying this ``idempotency_key`` as ``source_id`` (with
        ``source_type="self_cancel_fee"``) — a retried cancel call can't
        double-bill even though ``AddInvoiceLine`` itself has no dedupe.
        """

        async def record_cancellation_fee(
            self,
            *,
            enrollment: Any,
            fee_cents: int,
            reason: str,
            actor_id: str,
            idempotency_key: str,
        ) -> dict[str, Any]:
            student = await students_query.by_ids([enrollment.student_id])
            if not student:
                logging.getLogger(__name__).warning(
                    "self-cancel fee skipped: no student found for student_id=%s",
                    enrollment.student_id,
                )
                return {"skipped": True, "reason": "student_not_found"}
            parent_id = student[0].parent_id
            # The fee's period is a *calendar* month label, and both
            # ``get_open_invoice_for_student`` below and
            # ``AddInvoiceLineCommand.period`` key off it. Derive it on the
            # session's own clock, the way QuoteEnrollment labels the checkout
            # quote (#541): a raw UTC label reads a month ahead for the several
            # evening hours before local month-end, so a parent cancelling at
            # 8:30pm Chicago on Nov 30 had the fee attached to — or a fresh
            # invoice opened for — December.
            session = await sessions_query.get(enrollment.session_id)
            timezone_name = (session.timezone if session is not None else None) or "America/Chicago"
            period = _local_period_label(clock(), timezone_name)

            existing_invoice = await billing_ledger_repo.get_open_invoice_for_student(
                enrollment.student_id, period
            )
            if existing_invoice is not None:
                existing_lines = await billing_ledger_repo.get_lines_for_invoice(
                    existing_invoice.invoice_id
                )
                for line in existing_lines:
                    if line.source_type == "self_cancel_fee" and line.source_id == idempotency_key:
                        return {
                            "line_id": line.line_id,
                            "invoice_id": line.invoice_id,
                            "deduped": True,
                        }

            result = await AddInvoiceLine(
                ledger=billing_ledger_repo,
                counters=billing_counters_repo,
                settings=billing_settings_repo,
            ).execute(
                AddInvoiceLineCommand(
                    student_id=enrollment.student_id,
                    period=period,
                    description=reason,
                    line_type="fee",
                    quantity=1,
                    unit_amount_cents=fee_cents,
                    source_type="self_cancel_fee",
                    source_id=idempotency_key,
                    # Request-time tenant, not the composition-time closure:
                    # every repo in this flow scopes by the ContextVar, and a
                    # multi-tenant process would otherwise write the fee line
                    # to the boot academy while cancelling in another.
                    academy_id=current_academy_id(),
                    parent_id=parent_id,
                )
            )
            return {
                "line_id": result.line.line_id,
                "invoice_id": result.invoice.invoice_id,
                "deduped": False,
            }

    # #612 staff roster alerts for the parent-side triggers: a self-cancel and
    # the waitlist promotion it frees a seat for.
    roster_notifier = compose_roster_notifier(db, settings)

    preview_self_cancel = PreviewSelfCancel(
        enrollments=enrollments_writer,
        students=students_query,
        policies=self_service_policies_repo,
        occurrences=occurrences_query,
    )
    self_cancel_enrollment = SelfCancelEnrollment(
        enrollments=enrollments_writer,
        students=students_query,
        policies=self_service_policies_repo,
        occurrences=occurrences_query,
        sessions=sessions_writer,
        outbox=outbox,
        billing=_SelfCancelFeeBillingPort(),
        enrollment_events=enrollment_events,
        roster_notifier=roster_notifier,
    )

    confirm_enrollment = ConfirmEnrollment(
        sessions=sessions_writer,
        enrollments=enrollments_writer,
        enrollment_query=enrollments_query,
        students=students_writer,
        outbox=outbox,
        idempotency_store=idempotency_store,
        enrollment_events=enrollment_events,
        academy_id=request_academy_id,
    )
    promote = PromoteFromWaitlist(
        waitlist=waitlist,
        sessions=sessions_writer,
        enrollments=enrollments_writer,
        outbox=outbox,
        enrollment_events=enrollment_events,
        roster_notifier=roster_notifier,
        academy_id=request_academy_id,
    )

    # Onboarding
    apps_repo = MongoApplicationRepository(db)
    waivers_repo = MongoRegistrationWaiverRepository(db)
    parent_waivers_repo = MongoParentWaiverRepository(db)
    get_waiver_req = GetParentWaiverRequirement(waivers=parent_waivers_repo)
    accept_waiver = AcceptParentWaiver(waivers=parent_waivers_repo, academy_id=request_academy_id)
    checkout_retirement = _StripeCheckoutAttemptRetirement(
        stripe=stripe,
        payments=payments_repo,
        clock=clock,
        unretired=MongoUnretiredCheckoutSessionRepository(db),
    )
    start_app = StartApplication(
        apps=apps_repo,
        academy_id=request_academy_id,
        clock=clock,
        checkout_retirement=checkout_retirement,
    )
    patch_app = PatchApplication(
        apps=apps_repo,
        waivers=waivers_repo,
        student_registrations=students_query,
    )
    get_status = GetApplicationStatus(apps=apps_repo)
    transition = TransitionApplication(
        apps=apps_repo,
        student_registrations=students_query,
        clock=clock,
        checkout_retirement=checkout_retirement,
    )
    list_available_sessions = ListParentAvailableSessions(sessions=sessions_query)
    request_pause = RequestEnrollmentPause(pause_requests=pause_requests)
    list_parent_pause_requests = ListParentPauseRequests(pause_requests=pause_requests)

    # Cross-context handlers register themselves at import time via @handler.
    # We install the deps holder so they can call the real use cases.
    install_handlers(
        HandlerDeps(
            confirm_enrollment=confirm_enrollment,
            promote_from_waitlist=promote,
            issue_refund=issue_refund,
            transition_application=transition,
        )
    )

    async def list_payments_for_parent(parent_id: str):
        # Request-time tenant, not the composition-time closure (C4): a
        # multi-tenant process would otherwise read the boot academy's rows.
        academy_id = current_academy_id()
        from dataclasses import dataclass as _dc

        @_dc
        class _Row:
            payment_id: str
            amount_cents: int
            currency: str
            status: str
            refunded_cents: int
            created_at: datetime
            session_id: str | None
            stripe_payment_intent_id: str | None = None
            stripe_invoice_id: str | None = None
            invoice_id: str | None = None
            invoice_period: str | None = None

        rows: list[_Row] = []
        legacy_rows: list[_Row] = []
        for p in await payments_repo.list_for_parent(parent_id):
            legacy_rows.append(
                _Row(
                    payment_id=p.payment_id,
                    amount_cents=p.amount_cents,
                    currency=p.currency or "usd",
                    status=p.status,
                    refunded_cents=p.refunded_cents,
                    created_at=p.created_at,
                    session_id=p.session_id,
                    stripe_payment_intent_id=p.stripe_payment_intent_id,
                )
            )
        ledger_keys: set[str] = set()
        ledger_row_ids: set[str] = set()
        async for doc in db["ledger_payments"].find(
            {"academy_id": academy_id, "parent_id": parent_id},
            sort=[("created_at", -1)],
            limit=100,
        ):
            ledger_row_ids.add(str(doc.get("payment_id") or ""))
            stripe_payment_intent_id = (
                str(doc.get("stripe_payment_intent_id"))
                if doc.get("stripe_payment_intent_id")
                else None
            )
            stripe_invoice_id = (
                str(doc.get("stripe_invoice_id")) if doc.get("stripe_invoice_id") else None
            )
            ledger_keys.update(key for key in (stripe_payment_intent_id, stripe_invoice_id) if key)
            rows.append(
                _Row(
                    payment_id=str(doc.get("payment_id") or ""),
                    amount_cents=int(doc.get("amount_cents") or 0),
                    currency=str(doc.get("currency") or "usd"),
                    status=str(doc.get("status") or ""),
                    refunded_cents=0,
                    created_at=doc["created_at"],
                    session_id=None,
                    stripe_payment_intent_id=stripe_payment_intent_id,
                    stripe_invoice_id=stripe_invoice_id,
                )
            )
        # Label ledger payments with the invoice they paid: payment_allocations
        # links payment_id -> invoice_id, and the invoice carries the period,
        # so two monthly payments stop looking like a duplicate charge.
        ledger_payment_ids = [row.payment_id for row in rows if row.payment_id]
        if ledger_payment_ids:
            invoice_by_payment: dict[str, str] = {}
            async for alloc in db["payment_allocations"].find(
                {"academy_id": academy_id, "payment_id": {"$in": ledger_payment_ids}}
            ):
                payment_key = str(alloc.get("payment_id") or "")
                alloc_invoice_id = str(alloc.get("invoice_id") or "")
                if payment_key and alloc_invoice_id and payment_key not in invoice_by_payment:
                    invoice_by_payment[payment_key] = alloc_invoice_id
            period_by_invoice: dict[str, str] = {}
            if invoice_by_payment:
                async for inv in db["invoices"].find(
                    {
                        "academy_id": academy_id,
                        "invoice_id": {"$in": sorted(set(invoice_by_payment.values()))},
                    },
                    {"invoice_id": 1, "period": 1},
                ):
                    period_by_invoice[str(inv.get("invoice_id") or "")] = str(
                        inv.get("period") or ""
                    )
            for row in rows:
                linked_invoice_id = invoice_by_payment.get(row.payment_id)
                if linked_invoice_id:
                    row.invoice_id = linked_invoice_id
                    row.invoice_period = period_by_invoice.get(linked_invoice_id) or None

        rows.extend(
            row
            for row in legacy_rows
            if row.payment_id not in ledger_row_ids
            and (
                not row.stripe_payment_intent_id or row.stripe_payment_intent_id not in ledger_keys
            )
        )
        rows.sort(
            key=lambda r: r.created_at or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )
        return rows

    async def list_credits_for_parent(parent_id: str):
        return await credits_repo.list_for_parent(parent_id)

    async def _parent_students(parent_id: str) -> list[dict[str, Any]]:
        academy_id = current_academy_id()  # request-time tenant (C4)
        cursor = (
            db["students"]
            .find(
                {
                    "academy_id": academy_id,
                    "$or": [{"parent_id": parent_id}, {"parent_user_id": parent_id}],
                }
            )
            .sort([("full_name", 1)])
        )
        return [doc async for doc in cursor]

    async def list_children_for_parent(parent_id: str) -> list[dict[str, Any]]:
        academy_id = current_academy_id()  # request-time tenant (C4)
        students = await _parent_students(parent_id)
        rows: list[dict[str, Any]] = []
        for student in students:
            student_id = str(student.get("student_id") or student["_id"])
            active_session_count = await db["enrollments"].count_documents(
                {"academy_id": academy_id, "student_id": student_id, "status": "active"}
            )
            attended_count = await db["attendance"].count_documents(
                {
                    "academy_id": academy_id,
                    "student_id": student_id,
                    "status": {"$in": ["present", "late"]},
                }
            )
            absent_count = await db["attendance"].count_documents(
                {"academy_id": academy_id, "student_id": student_id, "status": "absent"}
            )
            rows.append(
                {
                    "student_id": student_id,
                    "full_name": str(student.get("full_name") or "Unnamed student"),
                    "status": str(student.get("status") or "active"),
                    "active_session_count": active_session_count,
                    "attended_count": attended_count,
                    "absent_count": absent_count,
                }
            )
        return rows

    def _child_facts(student: dict[str, Any]) -> ChildFacts:
        raw_medical = student.get("medical_notes")
        return ChildFacts(
            student_id=str(student.get("student_id") or student["_id"]),
            full_name=student.get("full_name"),
            date_of_birth=(str(student["date_of_birth"]) if student.get("date_of_birth") else None),
            emergency_contact_name=student.get("emergency_contact_name"),
            emergency_contact_phone=student.get("emergency_contact_phone"),
            medical_notes=str(raw_medical) if raw_medical else None,
        )

    def _child_view(student: dict[str, Any]) -> dict[str, Any]:
        facts = _child_facts(student)
        no_medical_conditions = facts.medical_notes == MEDICAL_NONE_SENTINEL
        return {
            "student_id": facts.student_id,
            "full_name": facts.full_name or "Unnamed student",
            "date_of_birth": facts.date_of_birth,
            "emergency_contact_name": facts.emergency_contact_name,
            "emergency_contact_phone": facts.emergency_contact_phone,
            "medical_notes": None if no_medical_conditions else facts.medical_notes,
            "no_medical_conditions": no_medical_conditions,
        }

    async def get_parent_profile(parent_id: str) -> dict[str, Any] | None:
        """Parent's own editable fields, their children's, and the computed
        completeness gaps — backs GET /api/v2/parent/profile (issue #380)."""
        user = await users_query.get_by_id(parent_id)
        if user is None:
            return None
        students = await _parent_students(parent_id)
        parent_facts = ParentFacts(
            display_name=user.display_name,
            phone=user.phone,
            email_confirmed_at=user.email_confirmed_at,
        )
        child_facts = [_child_facts(s) for s in students]
        gaps = evaluate(parent_facts, child_facts)
        return {
            "user_id": user.user_id,
            "display_name": user.display_name,
            "email": str(user.email),
            "email_confirmed": user.email_confirmed_at is not None,
            "phone": user.phone,
            "children": [_child_view(s) for s in students],
            "gaps": {
                "parent": gaps.parent,
                "children": gaps.children,
                "is_complete": gaps.is_complete,
            },
        }

    async def update_parent_profile(parent_id: str, request: Any) -> dict[str, Any] | None:
        """Parent editing their own display name / phone. Reuses the audited
        admin-user write with the parent as both actor and target — matching
        how the coach self-service profile already updates identity.User."""
        academy_id = current_academy_id()
        command = UpdateAdminUserCommand(
            display_name=request.display_name,
            phone=request.phone,
            actor_id=parent_id,
            reason="parent self-service profile update",
        )
        result = await users_query.update_admin_user(parent_id, command, academy_id=academy_id)
        if result is None:
            return None
        return await get_parent_profile(parent_id)

    async def confirm_parent_email(parent_id: str) -> dict[str, Any] | None:
        user = await users_query.confirm_email(parent_id)
        if user is None:
            return None
        return await get_parent_profile(parent_id)

    async def update_parent_child(
        parent_id: str, student_id: str, request: Any
    ) -> dict[str, Any] | None:
        """Parent editing their own child's safety details. Ownership is
        verified against the tenant-scoped student list before any write —
        this is the first parent write path in the codebase, so a student
        belonging to another parent (or another academy) must never be
        reachable, and both cases return None (404) rather than distinguishing
        them, matching the existing _verify_child_ownership convention used
        elsewhere in the parent BFF (progress_skill_routes.py)."""
        students = await _parent_students(parent_id)
        owned_ids = {str(s.get("student_id") or s["_id"]) for s in students}
        if student_id not in owned_ids:
            return None

        medical_notes = request.medical_notes
        if request.no_medical_conditions:
            medical_notes = MEDICAL_NONE_SENTINEL

        command = UpdateAdminStudentCommand(
            date_of_birth=request.date_of_birth,
            emergency_contact_name=request.emergency_contact_name,
            emergency_contact_phone=request.emergency_contact_phone,
            medical_notes=medical_notes,
            actor_id=parent_id,
            reason="parent self-service profile update",
        )
        updated = await students_query.update_student_profile(student_id, command)
        if updated is None:
            return None
        return await get_parent_profile(parent_id)

    async def list_enrollments_for_parent(parent_id: str) -> list[dict[str, Any]]:
        academy_id = current_academy_id()  # request-time tenant (C4)
        students = await _parent_students(parent_id)
        by_id = {str(s.get("student_id") or s["_id"]): s for s in students}
        if not by_id:
            return []
        billing_customer = await db["parent_billing_customers"].find_one(
            {"academy_id": academy_id, "parent_id": parent_id}
        )
        autopay_payment_method_type = None
        autopay_payment_method_label = None
        autopay_payment_method_last4 = None
        autopay_setup_status = None
        if billing_customer:
            autopay_payment_method_type = billing_customer.get(
                "primary_payment_method_type"
            ) or billing_customer.get("payment_method_type")
            autopay_payment_method_label = billing_customer.get(
                "primary_payment_method_label"
            ) or billing_customer.get("payment_method_label")
            autopay_payment_method_last4 = billing_customer.get(
                "primary_payment_method_last4"
            ) or billing_customer.get("payment_method_last4")
            autopay_setup_status = billing_customer.get(
                "primary_setup_status"
            ) or billing_customer.get("setup_status")
        cursor = (
            db["enrollments"]
            .find(
                {
                    "academy_id": academy_id,
                    "student_id": {"$in": list(by_id)},
                    "status": {"$in": ["active", "paused"]},
                }
            )
            .sort([("created_at", -1), ("enrollment_id", 1)])
        )
        rows: list[dict[str, Any]] = []
        async for enrollment in cursor:
            student_id = str(enrollment["student_id"])
            enrollment_id = str(enrollment.get("enrollment_id") or enrollment["_id"])
            session = await db["sessions"].find_one(
                {"academy_id": academy_id, "session_id": enrollment["session_id"]}
            )
            billing_enrollment = await db["student_billing_enrollments"].find_one(
                {
                    "academy_id": academy_id,
                    "parent_id": parent_id,
                    "enrollment_id": enrollment_id,
                }
            )
            rows.append(
                {
                    "enrollment_id": enrollment_id,
                    "student_id": student_id,
                    "student_name": str(by_id[student_id].get("full_name") or "Unnamed student"),
                    "session_id": str(enrollment["session_id"]),
                    "session_title": str(session.get("title") if session else "Session"),
                    "status": str(enrollment.get("status") or "active"),
                    "payment_mode": enrollment.get("payment_mode"),
                    "subscription_status": enrollment.get("subscription_status"),
                    "autopay_enrollment_status": (
                        billing_enrollment.get("autopay_enrollment_status")
                        if billing_enrollment
                        else None
                    ),
                    "last_attempt_outcome": (
                        billing_enrollment.get("last_attempt_outcome")
                        if billing_enrollment
                        else None
                    ),
                    "last_attempt_at": (
                        billing_enrollment.get("last_attempt_at") if billing_enrollment else None
                    ),
                    "last_failure_code": (
                        billing_enrollment.get("last_failure_code") if billing_enrollment else None
                    ),
                    "autopay_payment_method_type": autopay_payment_method_type,
                    "autopay_payment_method_label": autopay_payment_method_label,
                    "autopay_payment_method_last4": autopay_payment_method_last4,
                    "autopay_setup_status": autopay_setup_status,
                }
            )
        return rows

    async def _resolve_coach_name(coach_id: str | None) -> str | None:
        if not coach_id:
            return None
        academy_id = current_academy_id()  # request-time tenant (C4)
        user = await db["users"].find_one(
            {"academy_id": academy_id, "$or": [{"user_id": coach_id}, {"firebase_uid": coach_id}]}
        )
        if not user:
            return None
        for field in ("full_name", "display_name", "name"):
            if user.get(field):
                return str(user[field])
        first = str(user.get("first_name") or "")
        last = str(user.get("last_name") or "")
        name = f"{first} {last}".strip()
        return name or None

    async def list_attendance_for_parent(
        parent_id: str, *, limit: int = 50, offset: int = 0
    ) -> tuple[list[dict[str, Any]], int]:
        academy_id = current_academy_id()  # request-time tenant (C4)
        students = await _parent_students(parent_id)
        by_id = {str(s.get("student_id") or s["_id"]): s for s in students}
        if not by_id:
            return [], 0
        query = {"academy_id": academy_id, "student_id": {"$in": list(by_id)}}
        total = await db["attendance"].count_documents(query)
        cursor = db["attendance"].find(query).sort([("marked_at", -1)]).skip(offset).limit(limit)
        attendance_rows = [doc async for doc in cursor]

        # Batch-fetch all sessions referenced in this page
        session_ids = list(
            {str(row["session_id"]) for row in attendance_rows if row.get("session_id")}
        )
        sessions_map: dict[str, Any] = {}
        if session_ids:
            async for sdoc in db["sessions"].find(
                {"academy_id": academy_id, "session_id": {"$in": session_ids}}
            ):
                sessions_map[str(sdoc.get("session_id") or sdoc["_id"])] = sdoc

        # Batch-fetch all coaches up-front to avoid N serial DB round-trips in the loop.
        unique_coach_ids = list(
            {
                str(a.get("marked_by") or a.get("coach_id"))
                for a in attendance_rows
                if a.get("marked_by") or a.get("coach_id")
            }
        )
        coach_cache: dict[str, str | None] = {cid: None for cid in unique_coach_ids}
        if unique_coach_ids:
            async for user in db["users"].find(
                {
                    "academy_id": academy_id,
                    "$or": [
                        {"user_id": {"$in": unique_coach_ids}},
                        {"firebase_uid": {"$in": unique_coach_ids}},
                    ],
                }
            ):
                uid = str(user.get("user_id") or user.get("firebase_uid") or "")
                if uid not in coach_cache:
                    continue
                for field in ("full_name", "display_name", "name"):
                    if user.get(field):
                        coach_cache[uid] = str(user[field])
                        break
                else:
                    name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
                    coach_cache[uid] = name or None

        rows: list[dict[str, Any]] = []
        for attendance in attendance_rows:
            student_id = str(attendance["student_id"])
            session = sessions_map.get(str(attendance["session_id"]))
            coach_id = str(attendance.get("marked_by") or attendance.get("coach_id") or "")
            coach_name = coach_cache.get(coach_id)
            rows.append(
                {
                    "attendance_id": str(attendance["attendance_id"]),
                    "student_id": student_id,
                    "student_name": str(
                        by_id.get(student_id, {}).get("full_name") or "Unnamed student"
                    ),
                    "session_id": str(attendance["session_id"]),
                    "session_title": str((session or {}).get("title") or "Session"),
                    "status": str(attendance["status"]),
                    "marked_at": attendance["marked_at"],
                    "coach_name": coach_name,
                }
            )
        return rows, total

    async def list_progress_for_parent(
        parent_id: str, *, limit: int = 50, offset: int = 0
    ) -> tuple[list[dict[str, Any]], int]:
        academy_id = current_academy_id()  # request-time tenant (C4)
        students = await _parent_students(parent_id)
        by_id = {str(s.get("student_id") or s["_id"]): s for s in students}
        if not by_id:
            return [], 0
        query = {"academy_id": academy_id, "student_id": {"$in": list(by_id)}}
        total_notes = await db["progress_notes"].count_documents(query)
        total_feedback = await db["session_feedback"].count_documents(query)
        total = total_notes + total_feedback
        # Fetch ALL matching rows from both collections (no skip/limit on DB queries)
        # so we can merge and slice correctly — avoids page 2 repeating feedback items.
        note_rows = [
            doc async for doc in db["progress_notes"].find(query).sort([("created_at", -1)])
        ]
        feedback_rows = [
            doc async for doc in db["session_feedback"].find(query).sort([("created_at", -1)])
        ]

        # Batch-fetch all sessions referenced in this page
        all_session_ids = list(
            {str(n["session_id"]) for n in note_rows + feedback_rows if n.get("session_id")}
        )
        sessions_map: dict[str, Any] = {}
        if all_session_ids:
            async for sdoc in db["sessions"].find(
                {"academy_id": academy_id, "session_id": {"$in": all_session_ids}}
            ):
                sessions_map[str(sdoc.get("session_id") or sdoc["_id"])] = sdoc

        coach_cache: dict[str, str | None] = {}
        rows: list[dict[str, Any]] = []

        for note in note_rows:
            student_id = str(note["student_id"])
            coach_id = note.get("coach_id")
            if coach_id not in coach_cache:
                coach_cache[coach_id] = await _resolve_coach_name(coach_id)
            coach_name = coach_cache[coach_id]
            session_id = note.get("session_id")
            session = sessions_map.get(str(session_id)) if session_id else None
            session_title: str | None = str(session.get("title") or "Session") if session else None
            rows.append(
                {
                    "note_id": str(note.get("note_id") or note["_id"]),
                    "student_id": student_id,
                    "student_name": str(
                        by_id.get(student_id, {}).get("full_name") or "Unnamed student"
                    ),
                    "session_id": str(session_id) if session_id else None,
                    "session_title": session_title,
                    "coach_id": coach_id,
                    "coach_name": coach_name,
                    "body": str(note.get("body") or note.get("note") or ""),
                    "created_at": note.get("created_at") or datetime.now(UTC),
                    "note_type": "progress_note",
                }
            )

        for fb in feedback_rows:
            student_id = str(fb["student_id"])
            coach_id = fb.get("coach_id")
            if coach_id not in coach_cache:
                coach_cache[coach_id] = await _resolve_coach_name(coach_id)
            coach_name = coach_cache[coach_id]
            session_id = fb.get("session_id")
            session = sessions_map.get(str(session_id)) if session_id else None
            session_title = str(session.get("title") or "Session") if session else None
            rows.append(
                {
                    "note_id": str(fb.get("feedback_id") or fb["_id"]),
                    "student_id": student_id,
                    "student_name": str(
                        by_id.get(student_id, {}).get("full_name") or "Unnamed student"
                    ),
                    "session_id": str(session_id) if session_id else None,
                    "session_title": session_title,
                    "coach_id": coach_id,
                    "coach_name": coach_name,
                    "body": str(fb.get("body") or ""),
                    "created_at": fb.get("created_at") or datetime.now(UTC),
                    "note_type": "feedback",
                    "rating": fb.get("rating"),
                }
            )

        # Re-sort blended results by created_at descending, then slice for the requested page
        rows.sort(key=lambda r: r["created_at"], reverse=True)
        page = rows[offset : offset + limit]
        return page, total

    async def list_invoices_for_parent(parent_id: str):
        return await billing_ledger_repo.list_invoices_for_parent(parent_id)

    async def get_invoice_for_parent(*, parent_id: str, invoice_id: str):
        academy_id = current_academy_id()  # request-time tenant (C4)
        invoice = await billing_ledger_repo.get_invoice(invoice_id)
        if invoice is None or invoice.parent_id != parent_id:
            return None
        lines_cursor = db["invoice_lines"].find(
            {"academy_id": academy_id, "invoice_id": invoice_id}
        )
        lines = [InvoiceLine(**doc) async for doc in lines_cursor]
        return {"invoice": invoice, "lines": lines}

    def _validate_checkout_redirect_urls(*urls: str) -> None:
        # Static env-var origins PLUS the request's resolved tenant origins
        # (rebuilt from stored slug/verified domains, never the raw Host), so a
        # newly onboarded academy can check out on its own host without a
        # CORS_ORIGINS edit.
        _tenant_origins = current_tenant_origins()
        _allowed = (*settings.cors_allowed_origins(), *_tenant_origins)
        for url in urls:
            try:
                validate_redirect_url(url, allowed_origins=_allowed)
            except InvalidRedirectUrl:
                if not _tenant_origins:
                    # Resolvable host but no derivable origins — typically an
                    # unverified custom_domain. Ops needs to see this: the
                    # tenant is browsable but cannot pay.
                    log.info(
                        "checkout_redirect_rejected_without_tenant_origins url=%s",
                        url,
                    )
                raise

    async def start_invoice_payment_for_parent(
        *,
        parent_id: str,
        invoice_id: str,
        success_url: str,
        cancel_url: str,
        enroll_autopay: bool = False,
    ):
        _validate_checkout_redirect_urls(success_url, cancel_url)
        invoice = await billing_ledger_repo.get_invoice(invoice_id)
        if invoice is None or invoice.parent_id != parent_id:
            return None
        if invoice.status not in {"open", "partially_paid"} or invoice.balance_due_cents <= 0:
            raise ValueError("invoice is not payable")
        invoice_stripe = stripe if hasattr(stripe, "create_invoice_checkout_session") else None
        # Opted-in payments must return with a checkout_session_id so the
        # parent app's checkout-status poll can pick up autopay activation
        # instead of relying solely on the webhook. Unmodified when not
        # opted in, so the plain one-time-payment redirect is unchanged.
        redirect_success_url = (
            _success_url_with_checkout_session_placeholder(success_url)
            if enroll_autopay
            else success_url
        )
        result = await SendInvoice(
            ledger=billing_ledger_repo,
            stripe=invoice_stripe,  # type: ignore[arg-type]
            email=None,
            connected_accounts=connected_accounts_repo,
            settings=billing_settings_repo,
            success_url=redirect_success_url,
            cancel_url=cancel_url,
        ).execute(invoice_id, enroll_autopay=enroll_autopay)
        if not result.checkout_url:
            # Still 409, but now with a machine-readable code and the concrete
            # reason SendInvoice recorded (issue #426) instead of a bare string.
            raise InvoicePayLinkUnavailable(
                "invoice payment link unavailable",
                reason=result.checkout_failure_code,
            )
        return {
            "invoice_id": result.invoice.invoice_id,
            "checkout_url": result.checkout_url,
        }

    async def start_balance_payment_for_parent(
        *,
        parent_id: str,
        success_url: str,
        cancel_url: str,
        enroll_autopay: bool = False,
    ):
        academy_id = current_academy_id()  # request-time tenant (C4)
        _validate_checkout_redirect_urls(success_url, cancel_url)
        all_invoices = await billing_ledger_repo.list_invoices_for_parent(parent_id)
        payable = [
            inv
            for inv in all_invoices
            if inv.status in {"open", "partially_paid"} and inv.balance_due_cents > 0
        ]
        if not payable:
            raise ValueError("no payable invoices")
        if len(payable) == 1:
            result = await start_invoice_payment_for_parent(
                parent_id=parent_id,
                invoice_id=payable[0].invoice_id,
                success_url=success_url,
                cancel_url=cancel_url,
                enroll_autopay=enroll_autopay,
            )
            if result is None:
                raise ValueError("invoice not found")
            return {"redirect_url": result["checkout_url"]}
        invoice_stripe = stripe if hasattr(stripe, "create_invoice_checkout_session") else None
        if invoice_stripe is None:
            # No Stripe wiring at all — nothing is broken, this academy just
            # does not collect online. Same 409, no failure recorded.
            raise InvoicePayLinkUnavailable("balance payment unavailable")
        # Destination-charge routing (Slice I posture): funds must settle to the
        # academy's connected account; refuse a platform charge if not ready
        # unless the temporary allow_platform_charge_fallback escape hatch is on.
        account = await connected_accounts_repo.get_for_academy()
        connected_account_stripe_id: str | None = None
        if account is not None and account.is_ready_for_charges():
            connected_account_stripe_id = account.stripe_account_id
        else:
            fallback_enabled = False
            try:
                fallback_enabled = (
                    await billing_settings_repo.get()
                ).allow_platform_charge_fallback
            except Exception as exc:
                log.warning(
                    "start_balance_payment: billing settings lookup failed; keeping "
                    "fail-closed connected-account requirement parent=%s err=%s",
                    parent_id,
                    exc,
                )
            if not fallback_enabled:
                # Same split as SendInvoice (issue #426): an academy with no
                # Connect account at all has simply never onboarded online
                # payments — nothing is broken, so record nothing. An account
                # that EXISTS but cannot charge is a real, operator-visible
                # failure.
                if account is not None:
                    log.error(
                        "start_balance_payment: refusing pay link parent=%s invoice_count=%d "
                        "— connected account not ready",
                        parent_id,
                        len(payable),
                    )
                    await record_checkout_mint_failure(
                        billing_ledger_repo,
                        invoices=payable,
                        failure_code=CHECKOUT_FAILURE_ACCOUNT_NOT_READY,
                        failure_message=(
                            "Academy Stripe connected account exists but is not ready for "
                            "charges, and platform-charge fallback is off."
                        ),
                    )
                raise InvoicePayLinkUnavailable(
                    "balance payment unavailable",
                    reason=(CHECKOUT_FAILURE_ACCOUNT_NOT_READY if account is not None else None),
                )
            log.warning(
                "start_balance_payment: connected account not ready — falling back to "
                "PLATFORM charge (allow_platform_charge_fallback=on) parent=%s",
                parent_id,
            )
        currencies = {inv.currency for inv in payable}
        if len(currencies) != 1:
            raise ValueError("cannot pay invoices with mixed currencies in one checkout")
        currency = next(iter(currencies))
        total_cents = sum(inv.balance_due_cents for inv in payable)
        invoice_ids_sorted = sorted(inv.invoice_id for inv in payable)
        invoice_ids = ",".join(invoice_ids_sorted)
        # Deterministic idempotency key so retries/re-clicks for the same unpaid
        # invoice set reuse one Stripe Checkout session instead of creating
        # duplicate collection attempts.
        fingerprint = hashlib.sha256(f"{academy_id}:{parent_id}:{invoice_ids}".encode()).hexdigest()
        # Autopay opt-in kwargs are only passed when requested so the plain
        # balance-payment gateway call stays byte-identical. The opt-in
        # idempotency key is distinct: an earlier one-time balance session must
        # not be replayed without the saved-payment-method params.
        idempotency_key = f"balance-payment:{fingerprint}"
        autopay_kwargs: dict[str, Any] = {}
        if enroll_autopay:
            idempotency_key = f"{idempotency_key}:autopay-optin"
            autopay_kwargs = {
                "save_payment_method_for_autopay": True,
                "autopay_enrollment_ids": sorted(
                    {inv.enrollment_id for inv in payable if inv.enrollment_id}
                ),
            }
        # Same reasoning as the single-invoice path: opted-in payments need a
        # checkout_session_id on return so the checkout-status poll can pick
        # up activation instead of relying solely on the webhook.
        redirect_success_url = (
            _success_url_with_checkout_session_placeholder(success_url)
            if enroll_autopay
            else success_url
        )
        try:
            _, url = await invoice_stripe.create_invoice_checkout_session(
                invoice_id=f"balance-{parent_id[:8]}",
                amount_cents=total_cents,
                currency=currency,
                success_url=redirect_success_url,
                cancel_url=cancel_url,
                metadata={
                    "academy_id": academy_id,
                    "parent_id": parent_id,
                    "invoice_ids": invoice_ids,
                    "source": "invoice_balance",
                    "type": "balance_payment",
                },
                idempotency_key=idempotency_key,
                connected_account_id=connected_account_stripe_id,
                **autopay_kwargs,
            )
        except Exception as exc:
            # Loud, and recorded per invoice (issue #426) — this is the parent
            # portal's primary payment CTA, so a broken gateway here is exactly
            # the outage signal an operator needs the same day.
            log.error(
                "start_balance_payment: checkout creation FAILED parent=%s invoice_count=%d "
                "idempotency_key=%s err=%s",
                parent_id,
                len(payable),
                idempotency_key,
                exc,
                exc_info=True,
            )
            await record_checkout_mint_failure(
                billing_ledger_repo,
                invoices=payable,
                failure_code=CHECKOUT_FAILURE_STRIPE_ERROR,
                failure_message=str(exc),
            )
            raise InvoicePayLinkUnavailable(
                "balance payment unavailable",
                reason=CHECKOUT_FAILURE_STRIPE_ERROR,
            ) from exc
        return {"redirect_url": url}

    async def quote_enrollment(
        *,
        parent_id: str,
        session_id: str,
        student_id: str | None = None,
        start_date: str | None = None,
    ):
        if student_id:
            students = await _parent_students(parent_id)
            owned = {str(s.get("student_id") or s["_id"]) for s in students}
            if student_id not in owned:
                raise SessionNotFound("student not found", student_id=student_id)
        return await quote_enrollment_uc.execute(
            QuoteEnrollmentCommand(
                session_id=session_id,
                billing_start_at=datetime.now(UTC),
                billing_start_date=_parse_start_date(start_date),
                calculated_by=parent_id,
                parent_id=parent_id,
                student_id=student_id,
            )
        )

    async def start_checkout_for_application(
        *,
        parent_id: str,
        application_id: str,
        success_url: str,
        cancel_url: str,
    ):
        _validate_checkout_redirect_urls(success_url, cancel_url)
        app = await get_status.execute(application_id, caller_user_id=parent_id)
        # Refuse a checkout this application can never legally complete, and
        # refuse it BEFORE any side effect. Everything below mints a quote
        # snapshot, a Stripe Checkout Session and a pending Payment before the
        # CHECKOUT_PENDING transition at the end gets to reject the status —
        # so without this guard a retry from, say, terminal CHECKOUT_EXPIRED
        # leaves a burnt quote and a dangling pending Payment row behind every
        # single time, on top of the 409 the parent already sees.
        if app.status not in _CHECKOUT_STARTABLE_STATUSES:
            raise ApplicationNotEditable(
                "illegal application transition",
                from_status=app.status,
                to_status="CHECKOUT_PENDING",
            )
        # Stop new registrations from landing incomplete (issue #380). This
        # runs BEFORE the paid/zero-amount branch below — the $0 path skips
        # Stripe entirely and jumps straight to PENDING_APPROVAL, so a guard
        # placed after that branch would let free registrations through with
        # missing safety details.
        missing_fields = [
            field
            for field, value in (
                ("date_of_birth", app.child_profile.date_of_birth),
                ("emergency_contact_name", app.child_profile.emergency_contact_name),
                ("emergency_contact_phone", app.child_profile.emergency_contact_phone),
                ("parent_phone", app.parent_profile.phone),
            )
            if not value.strip()
        ]
        if missing_fields:
            # `missing` rides along in DomainError.details so the wizard can
            # send the parent back to the step that owns the field instead of
            # stranding them on the review screen with a raw field name.
            raise IncompleteApplication(
                f"Application is missing required details: {', '.join(missing_fields)}",
                missing=missing_fields,
            )
        if not app.selected_session_id:
            raise MissingSelectedSession(
                "application must have a selected session",
                application_id=application_id,
            )
        catalog = await list_available_sessions.execute()
        selected = next(
            (session for session in catalog if session.session_id == app.selected_session_id),
            None,
        )
        if selected is None:
            raise SessionNotFound(
                "selected session is not available for checkout",
                session_id=app.selected_session_id,
            )
        quote = await quote_enrollment_uc.execute(
            QuoteEnrollmentCommand(
                session_id=selected.session_id,
                billing_start_at=clock(),
                calculated_by=parent_id,
                parent_id=parent_id,
            )
        )
        if quote.final_amount_cents <= 0:
            # No billable classes remain this month, so there is nothing to
            # charge — Stripe rejects zero-amount Checkout Sessions. Skip
            # payment and move the application straight to admin review;
            # regular monthly billing starts next month.
            #
            # Persist which period was quoted $0 so admin approval can stamp
            # skip_periods on the enrollment — otherwise the monthly billing
            # generator has no proration signal at all (enrollment docs never
            # carry billing_start_at/created_at) and would charge full tuition
            # for this period once the enrollment exists.
            # Reuse the quote's own label instead of re-deriving one from a
            # fresh UTC now(): the quote's period is built in the session's
            # timezone, so a UTC label disagrees with it (and with the monthly
            # generator's skip_periods comparison) for the several evening
            # hours before local month-end (#541).
            zero_quote_period = quote.billing_period_label
            await apps_repo.save(app.model_copy(update={"zero_quote_period": zero_quote_period}))
            if quote.snapshot_id:
                consumed = await payments_repo.consume_quote_snapshot(quote.snapshot_id)
                if consumed is None:
                    # The snapshot expired (or a concurrent request burnt it)
                    # between quoting and consuming. Refuse the transition so
                    # the parent re-quotes rather than enrolling against an
                    # audit snapshot stamped EXPIRED (issue #530).
                    raise QuoteExpired(
                        "quote expired before checkout could start; please retry",
                        snapshot_id=quote.snapshot_id,
                        application_id=application_id,
                    )
            await transition.execute(app.application_id, "CHECKOUT_PENDING")
            await transition.execute(app.application_id, "PENDING_APPROVAL")
            return StartCheckoutResult(
                payment_id="",
                checkout_session_id="",
                redirect_url=success_url,
            )
        # Consume the snapshot BEFORE minting the Stripe Checkout Session:
        # consume() is the TTL gate, so running it first guarantees no
        # session (with the quote's amount frozen into it) can exist for a
        # snapshot that was already expired or burnt. If consume refuses,
        # nothing has been created yet and the parent simply re-quotes.
        # (If the Stripe call below then fails, the snapshot stays CONSUMED
        # and a retry mints a fresh quote — the pre-existing behaviour.)
        if quote.snapshot_id:
            consumed = await payments_repo.consume_quote_snapshot(quote.snapshot_id)
            if consumed is None:
                raise QuoteExpired(
                    "quote expired before checkout could start; please retry",
                    snapshot_id=quote.snapshot_id,
                    application_id=application_id,
                )
        result = await start_checkout.execute(
            StartCheckoutCommand(
                parent_id=parent_id,
                session_id=selected.session_id,
                amount_cents=quote.final_amount_cents,
                calculation_snapshot_id=quote.snapshot_id,
                success_url=success_url,
                cancel_url=cancel_url,
            )
        )
        # From here to the transition below there is a PAYABLE Stripe session
        # and a pending ledger_payments row that NO application references yet
        # — the transition is what stamps the claim, so it cannot run first
        # (it consumes both ids). Every raise in this window therefore has to
        # unwind the attempt itself, or the parent can still pay a session
        # nothing points back at: `checkout.session.completed` resolves the
        # payment by checkout_session_id and marks it succeeded, then
        # `execute_for_payment` looks the application up by payment_id, finds
        # None and returns silently. Money taken, application stuck, no alert,
        # and there is no sweeper (issue #590).
        #
        # The window is genuinely reachable: the transition's own
        # `_assert_child_not_enrolled` runs BEFORE its CAS (ambiguous
        # same-name registration, or an enrollment that appeared since the
        # last child-profile patch), the composition's status guard above is
        # a TOCTOU read, and the transition's re-read can raise
        # ApplicationNotFound or any Mongo error.
        try:
            await transition.execute(
                app.application_id,
                "CHECKOUT_PENDING",
                stripe_checkout_session_id=result.checkout_session_id,
                payment_id=result.payment_id,
            )
        except Exception:
            try:
                # Same instance the transition itself retires with, and it can
                # run over ids the transition already touched on TWO paths:
                #
                #  * lost CAS — the transition retires the attempt it just
                #    minted and THEN raises ApplicationNotEditable, so this is
                #    a second retirement of the SAME ids. Harmless by
                #    construction: _expire_session swallows Stripe's "already
                #    expired" refusal, and retire_checkout_attempt no-ops on a
                #    payment that is no longer `pending`.
                #
                #  * post-commit — on the re-stamp path _restamp_checkout
                #    retires the OLD attempt AFTER its CAS has committed, and
                #    that call is not exception-guarded (only the Stripe expire
                #    inside it is; _payments.get/save are not). A Mongo error
                #    there raises with the new ids already stamped, so this
                #    compensation retires the session the application NOW
                #    points at. Accepted: no money is at risk, because execute
                #    raised and the caller therefore never receives
                #    `redirect_url` — the parent is never sent to that session.
                #    And it self-heals: the application is left
                #    CHECKOUT_PENDING, which is in _CHECKOUT_STARTABLE_STATUSES,
                #    so the next start re-stamps it with a fresh session. The
                #    composition cannot tell "committed" from "did not commit"
                #    here, and guessing the other way leaks a payable orphan —
                #    the bug this whole block exists to close.
                await checkout_retirement.retire_checkout_attempt(
                    checkout_session_id=result.checkout_session_id,
                    payment_id=result.payment_id,
                )
            except Exception:
                # Never let the compensation's own failure mask the error the
                # wizard is supposed to render — but never let it pass unseen
                # either, since what it leaks is a payable session.
                log.exception(
                    "checkout compensation failed: session %s / payment %s may still be "
                    "payable for application %s",
                    result.checkout_session_id,
                    result.payment_id,
                    app.application_id,
                )
            raise
        return result

    async def start_autopay_for_enrollment(
        *,
        parent_id: str,
        enrollment_id: str,
        success_url: str,
        cancel_url: str,
    ):
        academy_id = current_academy_id()  # request-time tenant (C4)
        _validate_checkout_redirect_urls(success_url, cancel_url)
        enrollment = await db["enrollments"].find_one(
            {"academy_id": academy_id, "enrollment_id": enrollment_id}
        )
        if not enrollment:
            raise SessionNotFound("enrollment not found", enrollment_id=enrollment_id)
        student = await db["students"].find_one(
            {"academy_id": academy_id, "student_id": enrollment.get("student_id")}
        )
        if (
            not student
            or str(student.get("parent_id") or student.get("parent_user_id")) != parent_id
        ):
            raise SessionNotFound("enrollment not found", enrollment_id=enrollment_id)
        session = await sessions_query.get(str(enrollment["session_id"]))
        if session is None:
            raise SessionNotFound("session not found", session_id=str(enrollment["session_id"]))
        session_doc = await db["sessions"].find_one(
            {"academy_id": academy_id, "session_id": session.session_id}
        )
        amount_cents = _session_amount_cents(session_doc or {})
        result = await start_subscription_checkout.execute(
            StartSubscriptionCheckoutCommand(
                parent_id=parent_id,
                enrollment_id=enrollment_id,
                session_id=session.session_id,
                amount_cents=amount_cents,
                success_url=success_url,
                cancel_url=cancel_url,
            )
        )
        # Do NOT stamp subscription_id / subscription_status here. Autopay setup
        # no longer writes a `subscriptions` document (removed in #266): the setup
        # runs in Stripe "setup" mode and completion is tracked on
        # student_billing_enrollments.autopay_enrollment_status via
        # CompleteAutopaySetup. Writing result.subscription_id would leave the
        # enrollment pointing at a nonexistent doc, and "incomplete" would never
        # be cleared — producing permanent dangling/stuck state on every setup.
        await db["enrollments"].update_one(
            {"academy_id": academy_id, "enrollment_id": enrollment_id},
            {
                "$set": {
                    "payment_mode": "monthly",
                    "updated_at": datetime.now(UTC),
                }
            },
        )
        return result

    async def open_billing_portal(*, parent_id: str, return_url: str):
        _validate_checkout_redirect_urls(return_url)
        # Request-time tenant (C4): re-scoping to the boot academy here would
        # look up another tenant's Stripe customer in multi-academy mode.
        with tenant_scope(request_academy_id()):
            stripe_customer_id = await parent_customers_repo.get_stripe_customer_id(
                parent_id=parent_id
            )
        result = await create_portal.execute(
            CreateCustomerPortalSessionCommand(
                parent_id=parent_id,
                return_url=return_url,
                stripe_customer_id=stripe_customer_id,
            )
        )
        return result.model_dump()

    async def get_checkout_status(
        *,
        parent_id: str,
        checkout_session_id: str,
        source: str | None = None,
        actor_id: str | None = None,
        ip: str | None = None,
        user_agent: str | None = None,
    ):
        result = await checkout_status.execute(
            checkout_session_id,
            parent_id=parent_id,
            consent_context=AutopayConsentCaptureContext(
                source=source or "unknown",
                actor_id=actor_id,
                ip=ip,
                user_agent=user_agent,
            ),
        )
        return result.model_dump()

    async def get_registration_waiver():
        return await waivers_repo.get_active()

    async def get_academy_info(*, academy_id: str) -> dict[str, Any]:
        doc = await db["academies"].find_one({"academy_id": academy_id})
        if not doc:
            return {
                "display_name": "Academy",
                "timezone": None,
                "contact_email": None,
                "contact_phone": None,
                "hours_text": None,
                "address": None,
                "logo_url": None,
            }
        return {
            "display_name": str(doc.get("display_name") or "Academy"),
            "timezone": doc.get("timezone"),
            "contact_email": doc.get("contact_email"),
            "contact_phone": doc.get("contact_phone"),
            "hours_text": doc.get("hours_text"),
            "address": doc.get("address"),
            "logo_url": doc.get("logo_url"),
        }

    async def get_child_schedule(
        *,
        parent_id: str,
        student_id: str,
        frm: date | None = None,
        to: date | None = None,
        limit: int = 50,
        offset: int = 0,
    ):
        return await get_child_schedule_uc.execute(
            parent_id,
            student_id,
            frm=frm,
            to=to,
            limit=limit,
            offset=offset,
        )

    # Session-type billing enrollment. Ownership check and enrollment stamping
    # both resolve the tenant at request time (issue #532): a parent of academy
    # B must never enroll against — or leak Stripe checkout metadata for — the
    # boot academy.
    class _StudentOwnerLookup:
        async def is_owned(self, parent_id: str, student_id: str) -> bool:
            doc = await db["students"].find_one(
                {
                    "academy_id": request_academy_id(),
                    "student_id": student_id,
                    "$or": [{"parent_id": parent_id}, {"parent_user_id": parent_id}],
                }
            )
            return doc is not None

    enroll_child_uc = EnrollChildInSessionType(
        enrollments=student_billing_enrollments,
        session_types=session_types_repo,
        stripe=stripe,
        student_owner_lookup=_StudentOwnerLookup(),
        academy_id=request_academy_id,
        connected_accounts=connected_accounts_repo,
        settings=billing_settings_repo,
    )
    cancel_billing_enrollment_uc = CancelBillingEnrollment(
        enrollments=student_billing_enrollments,
        stripe=stripe,
    )

    sp_composition = compose_student_progress(db, outbox)
    curriculum_composition = compose_curriculum(db)
    # Messages inbox (UIM13) — shared comms store, per-recipient read routes.
    messages_repo = MongoMessageRepository(db)

    async def _visible_session_ids(parent_id: str) -> list[str]:
        """Sessions this parent's children are ACTIVELY enrolled in (#614).

        Resolved per request, never captured at composition time: the tenant
        comes from ``current_academy_id()`` inside the closure, and the roster
        is read live so a family that joins or leaves a class gains or loses
        that class's announcements immediately, with no backfill.

        A withdrawn family losing access to the class's past announcements is
        the intended, privacy-correct behaviour — the announcement is about a
        class they are no longer in.
        """
        academy_id = current_academy_id()  # request-time tenant (C4)
        students = await _parent_students(parent_id)
        student_ids = [str(s.get("student_id") or s["_id"]) for s in students]
        if not student_ids:
            return []
        cursor = db["enrollments"].find(
            {
                "academy_id": academy_id,
                "student_id": {"$in": student_ids},
                "status": "active",
            },
            {"session_id": 1},
        )
        return sorted({str(doc["session_id"]) async for doc in cursor if doc.get("session_id")})

    async def list_messages(parent_id: str) -> list[Message]:
        return await messages_repo.for_recipient(
            parent_id, visible_session_ids=await _visible_session_ids(parent_id)
        )

    async def mark_message_read(message_id: str, user_id: str) -> None:
        await messages_repo.mark_read(
            message_id, user_id, visible_session_ids=await _visible_session_ids(user_id)
        )

    return ParentComposition(
        start_application=start_app,
        patch_application=patch_app,
        get_application_status=get_status,
        transition_application=transition,
        start_checkout=start_checkout,
        quote_enrollment=quote_enrollment,
        start_checkout_for_application=start_checkout_for_application,
        start_autopay_for_enrollment=start_autopay_for_enrollment,
        open_billing_portal=open_billing_portal,
        get_checkout_status=get_checkout_status,
        handle_webhook_event=handle_webhook,
        list_available_sessions=list_available_sessions,
        list_payments_for_parent=list_payments_for_parent,
        list_credits_for_parent=list_credits_for_parent,
        list_children_for_parent=list_children_for_parent,
        list_enrollments_for_parent=list_enrollments_for_parent,
        request_enrollment_pause=request_pause,
        list_parent_pause_requests=list_parent_pause_requests,
        submit_absence_notice=submit_absence_notice,
        list_parent_absences=list_parent_absences,
        submit_makeup_request=submit_makeup_request,
        list_parent_makeups=list_parent_makeups,
        list_eligible_makeup_targets=list_eligible_makeup_targets,
        submit_trial_request=submit_trial_request,
        list_parent_trial_requests=list_parent_trial_requests,
        preview_self_cancel=preview_self_cancel,
        self_cancel_enrollment=self_cancel_enrollment,
        list_attendance_for_parent=list_attendance_for_parent,
        list_progress_for_parent=list_progress_for_parent,
        list_invoices_for_parent=list_invoices_for_parent,
        get_invoice_for_parent=get_invoice_for_parent,
        start_invoice_payment_for_parent=start_invoice_payment_for_parent,
        start_balance_payment_for_parent=start_balance_payment_for_parent,
        get_child_schedule=get_child_schedule,
        enroll_child=enroll_child_uc.execute,
        cancel_billing_enrollment=cancel_billing_enrollment_uc.execute,
        get_parent_waiver_requirement=get_waiver_req,
        accept_parent_waiver=accept_waiver,
        get_academy_info=get_academy_info,
        get_registration_waiver=get_registration_waiver,
        student_progress=sp_composition,
        curriculum=curriculum_composition,
        list_messages=list_messages,
        mark_message_read=mark_message_read,
        get_parent_profile=get_parent_profile,
        update_parent_profile=update_parent_profile,
        confirm_parent_email=confirm_parent_email,
        update_parent_child=update_parent_child,
    )


class _StripeGatewayProto(Protocol):
    """Re-export to make this module importable without backing import."""


class _ConnectAccountResolver:
    """Resolve a connected Stripe account id -> owning academy for the webhook
    guard (Slice I). Bridges the repo method name (``get_by_stripe_account_id``)
    to the resolver name the webhook handler expects (``academy_id_for_account``)
    — the Slice-B name-mismatch lesson, covered by a port-drive test.
    """

    def __init__(self, repo: MongoConnectedAccountRepository, academy_id: str) -> None:
        self._repo = repo
        self._academy_id = academy_id

    async def academy_id_for_account(self, stripe_account_id: str) -> str | None:
        with tenant_scope(self._academy_id):
            account = await self._repo.get_by_stripe_account_id(stripe_account_id)
        return account.academy_id if account else None

    async def update_status(
        self,
        *,
        stripe_account_id: str,
        status: str,
        charges_enabled: bool | None,
        payouts_enabled: bool | None,
        capabilities: dict[str, str],
    ) -> None:
        with tenant_scope(self._academy_id):
            await self._repo.update_status(
                stripe_account_id=stripe_account_id,
                status=status,
                charges_enabled=charges_enabled,
                payouts_enabled=payouts_enabled,
                capabilities=capabilities,
            )


# Boot-frozen tenant wiring that intentionally survives in compose_parent
# (issue #532). Everything on this list is either per-academy composed by the
# scheduler, request-guarded upstream, or a read path still pending conversion
# to the request_academy_id() pattern:
#
# - HandleWebhookEvent / _EnrollmentBillingIdentity: per-academy BY DESIGN —
#   the scheduler composes one processor per academy, ingest resolves the
#   tenant from the event payload, and the handler's cross-academy guards
#   quarantine mismatches.
# - Parent read-path closures (payments/credits/children/enrollments/
#   attendance/invoices/schedule listings): still close over the boot
#   academy_id. Safe while only one academy is actually served; NOT safe once
#   saas_mode serves multiple tenants — which is exactly what
#   ensure_multi_academy_composable refuses.
_STATIC_TENANT_WIRING_NOTE = (
    "compose_parent still contains boot-frozen academy_id read paths "
    "(see _STATIC_TENANT_WIRING_NOTE in backend/v2/composition/parent.py). "
    "Serving multiple academies (saas_mode=True with tenancy_mode=multi_academy) "
    "would silently stamp/read the boot academy for other tenants (issue #532). "
    "Either set APP_TENANCY_MODE=single_academy, finish converting the read "
    "paths to request_academy_id(), or explicitly acknowledge the risk with "
    "V2_ALLOW_STATIC_TENANT_PARENT_WIRING=true."
)


def ensure_multi_academy_composable(settings: Any) -> None:
    """Fail-closed startup guard (issue #532).

    ``tenancy_mode`` defaults to ``multi_academy`` but without ``saas_mode``
    the tenant middleware resolves every request to ``default_academy_id``, so
    the boot-frozen wiring is harmless. The dangerous config is the flip that
    actually serves multiple tenants: ``saas_mode=True`` + ``multi_academy``.
    Refuse to compose the parent BFF in that mode unless the operator has
    explicitly acknowledged the remaining static-tenant wiring.
    """
    if (
        getattr(settings, "saas_mode", False)
        and getattr(settings, "tenancy_mode", "multi_academy") == "multi_academy"
        and not getattr(settings, "allow_static_tenant_parent_wiring", False)
    ):
        raise RuntimeError(_STATIC_TENANT_WIRING_NOTE)


def _require_academy_id(academy_id: str | None) -> str:
    if not academy_id:
        raise ValueError("academy_id is required for parent composition")
    return academy_id


def _session_amount_cents(doc: dict[str, object]) -> int:
    if doc.get("amount_cents") is not None:
        return int(doc["amount_cents"])
    if doc.get("monthly_price_cents") is not None:
        return int(doc["monthly_price_cents"])
    if doc.get("monthly_price") is not None:
        return round(float(doc["monthly_price"]) * 100)  # type: ignore[arg-type]
    return 2500


def _local_period_label(instant: datetime, timezone_name: str) -> str:
    """``YYYY-MM`` label of ``instant`` on the session's own clock.

    Mirrors ``_period_label`` in
    ``backend.v2.contexts.billing.application.use_cases.quote_enrollment`` and
    ``_local_period_label`` in
    ``backend.v2.contexts.billing.infrastructure.mongo_monthly_billing`` — every
    site that turns an instant into a billing-period label has to agree, or the
    labels stop naming the same invoice at the local month boundary (#541).

    Naive datetimes are treated as UTC instants (what Mongo hands back after
    dropping tzinfo); an unknown zone name falls back to UTC rather than
    raising, because a bad zone must not be able to block a cancellation.
    """
    moment = instant if instant.tzinfo is not None else instant.replace(tzinfo=UTC)
    try:
        tz = ZoneInfo(timezone_name)
    except (KeyError, ValueError):
        tz = ZoneInfo("UTC")
    return moment.astimezone(tz).strftime("%Y-%m")


def _parse_start_date(value: str | None) -> date | None:
    """Parse a caller-supplied start date, leaving the timezone to the caller.

    This used to pin the date to ``America/Chicago`` midnight and hand the
    resulting instant down as ``billing_start_at``. That hardcoded zone is
    wrong for any session that is not in Chicago, and once QuoteEnrollment
    began reading the billing start in the *session's* timezone it became
    actively harmful: Chicago midnight on the 1st is 22:00 on the last day of
    the previous month in Los Angeles, so the quote would be labelled, priced
    and persisted against the wrong month (#541). The calendar date now
    travels down as a date and QuoteEnrollment resolves it against the
    session's own clock.
    """
    if not value:
        return None
    return datetime.fromisoformat(value).date()
