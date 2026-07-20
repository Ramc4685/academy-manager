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
            enrollment_id=doc.get("enrollment_id"),
            session_id=doc.get("session_id"),
            stripe_subscription_id=str(doc.get("stripe_subscription_id") or ""),
            stripe_checkout_session_id=doc.get("stripe_checkout_session_id"),
            status=doc.get("status", "incomplete"),
            payment_mode=doc.get("payment_mode", "monthly"),
            created_at=doc["created_at"],
            updated_at=doc["updated_at"],
        )

    async def save(self, subscription: Subscription) -> None:
        doc = subscription.model_dump(mode="python")
        fields = {k: v for k, v in doc.items() if k != "academy_id"}
        update: dict[str, object] = {"$set": fields}
        # Stripe assigns the subscription id only after Checkout completes;
        # until then the domain model carries "". The stripe_sub_unique
        # partial index covers every string value including "", so a second
        # pending row would raise DuplicateKeyError — keep the field unset
        # instead so pending rows never enter the unique index.
        if not fields.get("stripe_subscription_id"):
            fields.pop("stripe_subscription_id", None)
            update["$unset"] = {"stripe_subscription_id": ""}
        await self._update_one(
            {"subscription_id": subscription.subscription_id},
            update,
            upsert=True,
        )

    async def get(self, subscription_id: str) -> Subscription | None:
        doc = await self._find_one({"subscription_id": subscription_id})
        return self._to_domain(doc) if doc else None

    async def get_by_stripe_sub(self, stripe_sub: str) -> Subscription | None:
        doc = await self._find_one({"stripe_subscription_id": stripe_sub})
        return self._to_domain(doc) if doc else None

    async def get_by_checkout_session(self, checkout_session_id: str) -> Subscription | None:
        doc = await self._find_one({"stripe_checkout_session_id": checkout_session_id})
        return self._to_domain(doc) if doc else None

    async def latest_for_enrollment(self, enrollment_id: str) -> Subscription | None:
        cursor = self._find_many(
            {"enrollment_id": enrollment_id},
            sort=[("created_at", -1), ("subscription_id", -1)],
            limit=1,
        )
        docs = [doc async for doc in cursor]
        return self._to_domain(docs[0]) if docs else None
