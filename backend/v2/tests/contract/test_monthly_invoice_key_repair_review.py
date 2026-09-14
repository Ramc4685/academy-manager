"""Contract tests for the repair_failed monthly invoice key review script (#599).

The script is the operator's way out of a key that can never be repaired in
place: it shows what the key points at, and records a judgement the generator
honours. These tests pin both halves — the read-only report gathers the
invoice, its lines and the credit charged against the key's payment, and the
write touches nothing but ``billing_invoice_keys``.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.scripts.monthly_invoice_key_repair_review import audit, mark_reviewed

ACADEMY = "test-academy"
NOW = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)


async def _seed_repair_failed_key(db) -> None:
    await db["billing_invoice_keys"].insert_one(
        {
            "academy_id": ACADEMY,
            "invoice_key_id": "key-1",
            "payment_id": "pay-1",
            "enrollment_id": "enr-1",
            "period": "2026-07",
            "status": "repair_failed",
            "repair_error": "existing monthly tuition line does not match the expected gross charge",
            "created_at": datetime(2026, 7, 1, tzinfo=UTC),
            "updated_at": datetime(2026, 8, 31, tzinfo=UTC),
        }
    )
    await db["invoices"].insert_one(
        {
            "academy_id": ACADEMY,
            "invoice_id": "inv-monthly-enr-1-2026-07",
            "enrollment_id": "enr-1",
            "period": "2026-07",
            "status": "open",
            "subtotal_cents": 9_000,
            "total_cents": 9_000,
            "balance_due_cents": 0,
        }
    )
    await db["invoice_lines"].insert_one(
        {
            "academy_id": ACADEMY,
            "invoice_id": "inv-monthly-enr-1-2026-07",
            "line_id": "line-monthly-enr-1-2026-07",
            "line_type": "tuition",
            "amount_cents": 9_000,
        }
    )
    await db["payments"].insert_one(
        {"academy_id": ACADEMY, "payment_id": "pay-1", "amount_cents": 9_000, "status": "paid"}
    )
    await db["credit_applications"].insert_one(
        {"academy_id": ACADEMY, "invoice_id": "pay-1", "amount_cents": 1_000}
    )
    await db["account_credit_ledger"].insert_one(
        {"academy_id": ACADEMY, "invoice_id": "pay-1", "amount_cents": -1_000}
    )


@pytest.mark.asyncio
async def test_audit_reports_each_repair_failed_key_with_its_invoice(db) -> None:
    await _seed_repair_failed_key(db)
    await db["billing_invoice_keys"].insert_one(
        {
            "academy_id": ACADEMY,
            "invoice_key_id": "key-2",
            "payment_id": "pay-2",
            "enrollment_id": "enr-2",
            "period": "2026-07",
            "status": "complete",
        }
    )

    report = await audit(db)

    assert report["repair_failed_key_count"] == 1
    entry = report["repair_failed_keys"][0]
    assert entry["key"]["enrollment_id"] == "enr-1"
    assert entry["invoice_id"] == "inv-monthly-enr-1-2026-07"
    assert entry["invoice"]["subtotal_cents"] == 9_000
    assert [line["amount_cents"] for line in entry["invoice_lines"]] == [9_000]
    assert [payment["payment_id"] for payment in entry["payments"]] == ["pay-1"]
    assert [app["amount_cents"] for app in entry["credit_applications"]] == [1_000]
    assert [row["amount_cents"] for row in entry["account_credit_ledger"]] == [-1_000]
    assert "_id" not in entry["key"]


@pytest.mark.asyncio
async def test_audit_is_read_only(db) -> None:
    await _seed_repair_failed_key(db)

    await audit(db)

    key = await db["billing_invoice_keys"].find_one({"enrollment_id": "enr-1"})
    assert key is not None
    assert key["status"] == "repair_failed"


@pytest.mark.asyncio
async def test_mark_reviewed_records_the_reason_and_leaves_money_alone(db) -> None:
    await _seed_repair_failed_key(db)

    report = await mark_reviewed(
        db,
        enrollment_id="enr-1",
        period="2026-07",
        reason="pre-#494 shape; invoice and payments verified correct",
        reviewed_by="ops@example.com",
        academy_id=None,
        now=NOW,
    )

    assert report["marked"] is True
    assert report["academy_id"] == ACADEMY
    key = await db["billing_invoice_keys"].find_one({"enrollment_id": "enr-1"})
    assert key is not None
    assert key["status"] == "reviewed"
    assert key["reviewed"]["reason"] == "pre-#494 shape; invoice and payments verified correct"
    assert key["reviewed"]["reviewed_by"] == "ops@example.com"
    # Mongo (and mongomock) drop tzinfo on the way in; the stored instant is UTC.
    assert key["reviewed"]["reviewed_at"].replace(tzinfo=UTC) == NOW
    invoice = await db["invoices"].find_one({"invoice_id": "inv-monthly-enr-1-2026-07"})
    assert invoice is not None
    assert invoice["total_cents"] == 9_000
    assert invoice["balance_due_cents"] == 0


@pytest.mark.asyncio
async def test_mark_reviewed_refuses_a_key_that_is_not_repair_failed(db) -> None:
    await _seed_repair_failed_key(db)

    report = await mark_reviewed(
        db,
        enrollment_id="enr-missing",
        period="2026-07",
        reason="anything",
        reviewed_by="ops@example.com",
        academy_id=None,
        now=NOW,
    )

    assert report["marked"] is False
    assert "no repair_failed key" in report["error"]
