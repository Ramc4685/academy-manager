"""Compose the Parent BFF use cases."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
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
from backend.v2.contexts.billing.application.ports import StripeGateway
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
from backend.v2.contexts.billing.application.use_cases.send_invoice import SendInvoice
from backend.v2.contexts.billing.application.use_cases.start_checkout import (
    StartCheckout,
    StartCheckoutCommand,
    StartCheckoutResult,
)
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
from backend.v2.contexts.enrollment.application.use_cases.confirm_enrollment import (
    ConfirmEnrollment,
)
from backend.v2.contexts.enrollment.application.use_cases.get_child_schedule import (
    GetChildSchedule,
)
from backend.v2.contexts.enrollment.application.use_cases.list_parent_available_sessions import (
    ListParentAvailableSessions,
)
from backend.v2.contexts.enrollment.application.use_cases.pause_requests import (
    ListParentPauseRequests,
    RequestEnrollmentPause,
)
from backend.v2.contexts.enrollment.application.use_cases.promote_from_waitlist import (
    PromoteFromWaitlist,
)
from backend.v2.contexts.enrollment.domain.errors import SessionNotFound
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
from backend.v2.contexts.onboarding.domain.errors import MissingSelectedSession
from backend.v2.contexts.onboarding.infrastructure.mongo_application_repo import (
    MongoApplicationRepository,
)
from backend.v2.contexts.onboarding.infrastructure.mongo_parent_waiver_repo import (
    MongoParentWaiverRepository,
)
from backend.v2.contexts.onboarding.infrastructure.mongo_registration_waiver_repo import (
    MongoRegistrationWaiverRepository,
)
from backend.v2.shared.config import get_settings
from backend.v2.shared.events import Outbox
from backend.v2.shared.idempotency import IdempotencyStore
from backend.v2.shared.security.redirect import validate_redirect_url
from backend.v2.shared.tenancy import tenant_scope

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
) -> ParentComposition:
    settings = get_settings()
    academy_id = _require_academy_id(academy_id)

    # Billing
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
    session_types_repo = MongoSessionTypeRepository(db)
    dedup = MongoStripeEventDedup(db)
    invoice_processing = MongoStripeInvoiceProcessingRepository(db)
    transaction_runner = _MongoTransactionRunner(db)

    start_checkout = StartCheckout(
        payment_repo=payments_repo,
        stripe=stripe,
        academy_id=academy_id,
        connected_accounts=connected_accounts_repo,
        settings=billing_settings_repo,
    )
    start_subscription_checkout = StartSubscriptionCheckout(
        subscriptions=subscriptions_repo,
        stripe=stripe,
        academy_id=academy_id,
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
        academy_id=academy_id,
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
    )

    # Enrollment
    sessions_query = MongoSessionRepository(db)
    sessions_writer = MongoSessionWriter(db)
    enrollments_writer = MongoEnrollmentWriter(db)
    enrollments_query = MongoEnrollmentRepository(db)
    enrollment_events = MongoEnrollmentEventRepository(db)
    students_writer = MongoStudentWriter(db)
    students_query = MongoStudentRepository(db)
    occurrences_query = MongoSessionOccurrenceRepository(db)
    waitlist = MongoWaitlistRepository(db)
    pause_requests = MongoPauseRequestRepository(db)

    get_child_schedule_uc = GetChildSchedule(
        enrollments=enrollments_query,
        occurrences=occurrences_query,
        sessions=sessions_query,
        students=students_query,
    )

    confirm_enrollment = ConfirmEnrollment(
        sessions=sessions_writer,
        enrollments=enrollments_writer,
        enrollment_query=enrollments_query,
        students=students_writer,
        outbox=outbox,
        idempotency_store=idempotency_store,
        enrollment_events=enrollment_events,
        academy_id=academy_id,
    )
    promote = PromoteFromWaitlist(
        waitlist=waitlist,
        sessions=sessions_writer,
        enrollments=enrollments_writer,
        outbox=outbox,
        enrollment_events=enrollment_events,
        academy_id=academy_id,
    )

    # Onboarding
    apps_repo = MongoApplicationRepository(db)
    waivers_repo = MongoRegistrationWaiverRepository(db)
    parent_waivers_repo = MongoParentWaiverRepository(db)
    get_waiver_req = GetParentWaiverRequirement(waivers=parent_waivers_repo)
    accept_waiver = AcceptParentWaiver(waivers=parent_waivers_repo, academy_id=academy_id)
    start_app = StartApplication(apps=apps_repo, academy_id=academy_id)
    patch_app = PatchApplication(apps=apps_repo, waivers=waivers_repo)
    get_status = GetApplicationStatus(apps=apps_repo)
    transition = TransitionApplication(apps=apps_repo)
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
        async for doc in db["ledger_payments"].find(
            {"academy_id": academy_id, "parent_id": parent_id},
            sort=[("created_at", -1)],
            limit=100,
        ):
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
            if not row.stripe_payment_intent_id or row.stripe_payment_intent_id not in ledger_keys
        )
        rows.sort(
            key=lambda r: r.created_at or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )
        return rows

    async def list_credits_for_parent(parent_id: str):
        return await credits_repo.list_for_parent(parent_id)

    async def _parent_students(parent_id: str) -> list[dict[str, Any]]:
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

    async def list_enrollments_for_parent(parent_id: str) -> list[dict[str, Any]]:
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
        invoice = await billing_ledger_repo.get_invoice(invoice_id)
        if invoice is None or invoice.parent_id != parent_id:
            return None
        lines_cursor = db["invoice_lines"].find(
            {"academy_id": academy_id, "invoice_id": invoice_id}
        )
        lines = [InvoiceLine(**doc) async for doc in lines_cursor]
        return {"invoice": invoice, "lines": lines}

    def _validate_checkout_redirect_urls(*urls: str) -> None:
        _allowed = settings.cors_allowed_origins()
        for url in urls:
            validate_redirect_url(url, allowed_origins=_allowed)

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
            raise ValueError("invoice payment link unavailable")
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
            raise ValueError("balance payment unavailable")
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
                raise ValueError("balance payment unavailable")
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
            log.warning(
                "start_balance_payment: checkout creation failed parent=%s invoice_count=%d err=%s",
                parent_id,
                len(payable),
                exc,
            )
            raise ValueError("balance payment unavailable") from exc
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
        billing_start = _start_date_to_datetime(start_date)
        return await quote_enrollment_uc.execute(
            QuoteEnrollmentCommand(
                session_id=session_id,
                billing_start_at=billing_start,
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
                billing_start_at=datetime.now(UTC),
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
            zero_quote_period = datetime.now(UTC).strftime("%Y-%m")
            await apps_repo.save(app.model_copy(update={"zero_quote_period": zero_quote_period}))
            if quote.snapshot_id:
                await payments_repo.consume_quote_snapshot(quote.snapshot_id)
            await transition.execute(app.application_id, "CHECKOUT_PENDING")
            await transition.execute(app.application_id, "PENDING_APPROVAL")
            return StartCheckoutResult(
                payment_id="",
                checkout_session_id="",
                redirect_url=success_url,
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
        if quote.snapshot_id:
            await payments_repo.consume_quote_snapshot(quote.snapshot_id)
        await transition.execute(
            app.application_id,
            "CHECKOUT_PENDING",
            stripe_checkout_session_id=result.checkout_session_id,
            payment_id=result.payment_id,
        )
        return result

    async def start_autopay_for_enrollment(
        *,
        parent_id: str,
        enrollment_id: str,
        success_url: str,
        cancel_url: str,
    ):
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
        with tenant_scope(academy_id):
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

    # Session-type billing enrollment
    class _StudentOwnerLookup:
        async def is_owned(self, parent_id: str, student_id: str) -> bool:
            doc = await db["students"].find_one(
                {
                    "academy_id": academy_id,
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
        academy_id=academy_id,
        connected_accounts=connected_accounts_repo,
        settings=billing_settings_repo,
    )
    cancel_billing_enrollment_uc = CancelBillingEnrollment(
        enrollments=student_billing_enrollments,
        stripe=stripe,
    )

    sp_composition = compose_student_progress(db, outbox)
    curriculum_composition = compose_curriculum(db)

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


def _require_academy_id(academy_id: str | None) -> str:
    if not academy_id:
        raise ValueError("academy_id is required for parent composition")
    return academy_id


def _session_amount_cents(doc: dict[str, object]) -> int:
    if doc.get("amount_cents") is not None:
        return int(doc["amount_cents"])  # type: ignore[arg-type]
    if doc.get("monthly_price_cents") is not None:
        return int(doc["monthly_price_cents"])  # type: ignore[arg-type]
    if doc.get("monthly_price") is not None:
        return round(float(doc["monthly_price"]) * 100)  # type: ignore[arg-type]
    return 2500


def _start_date_to_datetime(value: str | None) -> datetime:
    if not value:
        return datetime.now(UTC)
    local = datetime.combine(
        datetime.fromisoformat(value).date(),
        time.min,
        tzinfo=ZoneInfo("America/Chicago"),
    )
    return local.astimezone(UTC)
