"""Contract tests — migration 0137 autopay_status split backfill."""

from __future__ import annotations

import importlib
from datetime import UTC, datetime

import pytest

migration_0137 = importlib.import_module("backend.v2.migrations.0137_autopay_status_split")


@pytest.mark.asyncio
async def test_backfills_legacy_active_into_split_enrollment_status(db) -> None:
    await db["parent_billing_customers"].insert_one(
        {
            "academy_id": "acad-1",
            "parent_id": "parent-1",
            "autopay_status": "active",
            "created_at": datetime(2026, 1, 1, tzinfo=UTC),
        }
    )

    await migration_0137.up(db)

    doc = await db["parent_billing_customers"].find_one(
        {"academy_id": "acad-1", "parent_id": "parent-1"}
    )
    assert doc["autopay_enrollment_status"] == "active"
    assert "autopay_status" not in doc


@pytest.mark.asyncio
async def test_backfills_last_attempt_outcome_from_latest_payment_attempt(db) -> None:
    await db["parent_billing_customers"].insert_one(
        {
            "academy_id": "acad-1",
            "parent_id": "parent-1",
            "autopay_status": "active",
            "created_at": datetime(2026, 1, 1, tzinfo=UTC),
        }
    )
    await db["payment_attempts"].insert_many(
        [
            {
                "academy_id": "acad-1",
                "parent_id": "parent-1",
                "status": "failed",
                "failure_code": "card_declined",
                "created_at": datetime(2026, 6, 1, tzinfo=UTC),
            },
            {
                "academy_id": "acad-1",
                "parent_id": "parent-1",
                "status": "succeeded",
                "failure_code": None,
                "created_at": datetime(2026, 6, 15, tzinfo=UTC),
            },
        ]
    )

    await migration_0137.up(db)

    doc = await db["parent_billing_customers"].find_one(
        {"academy_id": "acad-1", "parent_id": "parent-1"}
    )
    # Latest attempt (2026-06-15, succeeded) wins over the earlier decline.
    assert doc["last_attempt_outcome"] == "succeeded"
    assert doc["last_failure_code"] is None
    assert doc["autopay_enrollment_status"] == "active"


@pytest.mark.asyncio
async def test_customer_without_payment_attempts_gets_no_outcome_projection(db) -> None:
    await db["parent_billing_customers"].insert_one(
        {
            "academy_id": "acad-1",
            "parent_id": "parent-no-attempts",
            "autopay_status": "active",
            "created_at": datetime(2026, 1, 1, tzinfo=UTC),
        }
    )

    await migration_0137.up(db)

    doc = await db["parent_billing_customers"].find_one(
        {"academy_id": "acad-1", "parent_id": "parent-no-attempts"}
    )
    assert doc["autopay_enrollment_status"] == "active"
    assert "last_attempt_outcome" not in doc


@pytest.mark.asyncio
async def test_migration_is_idempotent(db) -> None:
    await db["parent_billing_customers"].insert_one(
        {
            "academy_id": "acad-1",
            "parent_id": "parent-1",
            "autopay_status": "active",
            "created_at": datetime(2026, 1, 1, tzinfo=UTC),
        }
    )
    await db["payment_attempts"].insert_one(
        {
            "academy_id": "acad-1",
            "parent_id": "parent-1",
            "status": "succeeded",
            "failure_code": None,
            "created_at": datetime(2026, 6, 1, tzinfo=UTC),
        }
    )

    await migration_0137.up(db)
    await migration_0137.up(db)  # re-run must be a no-op, not an error

    doc = await db["parent_billing_customers"].find_one(
        {"academy_id": "acad-1", "parent_id": "parent-1"}
    )
    assert doc["autopay_enrollment_status"] == "active"
    assert doc["last_attempt_outcome"] == "succeeded"
    assert await db["parent_billing_customers"].count_documents({}) == 1


@pytest.mark.asyncio
async def test_doc_without_legacy_field_is_left_untouched(db) -> None:
    await db["parent_billing_customers"].insert_one(
        {
            "academy_id": "acad-1",
            "parent_id": "parent-already-split",
            "autopay_enrollment_status": "paused",
            "created_at": datetime(2026, 1, 1, tzinfo=UTC),
        }
    )

    await migration_0137.up(db)

    doc = await db["parent_billing_customers"].find_one(
        {"academy_id": "acad-1", "parent_id": "parent-already-split"}
    )
    assert doc["autopay_enrollment_status"] == "paused"
