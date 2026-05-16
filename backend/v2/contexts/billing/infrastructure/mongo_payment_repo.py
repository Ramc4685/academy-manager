"""Mongo PaymentRepository."""

from __future__ import annotations

from backend.v2.contexts.billing.domain.models import Payment
from backend.v2.shared.tenancy import TenantScopedRepository


class MongoPaymentRepository(TenantScopedRepository):
    collection_name = "payments"

    @staticmethod
    def _to_domain(doc: dict[str, object]) -> Payment:
        return Payment(
            payment_id=str(doc["payment_id"]),
            academy_id=str(doc["academy_id"]),
            parent_id=str(doc["parent_id"]),
            session_id=doc.get("session_id"),  # type: ignore[arg-type]
            subscription_id=doc.get("subscription_id"),  # type: ignore[arg-type]
            stripe_payment_intent_id=doc.get("stripe_payment_intent_id"),  # type: ignore[arg-type]
            stripe_checkout_session_id=doc.get("stripe_checkout_session_id"),  # type: ignore[arg-type]
            amount_cents=int(doc["amount_cents"]),  # type: ignore[arg-type]
            currency=str(doc.get("currency", "usd")),
            status=doc.get("status", "pending"),  # type: ignore[arg-type]
            refunded_cents=int(doc.get("refunded_cents", 0)),  # type: ignore[arg-type]
            created_at=doc["created_at"],  # type: ignore[arg-type]
            updated_at=doc["updated_at"],  # type: ignore[arg-type]
        )

    async def save(self, payment: Payment) -> None:
        doc = payment.model_dump(mode="python")
        await self._update_one(
            {"payment_id": payment.payment_id},
            {"$set": {k: v for k, v in doc.items() if k != "academy_id"}},
            upsert=True,
        )

    async def get(self, payment_id: str) -> Payment | None:
        doc = await self._find_one({"payment_id": payment_id})
        return self._to_domain(doc) if doc else None

    async def get_by_stripe_pi(self, stripe_pi: str) -> Payment | None:
        doc = await self._find_one({"stripe_payment_intent_id": stripe_pi})
        return self._to_domain(doc) if doc else None

    async def get_by_checkout_session(self, checkout_session_id: str) -> Payment | None:
        doc = await self._find_one({"stripe_checkout_session_id": checkout_session_id})
        return self._to_domain(doc) if doc else None

    async def list_for_parent(self, parent_id: str) -> list[Payment]:
        cursor = self._find_many(
            {"parent_id": parent_id},
            sort=[("created_at", -1)],
        )
        return [self._to_domain(doc) async for doc in cursor]
