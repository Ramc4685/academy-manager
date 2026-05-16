"""Mongo SubscriptionRepository."""

from __future__ import annotations

from backend.v2.contexts.billing.domain.models import Subscription
from backend.v2.shared.tenancy import TenantScopedRepository


class MongoSubscriptionRepository(TenantScopedRepository):
    collection_name = "subscriptions"

    @staticmethod
    def _to_domain(doc: dict[str, object]) -> Subscription:
        return Subscription(
            subscription_id=str(doc["subscription_id"]),
            academy_id=str(doc["academy_id"]),
            parent_id=str(doc["parent_id"]),
            session_id=doc.get("session_id"),  # type: ignore[arg-type]
            stripe_subscription_id=str(doc["stripe_subscription_id"]),
            status=doc.get("status", "incomplete"),  # type: ignore[arg-type]
            payment_mode=doc.get("payment_mode", "monthly"),  # type: ignore[arg-type]
            created_at=doc["created_at"],  # type: ignore[arg-type]
            updated_at=doc["updated_at"],  # type: ignore[arg-type]
        )

    async def save(self, subscription: Subscription) -> None:
        doc = subscription.model_dump(mode="python")
        await self._update_one(
            {"subscription_id": subscription.subscription_id},
            {"$set": {k: v for k, v in doc.items() if k != "academy_id"}},
            upsert=True,
        )

    async def get_by_stripe_sub(self, stripe_sub: str) -> Subscription | None:
        doc = await self._find_one({"stripe_subscription_id": stripe_sub})
        return self._to_domain(doc) if doc else None
