from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal

import pytest
from pydantic import BaseModel

from backend.v2.scripts.replay_event import _replay_dead_letter
from backend.v2.shared.events import MongoOutbox, handler
from backend.v2.shared.events.base import DomainEvent
from backend.v2.shared.events.dispatcher import MAX_ATTEMPTS, EventDispatcher


class RetryPayload(BaseModel):
    payment_id: str


class RetryEvent(DomainEvent):
    name: Literal["Test.RetryEvent"] = "Test.RetryEvent"  # type: ignore[assignment]
    schema_version: Literal[1] = 1  # type: ignore[assignment]
    payload: RetryPayload  # type: ignore[assignment]


class ReplayObservedPayload(BaseModel):
    payment_id: str


class ReplayObservedEvent(DomainEvent):
    name: Literal["Test.ReplayObserved"] = "Test.ReplayObserved"  # type: ignore[assignment]
    schema_version: Literal[1] = 1  # type: ignore[assignment]
    payload: ReplayObservedPayload  # type: ignore[assignment]


_observed_replay_event_ids: list[str] = []


@handler(event=RetryEvent, schema_version=1)
async def _always_fails(_event: RetryEvent) -> None:
    raise RuntimeError("retry me")


@handler(event=ReplayObservedEvent, schema_version=1)
async def _observe_replayed_event(event: ReplayObservedEvent) -> None:
    _observed_replay_event_ids.append(event.event_id)


@pytest.mark.asyncio
async def test_outbox_append_and_claim_sets_retry_lock_metadata(db) -> None:
    outbox = MongoOutbox(db)
    event = RetryEvent(
        aggregate_id="pay-1",
        academy_id="acad",
        payload=RetryPayload(payment_id="pay-1"),
    )

    await outbox.append(event)
    stored = await db["outbox_events"].find_one({"event_id": event.event_id})
    assert stored["processed"] is False
    assert stored["status"] == "pending"
    assert stored["attempt_count"] == 0
    assert stored["next_retry_at"] is not None

    dispatcher = EventDispatcher(db, worker_id="worker-a", lock_seconds=60)
    claimed = await dispatcher._claim_next_event()
    assert claimed["event_id"] == event.event_id
    assert claimed["status"] == "processing"
    assert claimed["lock_owner"] == "worker-a"
    assert claimed["locked_until"] is not None


@pytest.mark.asyncio
async def test_dispatcher_schedules_retry_without_blocking_sleep(db) -> None:
    outbox = MongoOutbox(db)
    event = RetryEvent(
        aggregate_id="pay-2",
        academy_id="acad",
        payload=RetryPayload(payment_id="pay-2"),
    )
    await outbox.append(event)
    dispatcher = EventDispatcher(db, worker_id="worker-b", lock_seconds=60)

    claimed = await dispatcher._claim_next_event()
    await dispatcher._process_event(claimed)

    stored = await db["outbox_events"].find_one({"event_id": event.event_id})
    assert stored["processed"] is False
    assert stored["status"] == "retry"
    assert stored["attempt_count"] == 1
    assert stored["next_retry_at"] is not None
    assert stored["locked_until"] is None
    assert await db["dead_letter_events"].count_documents({"event_id": event.event_id}) == 0


@pytest.mark.asyncio
async def test_dispatcher_reclaims_stale_processing_lock_but_skips_fresh_lock(db) -> None:
    now = datetime.now(UTC)
    await db["outbox_events"].insert_many(
        [
            _event_doc(
                "fresh-lock",
                status="processing",
                locked_until=now + timedelta(minutes=5),
                created_at=now - timedelta(minutes=2),
            ),
            _event_doc(
                "stale-lock",
                status="processing",
                locked_until=now - timedelta(minutes=5),
                created_at=now - timedelta(minutes=1),
            ),
        ]
    )

    claimed = await EventDispatcher(db, worker_id="worker-c")._claim_next_event()

    assert claimed["event_id"] == "stale-lock"
    assert claimed["lock_owner"] == "worker-c"


@pytest.mark.asyncio
async def test_dispatcher_dead_letters_after_attempts_exhausted(db) -> None:
    now = datetime.now(UTC)
    await db["outbox_events"].insert_one(
        _event_doc(
            "terminal",
            status="pending",
            attempt_count=MAX_ATTEMPTS - 1,
            next_retry_at=now,
            created_at=now,
        )
    )
    dispatcher = EventDispatcher(db, worker_id="worker-d")

    claimed = await dispatcher._claim_next_event()
    await dispatcher._process_event(claimed)

    stored = await db["outbox_events"].find_one({"event_id": "terminal"})
    assert stored["processed"] is True
    assert stored["status"] == "dead_lettered"
    assert stored["attempt_count"] == MAX_ATTEMPTS
    assert await db["dead_letter_events"].count_documents({"event_id": "terminal"}) == 1


