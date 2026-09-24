"""The #931 allocation audit script finds what it claims to, and writes nothing.

Runs on mongomock so the duplicate-key group (impossible on a real mongod with
the 0091 unique index) can be seeded.
"""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "payment_allocation_claim_audit.py"
NOW = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)
WRITE_METHODS = {
    "insert_one",
    "insert_many",
    "update_one",
    "update_many",
    "replace_one",
    "delete_one",
    "delete_many",
    "find_one_and_update",
    "find_one_and_replace",
    "find_one_and_delete",
    "bulk_write",
    "create_index",
    "create_indexes",
    "drop",
    "drop_index",
}


def _load_audit() -> Any:
    spec = importlib.util.spec_from_file_location("payment_allocation_claim_audit", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.audit


class _ReadOnlyCollection:
    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def __getattr__(self, name: str) -> Any:
        if name in WRITE_METHODS:
            raise AssertionError(f"audit attempted a write: {name}")
        return getattr(self._inner, name)


class _ReadOnlyDb:
    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def __getitem__(self, name: str) -> _ReadOnlyCollection:
        return _ReadOnlyCollection(self._inner[name])


def _allocation(allocation_id: str, invoice_id: str, key: str, **extra: Any) -> dict[str, Any]:
    return {
        "allocation_id": allocation_id,
        "academy_id": "acad-audit-931",
        "payment_id": "pay-audit-1",
        "invoice_id": invoice_id,
        "amount_cents": 5_000,
        "idempotency_key": key,
        "created_at": NOW,
        **extra,
    }


def _invoice(invoice_id: str, status: str) -> dict[str, Any]:
    return {
        "invoice_id": invoice_id,
        "academy_id": "acad-audit-931",
        "parent_id": "parent-audit-1",
        "period": "2026-09",
        "status": status,
        "total_cents": 5_000,
        "balance_due_cents": 0 if status == "paid" else 5_000,
        "updated_at": NOW,
    }


async def test_audit_reports_each_931_state_and_writes_nothing(db) -> None:
    await db["payment_allocations"].insert_many(
        [
            _allocation("alloc-dup-a", "inv-funded", "alloc:dup"),
            _allocation("alloc-dup-b", "inv-funded", "alloc:dup"),
            _allocation(
                "alloc-stale",
                "inv-stale",
                "alloc:stale",
                allocation_state="pending",
                claimed_at=NOW - timedelta(minutes=5),
            ),
            _allocation(
                "alloc-live",
                "inv-live",
                "alloc:live",
                allocation_state="pending",
                claimed_at=NOW - timedelta(seconds=5),
            ),
            _allocation("alloc-done", "inv-done", "alloc:done", allocation_state="committed"),
        ]
    )
    await db["invoices"].insert_many(
        [
            _invoice("inv-funded", "paid"),
            _invoice("inv-orphan", "paid"),
            _invoice("inv-open", "open"),
        ]
    )
    before = {
        name: [doc async for doc in db[name].find({}, {"_id": 0})]
        for name in ("payment_allocations", "invoices")
    }

    report = await _load_audit()(_ReadOnlyDb(db), now=NOW)

    assert report["duplicate_key_group_count"] == 1
    group = report["duplicate_key_groups"][0]
    assert group["idempotency_key"] == "alloc:dup" and group["row_count"] == 2
    assert group["surplus_allocated_cents"] == 5_000
    assert [row["invoice_id"] for row in report["posted_invoices_without_allocations"]] == [
        "inv-orphan"
    ]
    assert [row["allocation_id"] for row in report["stale_pending_claims"]] == ["alloc-stale"]
    after = {
        name: [doc async for doc in db[name].find({}, {"_id": 0})]
        for name in ("payment_allocations", "invoices")
    }
    assert after == before


async def test_audit_can_be_limited_to_one_academy(db) -> None:
    await db["invoices"].insert_many(
        [_invoice("inv-a", "paid"), {**_invoice("inv-b", "paid"), "academy_id": "acad-other"}]
    )
    report = await _load_audit()(_ReadOnlyDb(db), academy_id="acad-other", now=NOW)
    assert [row["invoice_id"] for row in report["posted_invoices_without_allocations"]] == ["inv-b"]
