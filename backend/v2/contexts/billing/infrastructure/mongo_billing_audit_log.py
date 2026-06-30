"""Tenant-scoped Mongo store for the billing audit trail.

Append-only: entries are never updated or deleted. One document per billing money-movement
mutation (collection ``billing_audit_log``). Mirrors MongoPayoutAuditLogRepository.
"""

from __future__ import annotations

from typing import Any

from backend.v2.contexts.billing.domain.billing_audit import BillingAuditEntry
from backend.v2.shared.tenancy import TenantScopedRepository


def _opt_str(value: Any) -> str | None:
    return None if value is None else str(value)


class MongoBillingAuditLogRepository(TenantScopedRepository):
    collection_name = "billing_audit_log"

    @staticmethod
    def _to_domain(doc: dict[str, Any]) -> BillingAuditEntry:
        return BillingAuditEntry(
            audit_id=str(doc.get("audit_id") or doc.get("_id")),
            academy_id=str(doc["academy_id"]),
            action=doc["action"],
            actor_id=str(doc["actor_id"]),
            at=doc["at"],
            invoice_id=_opt_str(doc.get("invoice_id")),
            payment_id=_opt_str(doc.get("payment_id")),
            reason=doc.get("reason"),
            before=doc.get("before"),
            after=doc.get("after"),
        )

    async def append(self, entry: BillingAuditEntry) -> None:
        doc = {k: v for k, v in entry.model_dump(mode="python").items() if k != "academy_id"}
        await self._insert_one(doc)

    async def list_for_invoice(self, invoice_id: str) -> list[BillingAuditEntry]:
        cursor = self._find_many(
            {"invoice_id": invoice_id},
            sort=[("at", -1)],
            limit=500,
        )
        return [self._to_domain(doc) async for doc in cursor]
