"""``scripts/find_deduped_refunds.py`` on synthetic data (#930).

The data reproduces what the pre-#930 key scheme left behind when academy B
refunded the same payment id, amount and reason as academy A: B's invoice
claimed a refund and wrote a ``refund_issued`` audit row, but the inner
``IssueRefund`` replayed A's cached Stripe refund. The audit must flag it, and
it must never write: every collection it touches is wrapped so that only
``find``/``find_one`` exist.
"""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "find_deduped_refunds.py"
ACAD = "acad-audit-a"
OTHER = "acad-audit-b"
NOW = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)


def _load_script() -> Any:
    spec = importlib.util.spec_from_file_location("find_deduped_refunds", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _ReadOnlyCollection:
    def __init__(self, collection: Any, log: list[str]) -> None:
        self._collection = collection
        self._log = log

    def find(self, *args: Any, **kwargs: Any) -> Any:
        self._log.append(f"find {self._collection.name}")
        return self._collection.find(*args, **kwargs)

    async def find_one(self, *args: Any, **kwargs: Any) -> Any:
        self._log.append(f"find_one {self._collection.name}")
        return await self._collection.find_one(*args, **kwargs)


class _ReadOnlyDb:
    def __init__(self, db: Any) -> None:
        self._db = db
        self.log: list[str] = []

    def __getitem__(self, name: str) -> _ReadOnlyCollection:
        return _ReadOnlyCollection(self._db[name], self.log)


def _payment(academy_id: str, refunded: int) -> dict[str, Any]:
    return {
        "payment_id": "pay-shared-1",
        "academy_id": academy_id,
        "parent_id": "parent-test-1",
        "session_id": "sess-test-1",
        "stripe_payment_intent_id": f"pi_{academy_id}",
        "amount_cents": 10_000,
        "currency": "usd",
        "status": "partially_refunded" if refunded else "succeeded",
        "refunded_cents": refunded,
        "created_at": NOW,
        "updated_at": NOW,
    }


def _invoice_cache(academy_id: str, refund_id: str) -> dict[str, Any]:
    return {
        "key": f"invoice_refund:{academy_id}:inv-1:3000:class cancelled",
        "value": {
            "payload": {
                "payment_id": "pay-shared-1",
                "stripe_refund_id": refund_id,
                "refunded_cents": 3_000,
                "total_refunded_cents": 3_000,
                "invoice_id": "inv-1",
            }
        },
        "created_at": NOW,
    }


def _audit_row(academy_id: str) -> dict[str, Any]:
    return {
        "audit_id": f"baud-{academy_id}",
        "academy_id": academy_id,
        "action": "refund_issued",
        "actor_id": "owner-test-1",
        "at": NOW,
        "invoice_id": "inv-1",
        "payment_id": "pay-shared-1",
        "reason": "class cancelled",
        "before": {"refunded_cents": 0},
        "after": {"refunded_cents": 3_000},
    }


async def _seed_pre_930_cross_academy_replay(db: Any) -> None:
    await db["payments"].insert_many([_payment(ACAD, 3_000), _payment(OTHER, 0)])
    await db["billing_audit_log"].insert_many([_audit_row(ACAD), _audit_row(OTHER)])
    await db["idempotency_keys"].insert_many(
        [
            # A's inner IssueRefund entry, shape-keyed with no academy.
            {
                "key": "refund:pay-shared-1:3000:class cancelled",
                "value": {
                    "value": {
                        "_type": "pydantic",
                        "data": {
                            "payment_id": "pay-shared-1",
                            "stripe_refund_id": "re_synthetic_a",
                            "refunded_cents": 3_000,
                            "total_refunded_cents": 3_000,
                        },
                    },
                    "stored_at": NOW.isoformat(),
                },
                "created_at": NOW,
            },
            _invoice_cache(ACAD, "re_synthetic_a"),
            # B got A's refund back.
            _invoice_cache(OTHER, "re_synthetic_a"),
        ]
    )


async def test_flags_a_refund_replayed_across_academies_without_writing(real_db) -> None:
    await _seed_pre_930_cross_academy_replay(real_db)
    before = {
        name: [d async for d in real_db[name].find({}, {"_id": 0})]
        for name in ("payments", "billing_audit_log", "idempotency_keys")
    }
    readonly = _ReadOnlyDb(real_db)

    report = await _load_script().audit(readonly)

    assert report["unbacked_invoice_refund_count"] == 1
    finding = report["unbacked_invoice_refunds"][0]
    assert finding["academy_id"] == OTHER
    assert finding["unbacked_cents"] == 3_000
    assert report["shared_stripe_refund_id_count"] == 1
    assert report["shared_stripe_refund_ids"][0]["stripe_refund_id"] == "re_synthetic_a"
    assert report["legacy_key_count"] == 3
    assert all(entry.split()[0] in {"find", "find_one"} for entry in readonly.log)
    after = {
        name: [d async for d in real_db[name].find({}, {"_id": 0})]
        for name in ("payments", "billing_audit_log", "idempotency_keys")
    }
    assert after == before


async def test_a_clean_post_930_history_reports_nothing(real_db) -> None:
    """Two keyed refunds of the same shape, each with its own Stripe refund."""
    await real_db["payments"].insert_one(_payment(ACAD, 6_000))
    await real_db["billing_audit_log"].insert_many(
        [
            {**_audit_row(ACAD), "audit_id": "baud-1"},
            {
                **_audit_row(ACAD),
                "audit_id": "baud-2",
                "before": {"refunded_cents": 3_000},
                "after": {"refunded_cents": 6_000},
            },
        ]
    )
    for n, refund_id in ((1, "re_synthetic_1"), (2, "re_synthetic_2")):
        entry = _invoice_cache(ACAD, refund_id)
        entry["key"] = f"invoice_refund:{ACAD}:inv-1:key:k-{n}"
        entry["value"]["fingerprint"] = "f" * 64
        await real_db["idempotency_keys"].insert_one(entry)

    report = await _load_script().audit(_ReadOnlyDb(real_db))

    assert report["unbacked_invoice_refund_count"] == 0
    assert report["shared_stripe_refund_id_count"] == 0
    assert report["legacy_key_count"] == 0


@pytest.mark.parametrize(
    ("key", "legacy"),
    [
        ("refund:pay-1:3000:admin_initiated", True),
        ("invoice_refund:acad:inv-1:3000:class cancelled", True),
        ("invoice_refund:acad:inv-1:key:k-1", False),
        ("payment_refund:acad:pay-1:None:admin_initiated", False),
    ],
)
def test_legacy_key_shapes(key: str, legacy: bool) -> None:
    assert (_load_script()._parse_legacy_key(key) is not None) is legacy
