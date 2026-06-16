"""Wave 2 dedup behavior tests.

Closes the PR review finding that failed Stripe events were being
permanently de-duped instead of retried.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.v2.contexts.billing.infrastructure.mongo_stripe_dedup import (
    STALE_PROCESSING_AFTER,
    MongoStripeEventDedup,
)


@pytest.mark.asyncio
async def test_first_claim_returns_true(db) -> None:
    # Ensure the unique index exists per migration 0030.
    await db["stripe_webhook_events"].create_index("event_id", unique=True)
    dedup = MongoStripeEventDedup(db)
    assert await dedup.claim("evt_1", "checkout.session.completed") is True


@pytest.mark.asyncio
async def test_concurrent_processing_claim_returns_false(db) -> None:
    await db["stripe_webhook_events"].create_index("event_id", unique=True)
    dedup = MongoStripeEventDedup(db)
    assert await dedup.claim("evt_2", "checkout.session.completed") is True
    # Same event arrives again while still "processing".
    assert await dedup.claim("evt_2", "checkout.session.completed") is False


@pytest.mark.asyncio
async def test_processed_event_short_circuits(db) -> None:
    await db["stripe_webhook_events"].create_index("event_id", unique=True)
    dedup = MongoStripeEventDedup(db)
    await dedup.claim("evt_3", "checkout.session.completed")
    await dedup.mark_processed("evt_3")
    # Stripe retries a successful event — short-circuit.
    assert await dedup.claim("evt_3", "checkout.session.completed") is False


@pytest.mark.asyncio
async def test_failed_event_is_reclaimable(db) -> None:
    """The bug surfaced by review: previously, a failed event stayed
    failed forever because the dedup row was already inserted."""
    await db["stripe_webhook_events"].create_index("event_id", unique=True)
    dedup = MongoStripeEventDedup(db)
    await dedup.claim("evt_4", "checkout.session.completed")
    await dedup.mark_failed("evt_4", "transient db error")
    # Stripe retries; we MUST reclaim so the handler runs again.
    assert await dedup.claim("evt_4", "checkout.session.completed") is True
    doc = await db["stripe_webhook_events"].find_one({"event_id": "evt_4"})
    assert doc["status"] == "processing"
    assert "error" not in doc


@pytest.mark.asyncio
async def test_stale_processing_row_is_reclaimable(db) -> None:
    await db["stripe_webhook_events"].create_index("event_id", unique=True)
    dedup = MongoStripeEventDedup(db)
    # Write a stale processing row by hand (simulating a crashed previous
    # attempt that never reached mark_processed/mark_failed).
    stale_received = datetime.now(UTC) - STALE_PROCESSING_AFTER - timedelta(seconds=1)
    await db["stripe_webhook_events"].insert_one(
        {
            "event_id": "evt_5",
            "event_type": "checkout.session.completed",
            "status": "processing",
            "received_at": stale_received,
        }
    )
    # Retry should reclaim.
    assert await dedup.claim("evt_5", "checkout.session.completed") is True


@pytest.mark.asyncio
async def test_store_received_uses_receiving_academy_not_metadata_queue(db) -> None:
    await db["stripe_webhook_events"].create_index("event_id", unique=True)
    dedup = MongoStripeEventDedup(db)

    await dedup.store_received(
        {
            "id": "evt_wrong_metadata_queue",
            "type": "payment_intent.succeeded",
            "data": {
                "object": {
                    "id": "pi_wrong_metadata_queue",
                    "metadata": {"academy_id": "other-academy"},
                }
            },
        },
        raw_payload=b"{}",
        academy_id="acad",
    )

    doc = await db["stripe_webhook_events"].find_one({"event_id": "evt_wrong_metadata_queue"})
    assert doc["academy_id"] == "acad"
