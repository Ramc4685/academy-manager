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
from backend.v2.contexts.billing.infrastructure.mongo_stripe_invoice_processing_repo import (
    MongoStripeInvoiceProcessingRepository,
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


@pytest.mark.asyncio
async def test_store_received_short_circuits_existing_event_even_without_unique_index(db) -> None:
    dedup = MongoStripeEventDedup(db)
    event = {
        "id": "evt_replay_without_index",
        "type": "invoice.paid",
        "data": {"object": {"id": "in_replay_without_index"}},
    }

    assert await dedup.store_received(event, raw_payload=b"{}", academy_id="acad") is True
    assert await dedup.store_received(event, raw_payload=b"{}", academy_id="acad") is False
    assert (
        await db["stripe_webhook_events"].count_documents({"event_id": "evt_replay_without_index"})
        == 1
    )


@pytest.mark.asyncio
async def test_terminal_status_updates_repair_duplicate_legacy_event_rows(db) -> None:
    dedup = MongoStripeEventDedup(db)
    await db["stripe_webhook_events"].insert_many(
        [
            {
                "event_id": "evt_duplicate_legacy_rows",
                "event_type": "checkout.session.completed",
                "status": "processing",
                "received_at": datetime.now(UTC),
            },
            {
                "event_id": "evt_duplicate_legacy_rows",
                "event_type": "checkout.session.completed",
                "status": "received",
                "received_at": datetime.now(UTC),
            },
        ]
    )

    await dedup.mark_processed("evt_duplicate_legacy_rows")

    docs = (
        await db["stripe_webhook_events"]
        .find({"event_id": "evt_duplicate_legacy_rows"})
        .to_list(length=None)
    )
    assert len(docs) == 2
    assert {doc["status"] for doc in docs} == {"processed"}


@pytest.mark.asyncio
async def test_stripe_invoice_processing_recovery_point_upserts_by_business_key(db) -> None:
    await db["stripe_invoice_processing"].create_index(
        [("academy_id", 1), ("business_key", 1)],
        unique=True,
    )
    repo = MongoStripeInvoiceProcessingRepository(db)
    now = datetime.now(UTC)

    await repo.record_recovery_point(
        academy_id="acad",
        stripe_invoice_id="in_1",
        stripe_subscription_id="sub_1",
        event_id="evt_1",
        recovery_point="ledger_payment_recorded",
        ledger_invoice_id="ledger-in_1",
        ledger_payment_id="ledger-pay-in_1",
        updated_at=now,
    )
    await repo.record_recovery_point(
        academy_id="acad",
        stripe_invoice_id="in_1",
        stripe_subscription_id="sub_1",
        event_id="evt_2",
        recovery_point="ledger_allocated",
        ledger_invoice_id="ledger-in_1",
        ledger_payment_id="ledger-pay-in_1",
        updated_at=now,
    )

    docs = await db["stripe_invoice_processing"].find({}).to_list(length=None)
    assert len(docs) == 1
    assert docs[0]["business_key"] == "stripe_invoice:in_1"
    assert docs[0]["recovery_point"] == "ledger_allocated"
    assert docs[0]["event_ids"] == ["evt_1", "evt_2"]
