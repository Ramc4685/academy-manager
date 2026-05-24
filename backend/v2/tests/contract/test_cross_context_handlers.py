"""Wave 2 cross-context handler integration tests.

These exercise the load-bearing wiring that production cutover depends on:

- Billing.PaymentSucceeded → Onboarding state transition (PENDING_APPROVAL);
  admin approval owns enrollment creation.
- Enrollment.CapacityExceeded → outbox event (auto-refund chain in Wave 2
  composition follows from here).
- Enrollment.EnrollmentCancelled → Enrollment.PromoteFromWaitlist (FIFO).

We invoke the registered @handler functions directly out of the dispatcher
registry rather than running the full asyncio polling loop — that proves
the same chain (decorator registration + install_handlers wiring +
handler body) without the loop-cleanup flakiness mongomock-motor adds.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.composition.event_handlers import (
    HandlerDeps,
    install_handlers,
    on_enrollment_cancelled,
    on_payment_succeeded,
)
from backend.v2.contexts.billing.application.use_cases.issue_refund import IssueRefund
from backend.v2.contexts.billing.domain.events import (
    PaymentSucceeded,
    PaymentSucceededPayload,
)
from backend.v2.contexts.billing.infrastructure.fake_stripe_gateway import (
    FakeStripeGateway,
)
from backend.v2.contexts.billing.infrastructure.mongo_payment_repo import (
    MongoPaymentRepository,
)
from backend.v2.contexts.enrollment.application.use_cases.confirm_enrollment import (
    ConfirmEnrollment,
)
from backend.v2.contexts.enrollment.application.use_cases.promote_from_waitlist import (
    PromoteFromWaitlist,
)
from backend.v2.contexts.enrollment.domain.events import (
    EnrollmentCancelled,
    EnrollmentCancelledPayload,
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
    TransitionApplication,
)
from backend.v2.contexts.onboarding.infrastructure.mongo_application_repo import (
    MongoApplicationRepository,
)
from backend.v2.shared.events import MongoOutbox
from backend.v2.shared.idempotency.mongo_store import MongoIdempotencyStore
from backend.v2.shared.ids import new_ulid


async def _wire(
    db,
) -> tuple[ConfirmEnrollment, PromoteFromWaitlist, IssueRefund, TransitionApplication, MongoOutbox]:
    from backend.v2.migrations import run_pending_migrations

    await run_pending_migrations(db)

    payments_repo = MongoPaymentRepository(db)
    sessions_w = MongoSessionWriter(db)
    enrollments_w = MongoEnrollmentWriter(db)
    enrollments_q = MongoEnrollmentRepository(db)
    students_w = MongoStudentWriter(db)
    waitlist = MongoWaitlistRepository(db)
    outbox = MongoOutbox(db)
    idem = MongoIdempotencyStore(db)
    apps_repo = MongoApplicationRepository(db)

    confirm = ConfirmEnrollment(
        sessions=sessions_w,
        enrollments=enrollments_w,
        enrollment_query=enrollments_q,
        students=students_w,
        outbox=outbox,
        idempotency_store=idem,
        academy_id="acad",
    )
    promote = PromoteFromWaitlist(
        waitlist=waitlist,
        sessions=sessions_w,
        enrollments=enrollments_w,
        outbox=outbox,
        academy_id="acad",
    )
    issue_refund = IssueRefund(
        payment_repo=payments_repo,
        stripe=FakeStripeGateway(),
        outbox=outbox,
        idempotency_store=idem,
    )
    transition = TransitionApplication(apps=apps_repo)

    install_handlers(
        HandlerDeps(
            confirm_enrollment=confirm,
            promote_from_waitlist=promote,
            issue_refund=issue_refund,
            transition_application=transition,
        )
    )
    return confirm, promote, issue_refund, transition, outbox


@pytest.mark.asyncio
async def test_on_payment_succeeded_handler_marks_application_pending_approval(db, acad) -> None:
    """The composition handler:
    1. Moves the paid application to admin review.
    2. Does not reserve a seat.
    3. Does not create an enrollment before admin approval.
    """
    await _wire(db)

    # Seed an available session.
    session_id = str(new_ulid())
    await db["sessions"].insert_one(
        {
            "session_id": session_id,
            "academy_id": "acad",
            "coach_id": "coach-1",
            "title": "Junior A",
            "location": "Court 1",
            "start_at": datetime(2026, 5, 16, 9, 0, tzinfo=UTC),
            "end_at": datetime(2026, 5, 16, 10, 30, tzinfo=UTC),
            "capacity": 2,
            "reserved_seats": 0,
            "status": "scheduled",
        }
    )
    now = datetime.now(UTC)
    await db["onboarding_applications"].insert_one(
        {
            "application_id": "app-1",
            "academy_id": "acad",
            "parent_user_id": "parent-1",
            "parent_email": "parent@example.com",
            "status": "CHECKOUT_PENDING",
            "selected_session_id": session_id,
            "payment_id": "pay-1",
            "expires_at": now,
            "created_at": now,
            "updated_at": now,
        }
    )
    # Fire the handler the same way the dispatcher would.
    event = PaymentSucceeded(
        aggregate_id="pay-1",
        academy_id="acad",
        payload=PaymentSucceededPayload(
            payment_id="pay-1",
            parent_id="parent-1",
            session_id=session_id,
            amount_cents=15000,
            currency="usd",
            succeeded_at=datetime.now(UTC),
        ),
    )
    await on_payment_succeeded(event)

    # Assertions.
    enrollments = [doc async for doc in db["enrollments"].find({})]
    assert enrollments == []

    session = await db["sessions"].find_one({"session_id": session_id})
    assert session["reserved_seats"] == 0

    application = await db["onboarding_applications"].find_one({"application_id": "app-1"})
    assert application["status"] == "PENDING_APPROVAL"


@pytest.mark.asyncio
async def test_on_payment_succeeded_at_capacity_still_defers_to_admin_review(db, acad) -> None:
    """Capacity is evaluated by the admin approval use case, not checkout."""
    await _wire(db)

    # Seed a full session.
    session_id = str(new_ulid())
    await db["sessions"].insert_one(
        {
            "session_id": session_id,
            "academy_id": "acad",
            "coach_id": "coach-1",
            "title": "Junior A",
            "location": "Court 1",
            "start_at": datetime(2026, 6, 1, 9, 0, tzinfo=UTC),
            "end_at": datetime(2026, 6, 1, 10, 30, tzinfo=UTC),
            "capacity": 1,
            "reserved_seats": 1,  # at capacity
            "status": "scheduled",
        }
    )
    now = datetime.now(UTC)
    await db["onboarding_applications"].insert_one(
        {
            "application_id": "app-2",
            "academy_id": "acad",
            "parent_user_id": "parent-2",
            "parent_email": "parent2@example.com",
            "status": "CHECKOUT_PENDING",
            "selected_session_id": session_id,
            "payment_id": "pay-2",
            "expires_at": now,
            "created_at": now,
            "updated_at": now,
        }
    )

    event = PaymentSucceeded(
        aggregate_id="pay-2",
        academy_id="acad",
        payload=PaymentSucceededPayload(
            payment_id="pay-2",
            parent_id="parent-2",
            session_id=session_id,
            amount_cents=15000,
            currency="usd",
            succeeded_at=datetime.now(UTC),
        ),
    )
    await on_payment_succeeded(event)

    events = [doc async for doc in db["outbox_events"].find({})]
    assert events == []
    enrollments = [doc async for doc in db["enrollments"].find({})]
    assert enrollments == []
    application = await db["onboarding_applications"].find_one({"application_id": "app-2"})
    assert application["status"] == "PENDING_APPROVAL"


@pytest.mark.asyncio
async def test_on_enrollment_cancelled_promotes_oldest_waitlist_entry(db, acad) -> None:
    """The waitlist-promotion handler fires on EnrollmentCancelled and
    picks the oldest waiting entry by joined_at (FIFO)."""
    await _wire(db)

    session_id = str(new_ulid())
    await db["sessions"].insert_one(
        {
            "session_id": session_id,
            "academy_id": "acad",
            "coach_id": "coach-1",
            "title": "Junior A",
            "location": "Court 1",
            "start_at": datetime(2026, 6, 1, 9, 0, tzinfo=UTC),
            "end_at": datetime(2026, 6, 1, 10, 30, tzinfo=UTC),
            "capacity": 2,
            "reserved_seats": 0,
            "status": "scheduled",
        }
    )
    # Older entry.
    older_id = str(new_ulid())
    await db["waitlist"].insert_one(
        {
            "waitlist_id": older_id,
            "academy_id": "acad",
            "session_id": session_id,
            "student_id": "st-older",
            "parent_id": "p-older",
            "joined_at": datetime(2026, 5, 16, 8, 0, tzinfo=UTC),
            "status": "waiting",
        }
    )
    # Newer entry.
    newer_id = str(new_ulid())
    await db["waitlist"].insert_one(
        {
            "waitlist_id": newer_id,
            "academy_id": "acad",
            "session_id": session_id,
            "student_id": "st-newer",
            "parent_id": "p-newer",
            "joined_at": datetime(2026, 5, 16, 9, 0, tzinfo=UTC),
            "status": "waiting",
        }
    )

    event = EnrollmentCancelled(
        aggregate_id="enr-1",
        academy_id="acad",
        payload=EnrollmentCancelledPayload(
            enrollment_id="enr-1",
            session_id=session_id,
            student_id="st-cancelled",
            reason="admin_cancel",
        ),
    )
    await on_enrollment_cancelled(event)

    older = await db["waitlist"].find_one({"waitlist_id": older_id})
    newer = await db["waitlist"].find_one({"waitlist_id": newer_id})
    assert older["status"] == "promoted"
    assert newer["status"] == "waiting"

    # Outbox got the WaitlistPromoted event.
    events = [doc async for doc in db["outbox_events"].find({})]
    assert any(e["name"] == "Enrollment.WaitlistPromoted" for e in events)
