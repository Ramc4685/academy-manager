"""Find refund requests that were deduped onto an earlier refund (#930).

Read-only: every call below is a ``find``. Nothing is written, updated or
deleted.

Before #930 both admin refund paths deduped on the refund's SHAPE instead of
the request, and ``IssueRefund``'s key carried no academy:

* ``IssueRefund`` cached under ``refund:{payment_id}:{amount}:{reason}``;
* the invoice refund cached under
  ``invoice_refund:{academy}:{invoice}:{amount}:{reason}``.

A second, legitimate refund with the same shape inside the 7-day TTL got the
first result back: no Stripe refund, a 200 to the owner. A swallowed request
leaves no row of its own, so this audit reports the three traces it CAN leave:

1. ``unbacked_invoice_refunds`` — the invoice route claims the invoice
   projection and writes a ``refund_issued`` audit row even when the inner
   ``IssueRefund`` replayed a cached result. Per payment, the invoice refunds
   the audit trail attributes to it exceed what the payment says was refunded:
   the difference is refund the family was told about but never received.
2. ``shared_stripe_refund_ids`` — one Stripe refund id answering more than one
   cached request (a different invoice, or another academy's same payment id).
   Each extra request is a refund that was replayed, not issued.
3. ``legacy_keys`` — pre-#930 shape-keyed cache entries still inside their TTL,
   with the window during which an identical refund request would have been
   swallowed. Compare each window against the Stripe dashboard / request logs;
   a same-shape refund attempt inside it that has no Stripe refund was dropped.

Exit status 1 when (1) or (2) finds anything.

Usage (point it at a copy or a read-only user; never run it casually against
production)::

    MONGO_URL=... DB_NAME=... python backend/scripts/find_deduped_refunds.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import defaultdict
from datetime import timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
sys.path.insert(0, str(REPO_ROOT))

#: ``idempotency_keys`` TTL (migration 0001).
IDEMPOTENCY_TTL = timedelta(days=7)

LEGACY_PAYMENT_PREFIX = "refund:"
INVOICE_PREFIX = "invoice_refund:"


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items() if key != "_id"}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _legacy_payment_result(doc: dict[str, Any]) -> dict[str, Any] | None:
    """The cached ``IssueRefundResult`` of a pre-#930 ``@idempotent`` entry."""
    value = doc.get("value") or {}
    inner = value.get("value") if isinstance(value, dict) else None
    if isinstance(inner, dict) and inner.get("_type") == "pydantic":
        data = inner.get("data")
        return data if isinstance(data, dict) else None
    return None


def _invoice_payload(doc: dict[str, Any]) -> dict[str, Any] | None:
    value = doc.get("value") or {}
    payload = value.get("payload") if isinstance(value, dict) else None
    return payload if isinstance(payload, dict) else None


def _parse_legacy_key(key: str) -> dict[str, Any] | None:
    """Split a shape key; None when it is not the pre-#930 shape.

    ``refund:{payment}:{amount}:{reason}`` (3 fields after the prefix) and
    ``invoice_refund:{academy}:{invoice}:{amount}:{reason}`` (4 fields). Keyed
    entries (``...:key:{client key}``) and ``:claim`` markers are not legacy.
    """
    if key.startswith(INVOICE_PREFIX):
        parts = key[len(INVOICE_PREFIX) :].split(":", 3)
        if len(parts) != 4 or parts[2] == "key":
            return None
        academy_id, invoice_id, amount, reason = parts
        return {
            "path": "invoice_refund",
            "academy_id": academy_id,
            "invoice_id": invoice_id,
            "amount": amount,
            "reason": reason,
        }
    if key.startswith(LEGACY_PAYMENT_PREFIX):
        parts = key[len(LEGACY_PAYMENT_PREFIX) :].split(":", 2)
        if len(parts) != 3:
            return None
        payment_id, amount, reason = parts
        return {
            "path": "payment_refund",
            "academy_id": None,  # the pre-#930 key carried none
            "payment_id": payment_id,
            "amount": amount,
            "reason": reason,
        }
    return None


def _target(key: str) -> tuple[str, str | None, str]:
    """(path, academy, payment-or-invoice id) a cache key refunds."""
    kind, _, rest = key.partition(":")
    parts = rest.split(":")
    if kind == "refund":  # pre-#930 IssueRefund key: no academy
        return kind, None, parts[0]
    return kind, parts[0], parts[1] if len(parts) > 1 else ""


