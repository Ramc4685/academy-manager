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
from backend.v2.shared.events.dispatcher import EventDispatcher
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
        academy_id=lambda: "acad",
    )
    promote = PromoteFromWaitlist(
        waitlist=waitlist,
        sessions=sessions_w,
        enrollments=enrollments_w,
        outbox=outbox,
        academy_id=lambda: "acad",
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
async def test_dispatcher_rehydrates_payment_succeeded_payload_from_outbox(db, acad) -> None:
    """MongoOutbox stores the full event under payload; dispatch must rebuild
    the concrete event so handlers receive typed payload models.
    """
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
            "capacity": 1,
            "reserved_seats": 0,
            "status": "scheduled",
        }
    )
    now = datetime.now(UTC)
    await db["onboarding_applications"].insert_one(
        {
            "application_id": "app-dispatch",
            "academy_id": "acad",
            "parent_user_id": "parent-dispatch",
            "parent_email": "dispatch@example.com",
            "status": "CHECKOUT_PENDING",
            "selected_session_id": session_id,
            "payment_id": "pay-dispatch",
            "expires_at": now,
            "created_at": now,
            "updated_at": now,
        }
    )

    outbox = MongoOutbox(db)
    await outbox.append(
        PaymentSucceeded(
            aggregate_id="pay-dispatch",
            academy_id="acad",
            payload=PaymentSucceededPayload(
                payment_id="pay-dispatch",
                parent_id="parent-dispatch",
                session_id=session_id,
                amount_cents=15000,
                currency="usd",
                succeeded_at=datetime.now(UTC),
            ),
        )
    )

    event_doc = await db["outbox_events"].find_one({"aggregate_id": "pay-dispatch"})
    assert event_doc is not None
    await EventDispatcher(db)._process_event(event_doc)

    application = await db["onboarding_applications"].find_one({"application_id": "app-dispatch"})
    assert application["status"] == "PENDING_APPROVAL"
    assert await db["dead_letter_events"].count_documents({}) == 0
    processed = await db["outbox_events"].find_one({"aggregate_id": "pay-dispatch"})
    assert processed["processed"] is True
    assert processed["status"] == "processed"


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


@pytest.mark.asyncio
async def test_on_enrollment_cancelled_parent_cancel_reason_promotes_end_to_end(db, acad) -> None:
    """Parent self-cancel (PR #500) emits EnrollmentCancelled with
    reason="parent_cancel" AFTER releasing the seat; the same handler must
    promote the waitlist. Pins the full chain: waitlist entry promoted,
    an active enrollment created for the promoted student, the freed seat
    re-reserved, and WaitlistPromoted appended to the outbox."""
    await _wire(db)

    session_id = str(new_ulid())
    await db["sessions"].insert_one(
        {
            "session_id": session_id,
            "academy_id": "acad",
            "coach_id": "coach-1",
            "title": "Junior A",
            "location": "Court 1",
            "start_at": datetime(2026, 9, 1, 9, 0, tzinfo=UTC),
            "end_at": datetime(2026, 9, 1, 10, 30, tzinfo=UTC),
            "capacity": 1,
            # Self-cancel already ran release_seat before appending the event.
            "reserved_seats": 0,
            "status": "scheduled",
        }
    )
    waitlist_id = str(new_ulid())
    await db["waitlist"].insert_one(
        {
            "waitlist_id": waitlist_id,
            "academy_id": "acad",
            "session_id": session_id,
            "student_id": "st-waiting",
            "parent_id": "p-waiting",
            "joined_at": datetime(2026, 8, 1, 8, 0, tzinfo=UTC),
            "status": "waiting",
        }
    )

    event = EnrollmentCancelled(
        aggregate_id="enr-parent",
        academy_id="acad",
        payload=EnrollmentCancelledPayload(
            enrollment_id="enr-parent",
            session_id=session_id,
            student_id="st-cancelled",
            reason="parent_cancel",
        ),
    )
    await on_enrollment_cancelled(event)

    entry = await db["waitlist"].find_one({"waitlist_id": waitlist_id})
    assert entry["status"] == "promoted"

    enrollment = await db["enrollments"].find_one(
        {"session_id": session_id, "student_id": "st-waiting"}
    )
    assert enrollment is not None
    assert enrollment["status"] == "active"

    session = await db["sessions"].find_one({"session_id": session_id})
    assert session["reserved_seats"] == 1

    events = [doc async for doc in db["outbox_events"].find({})]
    assert any(e["name"] == "Enrollment.WaitlistPromoted" for e in events)


# ---------------------------------------------------------------------------
# Dunning failure notice (issue #435)
# ---------------------------------------------------------------------------


def _dunning_event(*, terminal: bool = False):
    from backend.v2.contexts.billing.domain.events import (
        DunningNoticeRequested,
        DunningNoticeRequestedPayload,
    )

    return DunningNoticeRequested(
        aggregate_id="inv-1",
        academy_id="acad",
        payload=DunningNoticeRequestedPayload(
            invoice_id="inv-1",
            parent_id="parent-1",
            period="2026-08",
            balance_due_cents=12_500,
            currency="usd",
            attempt_no=2,
            terminal=terminal,
        ),
    )


class _RecordingNotifier:
    def __init__(self, raises: Exception | None = None) -> None:
        self.calls: list[dict] = []
        self.academies: list[str | None] = []
        self.raises = raises

    async def send_dunning_notice(self, **kwargs) -> None:
        from backend.v2.shared.tenancy import current_academy_id

        self.academies.append(current_academy_id())
        if self.raises is not None:
            raise self.raises
        self.calls.append(kwargs)


@pytest.mark.asyncio
async def test_dunning_notice_handler_sends_inside_the_event_tenant_scope() -> None:
    """The handler runs on the dispatcher, outside any request, so the tenant
    must come from the event — the adapter resolves the parent's membership and
    academy name with ``current_academy_id()``."""
    from backend.v2.composition.event_handlers import (
        install_dunning_notifier,
        on_dunning_notice_requested,
    )

    notifier = _RecordingNotifier()
    install_dunning_notifier(notifier)
    try:
        await on_dunning_notice_requested(_dunning_event(terminal=True))
    finally:
        install_dunning_notifier(None)

    assert notifier.academies == ["acad"]
    assert notifier.calls == [
        {
            "parent_id": "parent-1",
            "invoice_id": "inv-1",
            "period": "2026-08",
            "balance_due_cents": 12_500,
            "currency": "usd",
            "attempt_no": 2,
            "terminal": True,
        }
    ]


@pytest.mark.asyncio
async def test_dunning_notice_handler_propagates_failure_for_retry() -> None:
    """Raising is how the notice reaches the dispatcher's retry ladder. If this
    handler ever swallowed the error we would be back to the original bug: a
    parent never told that their payment failed."""
    from backend.v2.composition.event_handlers import (
        install_dunning_notifier,
        on_dunning_notice_requested,
    )

    install_dunning_notifier(_RecordingNotifier(raises=RuntimeError("resend 503")))
    try:
        with pytest.raises(RuntimeError, match="resend 503"):
            await on_dunning_notice_requested(_dunning_event())
    finally:
        install_dunning_notifier(None)


@pytest.mark.asyncio
async def test_dunning_notice_handler_raises_when_not_installed() -> None:
    from backend.v2.composition.event_handlers import (
        install_dunning_notifier,
        on_dunning_notice_requested,
    )

    install_dunning_notifier(None)
    with pytest.raises(RuntimeError, match="install_dunning_notifier"):
        await on_dunning_notice_requested(_dunning_event())
