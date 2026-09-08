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

import logging
from datetime import UTC, datetime

import pytest

from backend.v2.composition.event_handlers import (
    HandlerDeps,
    install_handlers,
    on_enrollment_cancelled,
    on_payment_succeeded,
)
from backend.v2.composition.level_up_lifecycle import compose_expire_level_up_recommendations
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
            expire_level_up_recommendations=compose_expire_level_up_recommendations(db),
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


def _pending_rec(rec_id: str, student_id: str) -> dict:
    return {
        "rec_id": rec_id,
        "academy_id": "acad",
        "student_id": student_id,
        "from_level_id": "lvl-1",
        "to_level_id": "lvl-2",
        "program_id": "prog-1",
        "status": "RECOMMENDED",
        "recommended_by": "coach-1",
        "recommended_at": datetime(2026, 8, 20, 9, 0, tzinfo=UTC),
        "reviewed_by": None,
        "reviewed_at": None,
        "rejection_reason": None,
    }


def _cancelled(student_id: str, session_id: str = "sess-673") -> EnrollmentCancelled:
    return EnrollmentCancelled(
        aggregate_id=f"enr-{student_id}",
        academy_id="acad",
        payload=EnrollmentCancelledPayload(
            enrollment_id=f"enr-{student_id}",
            session_id=session_id,
            student_id=student_id,
            reason="admin_cancel",
        ),
    )


@pytest.mark.asyncio
async def test_on_enrollment_cancelled_expires_the_withdrawn_students_pending_level_up(
    db, acad
) -> None:
    """Issue #673: the handler closes a pending recommendation once the
    student has no live enrollment left, and leaves a student who is still
    enrolled elsewhere (or paused) alone."""
    await _wire(db)
    await db["level_up_recommendations"].insert_many(
        [
            _pending_rec("rec-gone", "st-gone"),
            _pending_rec("rec-still-here", "st-still-here"),
            _pending_rec("rec-paused", "st-paused"),
        ]
    )
    await db["enrollments"].insert_many(
        [
            {
                "enrollment_id": "enr-st-gone",
                "academy_id": "acad",
                "session_id": "sess-673",
                "student_id": "st-gone",
                "status": "withdrawn",
            },
            {
                "enrollment_id": "enr-st-still-here",
                "academy_id": "acad",
                "session_id": "sess-673",
                "student_id": "st-still-here",
                "status": "cancelled",
            },
            {
                "enrollment_id": "enr-st-still-here-2",
                "academy_id": "acad",
                "session_id": "sess-other",
                "student_id": "st-still-here",
                "status": "active",
            },
            {
                "enrollment_id": "enr-st-paused",
                "academy_id": "acad",
                "session_id": "sess-673",
                "student_id": "st-paused",
                "status": "paused",
            },
        ]
    )

    await on_enrollment_cancelled(_cancelled("st-gone"))
    await on_enrollment_cancelled(_cancelled("st-still-here"))
    await on_enrollment_cancelled(_cancelled("st-paused"))

    gone = await db["level_up_recommendations"].find_one({"rec_id": "rec-gone"})
    assert gone["status"] == "REJECTED"
    assert gone["rejection_reason"] == "enrollment_ended"
    assert gone["reviewed_by"] == "system:enrollment_ended"
    still = await db["level_up_recommendations"].find_one({"rec_id": "rec-still-here"})
    assert still["status"] == "RECOMMENDED"
    paused = await db["level_up_recommendations"].find_one({"rec_id": "rec-paused"})
    assert paused["status"] == "RECOMMENDED"


class _RecordingUseCase:
    """Stands in for either side of ``on_enrollment_cancelled``: records the
    ids it was called with and optionally raises."""

    def __init__(self, raises: Exception | None = None) -> None:
        self.calls: list[str] = []
        self.raises = raises

    async def execute(self, ident: str) -> None:
        self.calls.append(ident)
        if self.raises is not None:
            raise self.raises
        return None


def _install_cancel_handler_stubs(*, promote: _RecordingUseCase, expire: _RecordingUseCase) -> None:
    # Only the two use cases this handler touches matter; the rest of
    # HandlerDeps is never reached by on_enrollment_cancelled.
    install_handlers(
        HandlerDeps(
            confirm_enrollment=None,  # type: ignore[arg-type]
            promote_from_waitlist=promote,  # type: ignore[arg-type]
            issue_refund=None,  # type: ignore[arg-type]
            transition_application=None,  # type: ignore[arg-type]
            expire_level_up_recommendations=expire,  # type: ignore[arg-type]
        )
    )


@pytest.mark.asyncio
async def test_on_enrollment_cancelled_level_up_expiry_failure_never_replays_promotion(
    caplog,
) -> None:
    """Issue #673 isolation, direction one: a level-up expiry that raises is
    logged and swallowed; the seat promotion still runs exactly once and the
    handler returns normally, so the outbox does not retry (and re-promote)."""
    promote = _RecordingUseCase()
    expire = _RecordingUseCase(raises=RuntimeError("level-up repo down"))
    _install_cancel_handler_stubs(promote=promote, expire=expire)

    with caplog.at_level(logging.ERROR, logger="backend.v2.composition.event_handlers"):
        await on_enrollment_cancelled(_cancelled("st-gone"))

    assert expire.calls == ["st-gone"]
    assert promote.calls == ["sess-673"]
    failure_logs = [r for r in caplog.records if "level-up expiry failed" in r.getMessage()]
    assert len(failure_logs) == 1
    assert failure_logs[0].exc_info is not None
    assert "st-gone" in failure_logs[0].getMessage()
    assert "enr-st-gone" in failure_logs[0].getMessage()


@pytest.mark.asyncio
async def test_on_enrollment_cancelled_promotion_failure_does_not_starve_level_up_expiry(
    caplog,
) -> None:
    """Issue #673 isolation, direction two: the expiry runs *before* the
    promotion in its own try/except, so a promotion that fails on every retry
    (and eventually dead-letters) cannot leave the stale recommendation
    behind. The promotion keeps its raise-for-retry semantics: the handler
    still propagates the error, and nothing about the expiry is logged as a
    failure."""
    promote = _RecordingUseCase(raises=RuntimeError("waitlist repo down"))
    expire = _RecordingUseCase()
    _install_cancel_handler_stubs(promote=promote, expire=expire)

    with caplog.at_level(logging.ERROR, logger="backend.v2.composition.event_handlers"):
        with pytest.raises(RuntimeError, match="waitlist repo down"):
            await on_enrollment_cancelled(_cancelled("st-gone"))

    assert expire.calls == ["st-gone"]
    assert promote.calls == ["sess-673"]
    assert not [r for r in caplog.records if "level-up expiry failed" in r.getMessage()]


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
