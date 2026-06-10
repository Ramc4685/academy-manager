"""Tenant-scoped Mongo store for the payout audit trail.

Append-only: entries are never updated or deleted. One document per
mutation on a payout period (collection ``payout_audit_log``).
"""

from __future__ import annotations

from typing import Any

from backend.v2.contexts.finance.domain.payout_audit import PayoutAuditEntry
from backend.v2.shared.tenancy import TenantScopedRepository


class MongoPayoutAuditLogRepository(TenantScopedRepository):
    collection_name = "payout_audit_log"

    @staticmethod
    def _to_domain(doc: dict[str, Any]) -> PayoutAuditEntry:
        return PayoutAuditEntry(
            audit_id=str(doc.get("audit_id") or doc.get("_id")),
            academy_id=str(doc["academy_id"]),
            period_id=str(doc["period_id"]),
            occurrence_id=(None if doc.get("occurrence_id") is None else str(doc["occurrence_id"])),
            action=doc["action"],
            actor_id=str(doc["actor_id"]),
            at=doc["at"],
            reason=doc.get("reason"),
            before=doc.get("before"),
            after=doc.get("after"),
        )

    async def append(self, entry: PayoutAuditEntry) -> None:
        doc = {k: v for k, v in entry.model_dump(mode="python").items() if k != "academy_id"}
        await self._insert_one(doc)

    async def list_for_period(self, period_id: str) -> list[PayoutAuditEntry]:
        cursor = self._find_many(
            {"period_id": period_id},
            sort=[("at", -1)],
            limit=500,
        )
        return [self._to_domain(doc) async for doc in cursor]
