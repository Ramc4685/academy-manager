"""Mongo store for Stripe disputes (``payment_disputes``, migration 0205).

One row per ``(academy_id, dispute_id)``. ``stamp_payment`` mirrors the
dispute onto the disputed payment row in ``ledger_payments`` (every payment
since the Phase 5 freeze) and ``payments`` (historical rows), matched by the
PaymentIntent inside the request academy. Only ``dispute_*`` fields are
written: amounts, refunds, status and allocations are never touched, because
a dispute is the academy's to resolve and the ledger records no adjustment.
"""

from __future__ import annotations

from typing import Any

from backend.v2.contexts.billing.domain.payment_dispute import PaymentDispute
from backend.v2.shared.tenancy import TenantScopedRepository, current_academy_id


class MongoPaymentDisputeRepository(TenantScopedRepository):
    collection_name = "payment_disputes"

    async def get(self, dispute_id: str) -> PaymentDispute | None:
        doc = await self._find_one({"dispute_id": dispute_id})
        return _from_doc(doc) if doc else None

    async def save(self, dispute: PaymentDispute) -> None:
        doc = dispute.model_dump(mode="python")
        doc.pop("academy_id", None)
        doc["is_open"] = dispute.is_open
        await self._update_one(
            {"dispute_id": dispute.dispute_id},
            {"$set": doc},
            upsert=True,
        )

    async def stamp_payment(self, dispute: PaymentDispute) -> None:
        if not dispute.stripe_payment_intent_id:
            return
        academy_id = current_academy_id()
        fields: dict[str, Any] = {
            "dispute_id": dispute.dispute_id,
            "dispute_status": dispute.status,
            "dispute_reason": dispute.reason,
            "dispute_amount_cents": dispute.amount_cents,
            "dispute_outcome": dispute.outcome,
            "disputed_at": dispute.opened_at,
        }
        pi = dispute.stripe_payment_intent_id
        await self._db["ledger_payments"].update_many(
            {"academy_id": academy_id, "stripe_payment_intent_id": pi},
            {"$set": fields},
        )
        for pi_field in ("stripe_payment_intent_id", "stripe_payment_intent"):
            await self._db["payments"].update_many(
                {"academy_id": academy_id, pi_field: pi},
                {"$set": fields},
            )

    async def list_open(self, *, limit: int = 20) -> list[PaymentDispute]:
        cursor = self._find_many(
            {"is_open": True},
            sort=[("opened_at", -1), ("dispute_id", 1)],
            limit=max(1, min(int(limit), 100)),
        )
        return [_from_doc(doc) async for doc in cursor]

    async def count_open(self) -> int:
        return int(await self.collection.count_documents(self._scoped({"is_open": True})))


def _from_doc(doc: dict[str, Any]) -> PaymentDispute:
    return PaymentDispute.model_validate(
        {k: v for k, v in doc.items() if k not in ("_id", "is_open")}
    )
