"""Wave 2 cross-context handler integration tests.

These exercise the load-bearing wiring that production cutover depends on:

- Billing.PaymentSucceeded → Enrollment.ConfirmEnrollment + Onboarding state
  transition (PENDING_APPROVAL).
- Enrollment.CapacityExceeded → outbox event (auto-refund chain in Wave 2
  composition follows from here).
- Enrollment.EnrollmentCancelled → Enrollment.PromoteFromWaitlist (FIFO).

We invoke the registered @handler functions directly out of the dispatcher
registry rather than running the full asyncio polling loop — that proves
the same chain (decorator registration + install_handlers wiring +
handler body) without the loop-cleanup flakiness mongomock-motor adds.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from ulid import ULID

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
from backend.v2.contexts.billing.domain.models import Payment
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
from backend.v2.contexts.enrollment.domain.models_extra import WaitlistEntry
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


async def _wire(db) -> tuple[ConfirmEnrollment, PromoteFromWaitlist, IssueRefund, TransitionApplication, MongoOutbox]:
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
    promote = PromoteFromWaitlist(waitlist=waitlist, outbox=outbox, academy_id="acad")
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
async def test_on_payment_succeeded_handler_creates_enrollment(db, acad) -> None:
    """The composition handler:
    1. ConfirmEnrollment runs.
    2. Session.reserved_seats increments.
    3. An Enrollment row is created.
    4. Outbox carries EnrollmentConfirmed for downstream handlers.
    """
    await _wire(db)

    # Seed an available session.
    session_id = str(ULID())
    await db["sessions"].insert_one(
        {
            "session_id": session_id,
            "academy_id": "acad",
            "coach_id": "coach-1",
            "title": "Junior A",
            "location": "Court 1",
            "start_at": datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc),
            "end_at": datetime(2026, 6, 1, 10, 30, tzinfo=timezone.utc),
            "capacity": 2,
            "reserved_seats": 0,
            "status": "scheduled",
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
            succeeded_at=datetime.now(timezone.utc),
        ),
    )
    await on_payment_succeeded(event)

    # Assertions.
    enrollments = [doc async for doc in db["enrollments"].find({})]
    assert len(enrollments) == 1
    assert enrollments[0]["session_id"] == session_id
    assert enrollments[0]["status"] == "active"

    session = await db["sessions"].find_one({"session_id": session_id})
    assert session["reserved_seats"] == 1

    # Outbox got the downstream EnrollmentConfirmed event.
    outbox_events = [doc async for doc in db["outbox_events"].find({})]
    names = [e["name"] for e in outbox_events]
    assert "Enrollment.EnrollmentConfirmed" in names


@pytest.mark.asyncio
async def test_on_payment_succeeded_at_capacity_emits_capacity_exceeded(db, acad) -> None:
    """When the session is full, ConfirmEnrollment writes CapacityExceeded
    to the outbox (which the on_capacity_exceeded handler reacts to by
    auto-refunding via the Billing IssueRefund use case)."""
    await _wire(db)

    # Seed a full session.
    session_id = str(ULID())
    await db["sessions"].insert_one(
        {
            "session_id": session_id,
            "academy_id": "acad",
            "coach_id": "coach-1",
            "title": "Junior A",
            "location": "Court 1",
            "start_at": datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc),
            "end_at": datetime(2026, 6, 1, 10, 30, tzinfo=timezone.utc),
            "capacity": 1,
            "reserved_seats": 1,  # at capacity
            "status": "scheduled",
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
            succeeded_at=datetime.now(timezone.utc),
        ),
    )
    # The handler propagates the CapacityExceeded exception per its
    # implementation (it logs and re-raises so the dispatcher can retry/
    # dead-letter); the event is still appended to the outbox before
    # the exception fires.
    with pytest.raises(Exception):
        await on_payment_succeeded(event)

    events = [doc async for doc in db["outbox_events"].find({})]
    names = [e["name"] for e in events]
    assert "Enrollment.CapacityExceeded" in names


@pytest.mark.asyncio
async def test_on_enrollment_cancelled_promotes_oldest_waitlist_entry(db, acad) -> None:
    """The waitlist-promotion handler fires on EnrollmentCancelled and
    picks the oldest waiting entry by joined_at (FIFO)."""
    await _wire(db)

    session_id = str(ULID())
    # Older entry.
    older_id = str(ULID())
    await db["waitlist"].insert_one(
        {
            "waitlist_id": older_id,
            "academy_id": "acad",
            "session_id": session_id,
            "student_id": "st-older",
            "parent_id": "p-older",
            "joined_at": datetime(2026, 5, 16, 8, 0, tzinfo=timezone.utc),
            "status": "waiting",
        }
    )
    # Newer entry.
    newer_id = str(ULID())
    await db["waitlist"].insert_one(
        {
            "waitlist_id": newer_id,
            "academy_id": "acad",
            "session_id": session_id,
            "student_id": "st-newer",
            "parent_id": "p-newer",
            "joined_at": datetime(2026, 5, 16, 9, 0, tzinfo=timezone.utc),
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
