"""Compose the Parent BFF use cases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.v2.contexts.billing.application.ports import StripeGateway
from backend.v2.contexts.billing.application.use_cases.handle_webhook_event import (
    HandleWebhookEvent,
)
from backend.v2.contexts.billing.application.use_cases.issue_refund import IssueRefund
from backend.v2.contexts.billing.application.use_cases.start_checkout import StartCheckout
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
from backend.v2.contexts.enrollment.infrastructure.mongo_enrollment_repo import (
    MongoEnrollmentRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_enrollment_writer import (
    MongoEnrollmentWriter,
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
from backend.v2.contexts.onboarding.application.use_cases.manage_application import (
    GetApplicationStatus,
    PatchApplication,
    StartApplication,
    TransitionApplication,
)
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
    handle_webhook_event: HandleWebhookEvent
    list_payments_for_parent: object  # callable


def compose_parent(
    db: AsyncIOMotorDatabase,
    outbox: Outbox,
    idempotency_store: IdempotencyStore,
    stripe: StripeGateway,
) -> ParentComposition:
    settings = get_settings()
    academy_id = settings.default_academy_id

    # Billing
    payments_repo = MongoPaymentRepository(db)
    subscriptions_repo = MongoSubscriptionRepository(db)
    dedup = MongoStripeEventDedup(db)

    start_checkout = StartCheckout(
        payment_repo=payments_repo,
        stripe=stripe,
        academy_id=academy_id,
    )
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

    # Enrollment
    sessions_writer = MongoSessionWriter(db)
    enrollments_writer = MongoEnrollmentWriter(db)
    enrollments_query = MongoEnrollmentRepository(db)
    students_writer = MongoStudentWriter(db)
    waitlist = MongoWaitlistRepository(db)

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

    return ParentComposition(
        start_application=start_app,
        patch_application=patch_app,
        get_application_status=get_status,
        transition_application=transition,
        start_checkout=start_checkout,
        handle_webhook_event=handle_webhook,
        list_payments_for_parent=list_payments_for_parent,
    )


class _StripeGatewayProto(Protocol):
    """Re-export to make this module importable without backing import."""
