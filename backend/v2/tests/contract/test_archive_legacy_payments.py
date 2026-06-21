from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.scripts.archive_legacy_payments import archive_legacy_payments


@pytest.mark.asyncio
async def test_archive_legacy_payments_blocks_until_ledger_invoice_exists(db) -> None:
    now = datetime(2026, 6, 18, 12, 0, tzinfo=UTC)
    await db["payments"].insert_one(
        {
            "academy_id": "acad-1",
            "payment_id": "legacy-pay-1",
            "parent_id": "parent-1",
            "amount_cents": 5_000,
            "status": "succeeded",
            "created_at": now,
            "updated_at": now,
        }
    )

    result = await archive_legacy_payments(db, academy_id="acad-1", apply=True)

    assert result["status"] == "blocked"
    assert result["deleted_from_payments"] == 0
    assert result["blockers"] == [
        {
            "payment_id": "legacy-pay-1",
            "reason": "legacy payment has no backfilled ledger invoice",
        }
    ]
    assert await db["payments"].count_documents({"academy_id": "acad-1"}) == 1


@pytest.mark.asyncio
async def test_archive_legacy_payments_archives_backfilled_rows_before_delete(db) -> None:
    now = datetime(2026, 6, 18, 12, 0, tzinfo=UTC)
    await db["payments"].insert_one(
        {
            "academy_id": "acad-1",
            "payment_id": "legacy-pay-1",
            "parent_id": "parent-1",
            "amount_cents": 5_000,
            "status": "succeeded",
            "created_at": now,
            "updated_at": now,
        }
    )
    await db["invoices"].insert_one(
        {
            "academy_id": "acad-1",
            "invoice_id": "inv-from-legacy-pay-1",
            "backfill_payment_id": "legacy-pay-1",
        }
    )

    dry_run = await archive_legacy_payments(db, academy_id="acad-1", apply=False)
    applied = await archive_legacy_payments(db, academy_id="acad-1", apply=True)

    assert dry_run["status"] == "ready"
    assert dry_run["archiveable"] == 1
    assert dry_run["deleted_from_payments"] == 0
    assert applied["status"] == "ready"
    assert applied["archived"] == 1
    assert applied["deleted_from_payments"] == 1
    assert await db["payments"].count_documents({"academy_id": "acad-1"}) == 0
    archive = await db["legacy_payments_archive"].find_one(
        {"academy_id": "acad-1", "payment_id": "legacy-pay-1"}
    )
    assert archive is not None
    assert archive["archive_reason"] == "legacy_payment_collection_retired"


@pytest.mark.asyncio
async def test_archive_allows_invoice_number_preserving_backfill(db) -> None:
    now = datetime(2026, 6, 18, 12, 0, tzinfo=UTC)
    await db["payments"].insert_one(
        {
            "academy_id": "acad-1",
            "payment_id": "pay_28505f6db2b4a5b11917",
            "invoice_number": "BLNO-202605-b11917",
            "parent_id": "parent-1",
            "amount_cents": 6000,
            "status": "pending",
            "created_at": now,
            "updated_at": now,
        }
    )
    await db["invoices"].insert_one(
        {
            "academy_id": "acad-1",
            "invoice_id": "inv-from-pay_28505f6db2b4a5b11917",
            "invoice_number": "BLNO-202605-b11917",
            "backfill_payment_id": "pay_28505f6db2b4a5b11917",
        }
    )

    result = await archive_legacy_payments(db, academy_id="acad-1", apply=False)

    assert result["status"] == "ready"
    assert result["archiveable"] == 1
    assert result["blockers"] == []
