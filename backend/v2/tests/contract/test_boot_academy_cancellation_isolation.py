"""Cancellations never carry the boot academy into another tenant (P1 hardcoded #1).

``compose_admin`` captures ``academy_id = primary_academy_id or
default_academy_id`` once, when the server starts. Before this fix the admin
cancel paths stamped that boot value onto the ``EnrollmentCancelled`` outbox
event, and the dispatcher runs the handler inside
``tenant_scope(event.academy_id)``. So when academy B cancelled a class or an
enrollment, the waitlist promotion and the level-up expiry ran in academy A
(the boot academy, BLNO in production): B's waitlist never moved, and A's
waitlist rows for the same session id were offered a seat instead. Approving a
fixed pause did the same to the scheduled resume row, so B's paused family was
never resumed.

These run against a real mongod (``real_db``, every migration applied) with the
production composition root, booted as academy A, acting as academy B.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from backend.v2.composition import event_handlers
from backend.v2.composition.admin import compose_admin
from backend.v2.composition.event_handlers import HandlerDeps
from backend.v2.composition.level_up_lifecycle import compose_expire_level_up_recommendations
from backend.v2.contexts.billing.infrastructure.fake_stripe_gateway import FakeStripeGateway
from backend.v2.contexts.enrollment.application.use_cases.admin_writes import (
    CancelEnrollmentCommand,
    CancelSessionCommand,
)
from backend.v2.contexts.enrollment.application.use_cases.pause_requests import (
    DecidePauseRequestCommand,
    PauseRequest,
)
from backend.v2.contexts.enrollment.application.use_cases.promote_from_waitlist import (
    PromoteFromWaitlist,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_enrollment_writer import (
    MongoEnrollmentWriter,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_pause_request_repo import (
    MongoPauseRequestRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_scheduled_action_repo import (
    MongoScheduledEnrollmentActionRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_session_writer import MongoSessionWriter
from backend.v2.contexts.enrollment.infrastructure.mongo_waitlist_repo import (
    MongoWaitlistRepository,
)
from backend.v2.shared.config.settings import get_settings
from backend.v2.shared.events.dispatcher import EventDispatcher
from backend.v2.shared.events.outbox import MongoOutbox
from backend.v2.shared.idempotency.mongo_store import MongoIdempotencyStore
from backend.v2.shared.tenancy.context import current_academy_id, tenant_scope

BOOT = "acad-boot-a"  # the academy the server started with (BLNO in prod)
OTHER = "acad-tenant-b"  # the academy that actually made the request
# Same ids in both tenants on purpose: a second academy onboarded from copied
# data is exactly when ids collide, and it makes the leak visible (the
# wrong-tenant handler finds A's rows instead of finding nothing).
SESSION = "sess-shared-1"
FUTURE = datetime.now(UTC) + timedelta(days=30)


@pytest.fixture
def booted_as_a(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    monkeypatch.delenv("V2_PRIMARY_ACADEMY_ID", raising=False)
    monkeypatch.delenv("PRIMARY_ACADEMY_ID", raising=False)
    monkeypatch.setenv("V2_DEFAULT_ACADEMY_ID", BOOT)
    monkeypatch.setenv("DEFAULT_ACADEMY_ID", BOOT)
    get_settings.cache_clear()
    yield BOOT
    get_settings.cache_clear()


def _compose(db: Any) -> Any:
    return compose_admin(
        db,
        outbox=MongoOutbox(db),
        idempotency_store=MongoIdempotencyStore(db),
        stripe=FakeStripeGateway(),
    )


async def _seed_class(db: Any, academy_id: str, *, enrollment_id: str) -> None:
    await db["sessions"].insert_one(
        {
            "session_id": SESSION,
            "academy_id": academy_id,
            "coach_id": "coach-1",
            "title": "Juniors",
            "location": "Court 1",
            "start_at": FUTURE,
            "end_at": FUTURE + timedelta(hours=1),
            "capacity": 1,
            "reserved_seats": 1,
            "status": "scheduled",
        }
    )
    await db["enrollments"].insert_one(
        {
            "enrollment_id": enrollment_id,
            "academy_id": academy_id,
            "session_id": SESSION,
            "student_id": f"stu-enrolled-{academy_id}",
            "parent_id": f"par-enrolled-{academy_id}",
            "status": "active",
            "enrolled_at": FUTURE - timedelta(days=60),
            "created_at": FUTURE - timedelta(days=60),
        }
    )
    await db["waitlist"].insert_one(
        {
            "waitlist_id": f"wl-{academy_id}",
            "academy_id": academy_id,
            "session_id": SESSION,
            "student_id": f"stu-waiting-{academy_id}",
            "parent_id": f"par-waiting-{academy_id}",
            "joined_at": FUTURE - timedelta(days=10),
            "status": "waiting",
        }
    )


def _install_handlers(db: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    promote = PromoteFromWaitlist(
        waitlist=MongoWaitlistRepository(db),
        sessions=MongoSessionWriter(db),
        enrollments=MongoEnrollmentWriter(db),
        outbox=MongoOutbox(db),
        academy_id=current_academy_id,
    )
    monkeypatch.setattr(
        event_handlers,
        "_deps",
        HandlerDeps(
            confirm_enrollment=None,  # type: ignore[arg-type]
            promote_from_waitlist=promote,
            issue_refund=None,  # type: ignore[arg-type]
            transition_application=None,  # type: ignore[arg-type]
            expire_level_up_recommendations=compose_expire_level_up_recommendations(db),
        ),
    )


async def _dispatch_cancellations(db: Any) -> None:
    dispatcher = EventDispatcher(db)
    async for doc in db["outbox_events"].find({"name": "Enrollment.EnrollmentCancelled"}):
        await dispatcher._process_event(doc)


async def _waitlist_status(db: Any, academy_id: str) -> str:
    doc = await db["waitlist"].find_one({"academy_id": academy_id, "session_id": SESSION})
    assert doc is not None
    return str(doc["status"])


async def _cancellation_events(db: Any) -> list[dict[str, Any]]:
    return await db["outbox_events"].find({"name": "Enrollment.EnrollmentCancelled"}).to_list(10)


@pytest.mark.asyncio
async def test_cancel_session_in_b_stamps_every_cancellation_event_with_b(
    real_db: Any, booted_as_a: str
) -> None:
    await _seed_class(real_db, BOOT, enrollment_id="enr-shared-1")
    await _seed_class(real_db, OTHER, enrollment_id="enr-shared-1")
    admin = _compose(real_db)

    with tenant_scope(OTHER):
        await admin.cancel_session.execute(CancelSessionCommand(session_id=SESSION))

    events = await _cancellation_events(real_db)
    assert events, "cancelling a class with an active enrollment emits EnrollmentCancelled"
    assert {e["academy_id"] for e in events} == {OTHER}

    # Academy A's class and enrollment were never touched.
    a_session = await real_db["sessions"].find_one({"academy_id": BOOT, "session_id": SESSION})
    assert a_session["status"] == "scheduled"
    a_enr = await real_db["enrollments"].find_one({"academy_id": BOOT})
    assert a_enr["status"] == "active"


@pytest.mark.asyncio
async def test_cancel_enrollment_in_b_promotes_b_waitlist_and_never_touches_a(
    real_db: Any, booted_as_a: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _seed_class(real_db, BOOT, enrollment_id="enr-shared-1")
    await _seed_class(real_db, OTHER, enrollment_id="enr-shared-1")
    admin = _compose(real_db)
    _install_handlers(real_db, monkeypatch)

    with tenant_scope(OTHER):
        await admin.cancel_enrollment.execute(
            CancelEnrollmentCommand(enrollment_id="enr-shared-1", actor_id="admin-b")
        )

    assert [e["academy_id"] for e in await _cancellation_events(real_db)] == [OTHER]

    # The dispatcher runs the handler inside tenant_scope(event.academy_id):
    # with the right stamp, B's freed seat goes to B's waiting family.
    await _dispatch_cancellations(real_db)

    assert await _waitlist_status(real_db, OTHER) != "waiting"
    assert await _waitlist_status(real_db, BOOT) == "waiting"
    a_enr = await real_db["enrollments"].find_one({"academy_id": BOOT})
    assert a_enr["status"] == "active"
    a_session = await real_db["sessions"].find_one({"academy_id": BOOT, "session_id": SESSION})
    assert a_session["reserved_seats"] == 1


@pytest.mark.asyncio
async def test_approve_fixed_pause_in_b_schedules_the_resume_in_b(
    real_db: Any, booted_as_a: str
) -> None:
    await _seed_class(real_db, OTHER, enrollment_id="enr-pause-b")
    now = datetime.now(UTC)
    with tenant_scope(OTHER):
        await MongoPauseRequestRepository(real_db).add(
            PauseRequest(
                pause_request_id="pause-b-1",
                enrollment_id="enr-pause-b",
                parent_id=f"par-enrolled-{OTHER}",
                pause_kind="fixed",
                resume_on=(now + timedelta(days=45)).date(),
                reason="travel",
                status="pending",
                created_at=now,
            )
        )
    admin = _compose(real_db)

    with tenant_scope(OTHER):
        await admin.approve_pause_request.execute(
            DecidePauseRequestCommand(pause_request_id="pause-b-1", admin_id="admin-b")
        )

    rows = await real_db["scheduled_enrollment_actions"].find({}).to_list(10)
    assert [(r["academy_id"], r["action_type"]) for r in rows] == [(OTHER, "resume_from_pause")]


@pytest.mark.asyncio
async def test_scoped_update_cannot_write_a_foreign_academy_id(real_db: Any) -> None:
    """Repository hardening: a ``$setOnInsert``/``$set`` body that carries an
    academy_id (a domain object dumped whole) is re-stamped with the tenant in
    scope, the same way ``_insert_one`` already re-stamps inserts."""
    repo = MongoScheduledEnrollmentActionRepository(real_db)
    now = datetime.now(UTC)

    def _row(action_id: str) -> dict[str, Any]:
        return {
            "action_id": action_id,
            "academy_id": BOOT,
            "action_type": "resume_from_pause",
            "enrollment_id": f"enr-{action_id}",
            "run_at": now,
            "status": "pending",
            "created_at": now,
            "updated_at": now,
        }

    with tenant_scope(OTHER):
        await repo._update_one({"action_id": "act-1"}, {"$setOnInsert": _row("act-1")}, upsert=True)
        await repo._update_one({"action_id": "act-1"}, {"$set": {"academy_id": BOOT}})
        await repo._find_one_and_update(
            {"action_id": "act-2"}, {"$setOnInsert": _row("act-2")}, upsert=True
        )

    rows = await real_db["scheduled_enrollment_actions"].find({}).to_list(10)
    assert sorted((r["action_id"], r["academy_id"]) for r in rows) == [
        ("act-1", OTHER),
        ("act-2", OTHER),
    ]


@pytest.fixture
def blno_single_academy(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Production's shape: single_academy mode pinned to PRIMARY_ACADEMY_ID."""
    monkeypatch.setenv("V2_TENANCY_MODE", "single_academy")
    monkeypatch.setenv("V2_PRIMARY_ACADEMY_ID", BOOT)
    get_settings.cache_clear()
    yield BOOT
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_blno_regression_single_academy_cancellation_is_unchanged(
    real_db: Any, blno_single_academy: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """BLNO today: the request tenant IS the boot academy, so the stamp, the
    waitlist promotion and the scheduled resume all land in BLNO as before."""
    await _seed_class(real_db, BOOT, enrollment_id="enr-blno-1")
    admin = _compose(real_db)
    _install_handlers(real_db, monkeypatch)

    with tenant_scope(BOOT):
        await admin.cancel_enrollment.execute(
            CancelEnrollmentCommand(enrollment_id="enr-blno-1", actor_id="admin-blno")
        )
    assert [e["academy_id"] for e in await _cancellation_events(real_db)] == [BOOT]
    await _dispatch_cancellations(real_db)
    assert await _waitlist_status(real_db, BOOT) != "waiting"