@pytest.mark.asyncio
async def test_replay_dead_letter_rewrites_nested_event_id_and_resolves_original(db) -> None:
    _observed_replay_event_ids.clear()
    outbox = MongoOutbox(db)
    original = ReplayObservedEvent(
        aggregate_id="pay-replay",
        academy_id="acad",
        payload=ReplayObservedPayload(payment_id="pay-replay"),
    )
    await outbox.append(original)
    original_doc = await db["outbox_events"].find_one({"event_id": original.event_id})
    await db["dead_letter_events"].insert_one(
        {
            "event_id": original.event_id,
            "event": original_doc,
            "reason": "handler_failed",
            "created_at": datetime.now(UTC),
        }
    )

    replayed_id = await _replay_dead_letter(db, original.event_id, new_event_id="evt-replayed")
    replayed_doc = await db["outbox_events"].find_one({"event_id": replayed_id})
    dead = await db["dead_letter_events"].find_one({"event_id": original.event_id})
    await EventDispatcher(db, worker_id="worker-replay")._process_event(replayed_doc)

    assert replayed_id == "evt-replayed"
    assert replayed_doc["payload"]["event_id"] == "evt-replayed"
    assert dead["resolved"] is True
    assert dead["replayed"] is True
    assert dead["replayed_as"] == "evt-replayed"
    assert _observed_replay_event_ids == ["evt-replayed"]


def _event_doc(
    event_id: str,
    *,
    status: str,
    attempt_count: int = 0,
    next_retry_at: datetime | None = None,
    locked_until: datetime | None = None,
    created_at: datetime,
) -> dict[str, object]:
    return {
        "event_id": event_id,
        "name": "Test.RetryEvent",
        "schema_version": 1,
        "aggregate_id": event_id,
        "academy_id": "acad",
        "occurred_at": created_at,
        "payload": {
            "event_id": event_id,
            "name": "Test.RetryEvent",
            "schema_version": 1,
            "aggregate_id": event_id,
            "academy_id": "acad",
            "occurred_at": created_at,
            "payload": {"payment_id": event_id},
        },
        "processed": False,
        "status": status,
        "attempt_count": attempt_count,
        "next_retry_at": next_retry_at,
        "locked_until": locked_until,
        "lock_owner": None,
        "created_at": created_at,
        "updated_at": created_at,
    }


@pytest.mark.asyncio
async def test_is_running_tracks_the_poll_loop_lifecycle(db) -> None:
    """/healthz reads this to catch a dispatcher whose task died while the
    process kept serving traffic (issue #429)."""
    dispatcher = EventDispatcher(db, worker_id="worker-health")

    assert dispatcher.is_running() is False  # never started

    await dispatcher.start()
    assert dispatcher.is_running() is True

    await dispatcher.stop()
    assert dispatcher.is_running() is False


class UnhandledPayload(BaseModel):
    ref: str


class AuditOnlyStandIn(DomainEvent):
    # Reuses a real audit-only name so the dispatcher's allowlist applies.
    name: Literal["Coaching.AttendanceMarked"] = "Coaching.AttendanceMarked"  # type: ignore[assignment]
    schema_version: Literal[1] = 1  # type: ignore[assignment]
    payload: UnhandledPayload  # type: ignore[assignment]


class UnknownEvent(DomainEvent):
    name: Literal["Test.NobodyListens"] = "Test.NobodyListens"  # type: ignore[assignment]
    schema_version: Literal[1] = 1  # type: ignore[assignment]
    payload: UnhandledPayload  # type: ignore[assignment]


async def _dispatch_once(db, event: DomainEvent) -> dict:
    await MongoOutbox(db).append(event)
    dispatcher = EventDispatcher(db, worker_id="worker-audit", lock_seconds=60)
    await dispatcher._process_event(await dispatcher._claim_next_event())
    return await db["outbox_events"].find_one({"event_id": event.event_id})


@pytest.mark.asyncio
async def test_audit_only_event_without_handler_is_processed_not_dead_lettered(db) -> None:
    event = AuditOnlyStandIn(
        aggregate_id="a-1", academy_id="acad", payload=UnhandledPayload(ref="a-1")
    )
    stored = await _dispatch_once(db, event)

    assert stored["status"] == "processed"
    assert await db["dead_letter_events"].count_documents({"event_id": event.event_id}) == 0


@pytest.mark.asyncio
async def test_unknown_event_without_handler_still_dead_letters(db) -> None:
    event = UnknownEvent(aggregate_id="u-1", academy_id="acad", payload=UnhandledPayload(ref="u-1"))
    stored = await _dispatch_once(db, event)

    assert stored["status"] == "dead_lettered"
    dead = await db["dead_letter_events"].find_one({"event_id": event.event_id})
    assert dead["reason"] == "unregistered_schema_version"


def test_audit_only_events_name_real_event_classes() -> None:
    """A typo in AUDIT_ONLY_EVENTS would silently keep dead-lettering."""
    from backend.v2.contexts.billing.domain import events as billing
    from backend.v2.contexts.coaching.domain import events as coaching
    from backend.v2.contexts.enrollment.domain import events as enrollment
    from backend.v2.contexts.student_progress.domain import events as progress
    from backend.v2.shared.events.dispatcher import AUDIT_ONLY_EVENTS

    real = {
        (cls.model_fields["name"].default, cls.model_fields["schema_version"].default)
        for module in (billing, coaching, enrollment, progress)
        for cls in vars(module).values()
        if isinstance(cls, type) and issubclass(cls, DomainEvent) and cls is not DomainEvent
    }
    assert AUDIT_ONLY_EVENTS <= real, AUDIT_ONLY_EVENTS - real
