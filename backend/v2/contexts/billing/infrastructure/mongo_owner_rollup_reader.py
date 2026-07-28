"""Per-academy financial snapshot reader backing the owner rollup (UIM11).

Every query filters on the `academy_id` it is handed, so a rollup over N
academies is N ordinary tenant-scoped reads rather than one cross-tenant
query. The caller (`GetOwnerFinancialRollup`) is responsible for only ever
handing over academies the user actually owns.
"""

from __future__ import annotations

from typing import Any

from backend.v2.contexts.billing.application.ports import AcademyFinancialSnapshot

_REVENUE_PAYMENT_STATUSES = ("succeeded", "partially_refunded", "refunded")
_OPEN_INVOICE_STATUSES = ("open", "partially_paid", "draft")
_SETTLED_INVOICE_STATUSES = frozenset({"paid", "void", "waived", "cancelled"})


class MongoAcademyFinancialSnapshotReader:
    def __init__(self, db: Any) -> None:
        self._db = db

    async def read(
        self, *, academy_id: str, months: tuple[str, ...] | None = None
    ) -> AcademyFinancialSnapshot:
        revenue_by_month = await self._revenue_by_month(academy_id, months)
        outstanding_cents, outstanding_count = await self._outstanding(academy_id)
        return AcademyFinancialSnapshot(
            revenue_by_month=revenue_by_month,
            collected_cents=sum(revenue_by_month.values()),
            outstanding_cents=outstanding_cents,
            outstanding_invoice_count=outstanding_count,
        )

    async def _revenue_by_month(
        self, academy_id: str, months: tuple[str, ...] | None
    ) -> dict[str, int]:
        cursor = self._db["payments"].find(
            {
                "academy_id": academy_id,
                "status": {"$in": list(_REVENUE_PAYMENT_STATUSES)},
                "is_deleted": {"$ne": True},
            },
            {"amount_cents": 1, "refunded_cents": 1, "created_at": 1},
        )
        buckets: dict[str, int] = {}
        async for doc in cursor:
            created_at = doc.get("created_at")
            if created_at is None:
                continue
            key = created_at.strftime("%Y-%m")
            if months is not None and key not in months:
                continue
            net = int(doc.get("amount_cents") or 0) - int(doc.get("refunded_cents") or 0)
            buckets[key] = buckets.get(key, 0) + net
        return dict(sorted(buckets.items()))

    async def _outstanding(self, academy_id: str) -> tuple[int, int]:
        cursor = self._db["invoices"].find(
            {
                "academy_id": academy_id,
                "status": {"$in": list(_OPEN_INVOICE_STATUSES)},
                "balance_due_cents": {"$gt": 0},
                "is_deleted": {"$ne": True},
            },
            {"status": 1, "balance_due_cents": 1},
        )
        total = 0
        count = 0
        async for doc in cursor:
            if str(doc.get("status") or "") in _SETTLED_INVOICE_STATUSES:
                continue
            due = max(int(doc.get("balance_due_cents") or 0), 0)
            if due <= 0:
                continue
            total += due
            count += 1
        return total, count
