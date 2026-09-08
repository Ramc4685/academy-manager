"""Tenant-scoped Mongo store for the billing audit trail.

Append-only: entries are never updated or deleted. One document per billing money-movement
mutation (collection ``billing_audit_log``). Mirrors MongoPayoutAuditLogRepository.
"""

from __future__ import annotations

from typing import Any

from pymongo.errors import DuplicateKeyError

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
            parent_id=_opt_str(doc.get("parent_id")),
            reason=doc.get("reason"),
            before=doc.get("before"),
            after=doc.get("after"),
        )

    async def append(self, entry: BillingAuditEntry) -> None:
        doc = {k: v for k, v in entry.model_dump(mode="python").items() if k != "academy_id"}
        try:
            await self._insert_one(doc)
        except DuplicateKeyError:
            # ``(academy_id, audit_id)`` is unique. Deterministic audit ids let
            # an idempotent request safely repair a prior post-mutation audit
            # failure without creating duplicate trail entries.
            return

    async def list_for_invoice(self, invoice_id: str) -> list[BillingAuditEntry]:
        cursor = self._find_many(
            {"invoice_id": invoice_id},
            sort=[("at", -1)],
            limit=500,
        )
        return [self._to_domain(doc) async for doc in cursor]

    async def list_for_family(
        self,
        *,
        parent_id: str,
        invoice_ids: list[str],
        payment_ids: list[str],
        enrollment_ids: list[str],
    ) -> list[BillingAuditEntry]:
        """Every entry that touches one family: by invoice, by payment, by parent
        (family-level actions), or by the enrollment named in ``before``
        (``autopay_resumed`` rows written by the Billing Setup enable path carry
        no parent_id)."""
        clauses: list[dict[str, Any]] = [{"parent_id": parent_id}]
        if invoice_ids:
            clauses.append({"invoice_id": {"$in": invoice_ids}})
        if payment_ids:
            clauses.append({"payment_id": {"$in": payment_ids}})
        if enrollment_ids:
            clauses.append({"before.enrollment_id": {"$in": enrollment_ids}})
        cursor = self._find_many({"$or": clauses}, sort=[("at", -1)], limit=500)
        return [self._to_domain(doc) async for doc in cursor]
