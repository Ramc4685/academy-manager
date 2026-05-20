"""Compose the Parent BFF use cases."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timezone
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.v2.contexts.billing.application.ports import StripeGateway
from backend.v2.contexts.billing.application.use_cases.handle_webhook_event import (
    HandleWebhookEvent,
)
from backend.v2.contexts.billing.application.use_cases.quote_enrollment import (
    QuoteEnrollment,
    QuoteEnrollmentCommand,
)
from backend.v2.contexts.billing.application.use_cases.issue_refund import IssueRefund
from backend.v2.contexts.billing.application.use_cases.parent_billing import (
    CreateCustomerPortalSession,
    CreateCustomerPortalSessionCommand,
    GetCheckoutStatus,
    StartSubscriptionCheckout,
    StartSubscriptionCheckoutCommand,
)
from backend.v2.contexts.billing.application.use_cases.start_checkout import (
    StartCheckout,
    StartCheckoutCommand,
)
from backend.v2.contexts.billing.infrastructure.mongo_credit_ledger_repo import (
    MongoCreditLedgerRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_payment_repo import (
    MongoPaymentRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_stripe_dedup import (
    MongoStripeEventDedup,
)
from backend.v2.contexts.billing.infrastructure.mongo_subscription_repo import (
    MongoSubscriptionRepository,
)
from backend.v2.contexts.enrollment.application.use_cases.confirm_enrollment import (
    ConfirmEnrollment,
)
from backend.v2.contexts.enrollment.application.use_cases.promote_from_waitlist import (
    PromoteFromWaitlist,
)
from backend.v2.contexts.enrollment.application.use_cases.list_parent_available_sessions import (
    ListParentAvailableSessions,
)
from backend.v2.contexts.enrollment.application.use_cases.pause_requests import (
    ListParentPauseRequests,
    RequestEnrollmentPause,
)
from backend.v2.contexts.enrollment.domain.errors import SessionNotFound
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
from backend.v2.contexts.enrollment.infrastructure.mongo_student_writer import (
    MongoStudentWriter,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_waitlist_repo import (
    MongoWaitlistRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_pause_request_repo import (
    MongoPauseRequestRepository,
)
from backend.v2.contexts.onboarding.application.use_cases.manage_application import (
    GetApplicationStatus,
    PatchApplication,
    StartApplication,
    TransitionApplication,
)
from backend.v2.contexts.onboarding.domain.errors import MissingSelectedSession
from backend.v2.contexts.onboarding.infrastructure.mongo_application_repo import (
    MongoApplicationRepository,
)
from backend.v2.contexts.onboarding.infrastructure.mongo_waiver_repo import (
    MongoWaiverRepository,
)
from backend.v2.shared.config import get_settings
from backend.v2.shared.events import Outbox
from backend.v2.shared.idempotency import IdempotencyStore

from .event_handlers import HandlerDeps, install_handlers


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


def compose_parent(
    db: AsyncIOMotorDatabase[Any],
    outbox: Outbox,
    idempotency_store: IdempotencyStore,
    stripe: StripeGateway,
) -> ParentComposition:
    settings = get_settings()
    academy_id = settings.default_academy_id

    # Billing
    credits_repo = MongoCreditLedgerRepository(db)
    payments_repo = MongoPaymentRepository(db, credit_ledger=credits_repo)
    subscriptions_repo = MongoSubscriptionRepository(db)
    dedup = MongoStripeEventDedup(db)

    start_checkout = StartCheckout(
        payment_repo=payments_repo,
        stripe=stripe,
        academy_id=academy_id,
    )
    start_subscription_checkout = StartSubscriptionCheckout(
        subscriptions=subscriptions_repo,
        stripe=stripe,
        academy_id=academy_id,
    )
    create_portal = CreateCustomerPortalSession(stripe=stripe)
    checkout_status = GetCheckoutStatus(payments=payments_repo)
    issue_refund = IssueRefund(
        payment_repo=payments_repo,
        stripe=stripe,
        outbox=outbox,
        idempotency_store=idempotency_store,
    )
    handle_webhook = HandleWebhookEvent(
        stripe=stripe,
        dedup=dedup,
        payments=payments_repo,
        subscriptions=subscriptions_repo,
        outbox=outbox,
        academy_id=academy_id,
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
    students_writer = MongoStudentWriter(db)
    waitlist = MongoWaitlistRepository(db)
    pause_requests = MongoPauseRequestRepository(db)

    confirm_enrollment = ConfirmEnrollment(
        sessions=sessions_writer,
        enrollments=enrollments_writer,
        enrollment_query=enrollments_query,
        students=students_writer,
        outbox=outbox,
        idempotency_store=idempotency_store,
        academy_id=academy_id,
    )
    promote = PromoteFromWaitlist(
        waitlist=waitlist, outbox=outbox, academy_id=academy_id
    )

    # Onboarding
    apps_repo = MongoApplicationRepository(db)
    waivers_repo = MongoWaiverRepository(db)
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
        return await payments_repo.list_for_parent(parent_id)

    async def list_credits_for_parent(parent_id: str):
        return await credits_repo.list_for_parent(parent_id)

    async def _parent_students(parent_id: str) -> list[dict[str, Any]]:
        cursor = db["students"].find(
            {
                "academy_id": academy_id,
                "$or": [{"parent_id": parent_id}, {"parent_user_id": parent_id}],
            }
        ).sort([("full_name", 1)])
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
        cursor = db["enrollments"].find(
            {
                "academy_id": academy_id,
                "student_id": {"$in": list(by_id)},
                "status": {"$in": ["active", "paused"]},
            }
        ).sort([("created_at", -1), ("enrollment_id", 1)])
        rows: list[dict[str, Any]] = []
        async for enrollment in cursor:
            student_id = str(enrollment["student_id"])
            session = await db["sessions"].find_one(
                {"academy_id": academy_id, "session_id": enrollment["session_id"]}
            )
            rows.append(
                {
                    "enrollment_id": str(enrollment.get("enrollment_id") or enrollment["_id"]),
                    "student_id": student_id,
                    "student_name": str(by_id[student_id].get("full_name") or "Unnamed student"),
                    "session_id": str(enrollment["session_id"]),
                    "session_title": str(session.get("title") if session else "Session"),
                    "status": str(enrollment.get("status") or "active"),
                    "payment_mode": enrollment.get("payment_mode"),
                    "subscription_status": enrollment.get("subscription_status"),
                }
            )
        return rows

    async def list_attendance_for_parent(parent_id: str) -> list[dict[str, Any]]:
        students = await _parent_students(parent_id)
        by_id = {str(s.get("student_id") or s["_id"]): s for s in students}
        if not by_id:
            return []
        cursor = db["attendance"].find(
            {"academy_id": academy_id, "student_id": {"$in": list(by_id)}}
        ).sort([("marked_at", -1)]).limit(100)
        rows: list[dict[str, Any]] = []
        async for attendance in cursor:
            student_id = str(attendance["student_id"])
            session = await db["sessions"].find_one(
                {"academy_id": academy_id, "session_id": attendance["session_id"]}
            )
            rows.append(
                {
                    "attendance_id": str(attendance["attendance_id"]),
                    "student_id": student_id,
                    "student_name": str(by_id[student_id].get("full_name") or "Unnamed student"),
                    "session_id": str(attendance["session_id"]),
                    "session_title": str(session.get("title") if session else "Session"),
                    "status": str(attendance["status"]),
                    "marked_at": attendance["marked_at"],
                }
            )
        return rows

    async def list_progress_for_parent(parent_id: str) -> list[dict[str, Any]]:
        students = await _parent_students(parent_id)
        by_id = {str(s.get("student_id") or s["_id"]): s for s in students}
        if not by_id:
            return []
        cursor = db["progress_notes"].find(
            {"academy_id": academy_id, "student_id": {"$in": list(by_id)}}
        ).sort([("created_at", -1)]).limit(100)
        rows: list[dict[str, Any]] = []
        async for note in cursor:
            student_id = str(note["student_id"])
            rows.append(
                {
                    "note_id": str(note.get("note_id") or note["_id"]),
                    "student_id": student_id,
                    "student_name": str(by_id[student_id].get("full_name") or "Unnamed student"),
                    "coach_id": note.get("coach_id"),
                    "body": str(note.get("body") or note.get("note") or ""),
                    "created_at": note.get("created_at") or datetime.now(timezone.utc),
                }
            )
        return rows

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
                billing_start_at=datetime.now(timezone.utc),
                calculated_by=parent_id,
                parent_id=parent_id,
            )
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
        enrollment = await db["enrollments"].find_one(
            {"academy_id": academy_id, "enrollment_id": enrollment_id}
        )
        if not enrollment:
            raise SessionNotFound("enrollment not found", enrollment_id=enrollment_id)
        student = await db["students"].find_one(
            {"academy_id": academy_id, "student_id": enrollment.get("student_id")}
        )
        if not student or str(student.get("parent_id") or student.get("parent_user_id")) != parent_id:
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
        await db["enrollments"].update_one(
            {"academy_id": academy_id, "enrollment_id": enrollment_id},
            {
                "$set": {
                    "payment_mode": "monthly",
                    "subscription_status": "incomplete",
                    "subscription_id": result.subscription_id,
                    "updated_at": datetime.now(timezone.utc),
                }
            },
        )
        return result

    async def open_billing_portal(*, parent_id: str, return_url: str):
        user = await db["users"].find_one(
            {"academy_id": academy_id, "$or": [{"user_id": parent_id}, {"firebase_uid": parent_id}]}
        )
        result = await create_portal.execute(
            CreateCustomerPortalSessionCommand(
                parent_id=parent_id,
                return_url=return_url,
                stripe_customer_id=(user or {}).get("stripe_customer_id"),  # type: ignore[arg-type]
            )
        )
        return result.model_dump()

    async def get_checkout_status(*, parent_id: str, checkout_session_id: str):
        result = await checkout_status.execute(checkout_session_id, parent_id=parent_id)
        return result.model_dump()

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
    )


class _StripeGatewayProto(Protocol):
    """Re-export to make this module importable without backing import."""


def _session_amount_cents(doc: dict[str, object]) -> int:
    if doc.get("amount_cents") is not None:
        return int(doc["amount_cents"])  # type: ignore[arg-type]
    if doc.get("monthly_price_cents") is not None:
        return int(doc["monthly_price_cents"])  # type: ignore[arg-type]
    if doc.get("monthly_price") is not None:
        return int(round(float(doc["monthly_price"]) * 100))  # type: ignore[arg-type]
    return 2500


def _start_date_to_datetime(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    local = datetime.combine(
        datetime.fromisoformat(value).date(),
        time.min,
        tzinfo=ZoneInfo("America/Chicago"),
    )
    return local.astimezone(timezone.utc)
