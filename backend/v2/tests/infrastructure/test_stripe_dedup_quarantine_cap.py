"""Webhook retries are bounded (issue #437), against the real Mongo repo.

`test_webhook_handler.py` drives the cap through a fake dedup; this exercises
`MongoStripeEventDedup` itself on mongomock, because the behaviour under test is
the repository's own read-then-write of `retry_count`.

Before this, a permanently failing event retried 1m/5m/15m/hourly *forever*: no
cap, no dead-letter, and no admin surface beyond a log counter. Worse, it kept
being claimed, so it consumed one of the 25 attempts every drain tick and pushed
real payment events behind it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from backend.v2.contexts.billing.infrastructure.mongo_stripe_dedup import (
    MAX_WEBHOOK_ATTEMPTS,
    QUARANTINE_REJECTED,
    QUARANTINE_RETRY_LIMIT,
    MongoStripeEventDedup,
)
from mongomock_motor import AsyncMongoMockClient

ACADEMY_ID = "acad-1"
EVENT_ID = "evt_test_1"


def _db() -> Any:
    return AsyncMongoMockClient()["dedup_cap_test"]


async def _store(dedup: MongoStripeEventDedup) -> None:
    await dedup.store_received(
        {"id": EVENT_ID, "type": "checkout.session.completed", "livemode": False},
        raw_payload=b"{}",
        academy_id=ACADEMY_ID,
    )


async def _doc(db: Any) -> dict[str, Any]:
    doc = await db["stripe_webhook_events"].find_one({"event_id": EVENT_ID})
    assert doc is not None
    return doc


async def _drain_to_quarantine(db: Any, dedup: MongoStripeEventDedup) -> int:
    """Claim/fail until the event gives up. Returns the number of attempts.

    ``next_retry_at`` is backdated between attempts to stand in for the 1m/5m/
    15m/hourly backoff elapsing — the cap, not the schedule, is what is under
    test here, and without this the loop would only ever get one claim.
    """
    attempts = 0
    for _ in range(MAX_WEBHOOK_ATTEMPTS + 5):
        # Backdate first, so a caller that already recorded a failure (and is
        # therefore sitting on a future next_retry_at) still gets drained.
        await db["stripe_webhook_events"].update_one(
            {"event_id": EVENT_ID, "status": {"$ne": "quarantined"}},
            {"$set": {"next_retry_at": datetime.now(UTC) - timedelta(hours=2)}},
        )
        if await dedup.claim_next(academy_id=ACADEMY_ID, processor_id="w1") is None:
            break
        attempts += 1
        if await dedup.mark_failed(EVENT_ID, "still broken") == "quarantined":
            break
    return attempts


@pytest.mark.asyncio
async def test_failures_below_the_cap_stay_retryable() -> None:
    db = _db()
    dedup = MongoStripeEventDedup(db)
    await _store(dedup)

    claimed = await dedup.claim_next(academy_id=ACADEMY_ID, processor_id="w1")
    assert claimed is not None
    assert await dedup.mark_failed(EVENT_ID, "boom") == "failed"

    doc = await _doc(db)
    assert doc["status"] == "failed"
    # Still scheduled for another go — a transient error must not quarantine.
    assert doc["next_retry_at"] is not None


@pytest.mark.asyncio
async def test_the_cap_quarantines_and_the_drain_stops_claiming_it() -> None:
    db = _db()
    dedup = MongoStripeEventDedup(db)
    await _store(dedup)

    attempts = await _drain_to_quarantine(db, dedup)

    assert attempts == MAX_WEBHOOK_ATTEMPTS, "the event must get exactly its budget of attempts"

    doc = await _doc(db)
    assert doc["status"] == "quarantined"
    assert doc["quarantine_reason"] == QUARANTINE_RETRY_LIMIT
    assert doc["quarantined_at"] is not None
    # No next_retry_at, so nothing reschedules it...
    assert doc["next_retry_at"] is None
    # ...and the drain will not pick it up again, which is what frees the slot.
    assert await dedup.claim_next(academy_id=ACADEMY_ID, processor_id="w1") is None
    # The original failure is still readable by a human.
    assert "still broken" in doc["error_message"]


@pytest.mark.asyncio
async def test_a_guard_rejection_records_a_different_reason() -> None:
    """`quarantined` must not collapse two very different situations: "we tried
    24 times" and "a rule rejected this outright"."""
    db = _db()
    dedup = MongoStripeEventDedup(db)
    await _store(dedup)

    await dedup.mark_quarantined(EVENT_ID, "livemode mismatch")

    doc = await _doc(db)
    assert doc["status"] == "quarantined"
    assert doc["quarantine_reason"] == QUARANTINE_REJECTED


@pytest.mark.asyncio
async def test_replay_clears_the_quarantine_metadata() -> None:
    """An admin replay puts the event back in the drain; leaving the old reason
    behind would make the Billing Health card describe a running event as one
    that had given up."""
    db = _db()
    dedup = MongoStripeEventDedup(db)
    await _store(dedup)
    await _drain_to_quarantine(db, dedup)
    assert (await _doc(db))["status"] == "quarantined"

    assert await dedup.replay(EVENT_ID, academy_id=ACADEMY_ID) is True

    doc = await _doc(db)
    assert doc["status"] == "received"
    assert doc["retry_count"] == 0
    assert doc["quarantine_reason"] is None
    assert doc["quarantined_at"] is None
    # And it is claimable again, with a fresh budget.
    assert await dedup.claim_next(academy_id=ACADEMY_ID, processor_id="w1") is not None


@pytest.mark.asyncio
async def test_billing_health_counts_move_from_failed_to_quarantined() -> None:
    """PR #466's Billing Health card surfaces both counts. The cap is what makes
    them mean different things: `failed` is mid-retry, `quarantined` needs a
    human."""
    db = _db()
    dedup = MongoStripeEventDedup(db)
    await _store(dedup)

    await dedup.claim_next(academy_id=ACADEMY_ID, processor_id="w1")
    await dedup.mark_failed(EVENT_ID, "boom")
    assert await dedup.count_stuck_by_status(academy_id=ACADEMY_ID) == {
        "quarantined": 0,
        "failed": 1,
    }

    await _drain_to_quarantine(db, dedup)

    assert await dedup.count_stuck_by_status(academy_id=ACADEMY_ID) == {
        "quarantined": 1,
        "failed": 0,
    }