async def _unbacked_invoice_refunds(db: Any) -> list[dict[str, Any]]:
    claimed: dict[tuple[str, str], dict[str, Any]] = {}
    async for entry in db["billing_audit_log"].find({"action": "refund_issued"}):
        academy_id = str(entry.get("academy_id") or "")
        payment_id = str(entry.get("payment_id") or "")
        if not academy_id or not payment_id:
            continue
        before = int((entry.get("before") or {}).get("refunded_cents") or 0)
        after = int((entry.get("after") or {}).get("refunded_cents") or 0)
        row = claimed.setdefault(
            (academy_id, payment_id), {"claimed_cents": 0, "audit_ids": [], "invoice_ids": set()}
        )
        row["claimed_cents"] += max(after - before, 0)
        row["audit_ids"].append(entry.get("audit_id"))
        row["invoice_ids"].add(entry.get("invoice_id"))

    findings: list[dict[str, Any]] = []
    for (academy_id, payment_id), row in sorted(claimed.items()):
        payment = await db["payments"].find_one(
            {"academy_id": academy_id, "payment_id": payment_id},
            {"_id": 0, "refunded_cents": 1, "amount_cents": 1},
        )
        refunded = int((payment or {}).get("refunded_cents") or 0)
        if row["claimed_cents"] <= refunded:
            continue
        findings.append(
            {
                "academy_id": academy_id,
                "payment_id": payment_id,
                "payment_found": payment is not None,
                "invoice_ids": sorted(str(i) for i in row["invoice_ids"] if i),
                "claimed_by_invoice_refunds_cents": row["claimed_cents"],
                "payment_refunded_cents": refunded,
                "unbacked_cents": row["claimed_cents"] - refunded,
                "audit_ids": row["audit_ids"],
            }
        )
    return findings


async def audit(db: Any) -> dict[str, Any]:
    by_refund_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    legacy: list[dict[str, Any]] = []
    scanned = 0
    cursor = db["idempotency_keys"].find(
        {"key": {"$regex": "^(refund|invoice_refund|payment_refund):"}}
    )
    async for doc in cursor:
        scanned += 1
        key = str(doc.get("key") or "")
        if key.endswith(":claim"):
            continue
        result = (
            _legacy_payment_result(doc)
            if key.startswith(LEGACY_PAYMENT_PREFIX)
            else _invoice_payload(doc)
            if key.startswith(INVOICE_PREFIX)
            else ((doc.get("value") or {}).get("payload") or None)
        )
        created_at = doc.get("created_at")
        refund_id = str((result or {}).get("stripe_refund_id") or "")
        if refund_id:
            by_refund_id[refund_id].append(
                {
                    "key": key,
                    "created_at": _jsonable(created_at),
                    "payment_id": (result or {}).get("payment_id"),
                    "invoice_id": (result or {}).get("invoice_id"),
                }
            )
        shape = _parse_legacy_key(key)
        # A fingerprint marks a post-#930 entry; only pre-#930 ones replayed.
        if shape is not None and "fingerprint" not in (doc.get("value") or {}):
            legacy.append(
                {
                    **shape,
                    "key": key,
                    "stripe_refund_id": refund_id or None,
                    "swallow_window_start": _jsonable(created_at),
                    "swallow_window_end": _jsonable(
                        created_at + IDEMPOTENCY_TTL if hasattr(created_at, "isoformat") else None
                    ),
                }
            )

    shared: list[dict[str, Any]] = []
    for refund_id, requests in sorted(by_refund_id.items()):
        # One request can leave several entries with its refund id: the invoice
        # key, the inner payment key, and a keyed request's advisory shape key.
        # Those share a target; a refund id answering two TARGETS was replayed.
        targets = {_target(r["key"]) for r in requests}
        invoice_targets = {t for t in targets if t[0] == "invoice_refund"}
        payment_targets = {t for t in targets if t[0] != "invoice_refund"}
        if len(invoice_targets) > 1 or len(payment_targets) > 1:
            shared.append(
                {
                    "stripe_refund_id": refund_id,
                    "request_count": len(requests),
                    "requests": requests,
                }
            )

    unbacked = await _unbacked_invoice_refunds(db)
    return {
        "scanned_refund_idempotency_keys": scanned,
        "unbacked_invoice_refund_count": len(unbacked),
        "unbacked_cents": sum(f["unbacked_cents"] for f in unbacked),
        "unbacked_invoice_refunds": unbacked,
        "shared_stripe_refund_id_count": len(shared),
        "shared_stripe_refund_ids": shared,
        "legacy_key_count": len(legacy),
        "legacy_keys": sorted(legacy, key=lambda row: str(row["swallow_window_start"])),
    }


async def main() -> int:
    from motor.motor_asyncio import AsyncIOMotorClient

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mongo-url", default=os.environ.get("MONGO_URL") or os.environ.get("V2_MONGO_URL")
    )
    parser.add_argument(
        "--db-name", default=os.environ.get("DB_NAME") or os.environ.get("V2_MONGO_DB")
    )
    args = parser.parse_args()
    if not args.mongo_url or not args.db_name:
        parser.error("--mongo-url/--db-name or MONGO_URL/DB_NAME is required")

    client: Any = AsyncIOMotorClient(args.mongo_url)
    try:
        report = await audit(client[args.db_name])
        print(json.dumps({"db_name": args.db_name, **report}, indent=2, sort_keys=True))
    finally:
        client.close()
    return (
        1
        if report["unbacked_invoice_refund_count"] or report["shared_stripe_refund_id_count"]
        else 0
    )


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
