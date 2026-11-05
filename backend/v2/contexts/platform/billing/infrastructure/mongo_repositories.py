"""Mongo repositories for SaaS platform billing.

These collections are platform-owned and intentionally separate from parent
tuition billing collections such as `subscriptions` and `payments`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pymongo.errors import DuplicateKeyError

from backend.v2.contexts.platform.billing.domain.models import (
    PlatformPlan,
    TenantSubscription,
)


class MongoPlatformPlanRepository:
    def __init__(self, db: Any) -> None:
        self._collection = db["platform_plans"]

    async def get(self, plan_id: str) -> PlatformPlan | None:
        doc = await self._collection.find_one({"plan_id": plan_id})
        return _plan_from_doc(doc) if doc else None

    async def list(self) -> list[PlatformPlan]:
        cursor = self._collection.find({}, sort=[("code", 1), ("plan_id", 1)])
        return [_plan_from_doc(doc) async for doc in cursor]

    async def save(self, plan: PlatformPlan) -> None:
        doc = plan.model_dump(mode="python")
        doc["features"] = sorted(plan.features)  # BSON has no set
        await self._collection.update_one(
            {"plan_id": plan.plan_id},
            {"$set": doc},
            upsert=True,
        )


class MongoTenantSubscriptionRepository:
    def __init__(self, db: Any) -> None:
        self._collection = db["platform_tenant_subscriptions"]

    async def get_for_academy(self, academy_id: str) -> TenantSubscription | None:
        doc = await self._collection.find_one({"academy_id": academy_id})
        return _subscription_from_doc(doc) if doc else None

    async def save(self, subscription: TenantSubscription) -> None:
        doc = subscription.model_dump(mode="python")
        await self._collection.update_one(
            {"academy_id": subscription.academy_id},
            {"$set": doc},
            upsert=True,
        )

    async def claim_pending_checkout(
        self, subscription: TenantSubscription, *, expected_token: str | None, now: datetime
    ) -> bool:
        doc = subscription.model_dump(mode="python")
        pending = {k: v for k, v in doc.items() if k.startswith("pending_checkout_")}
        rest = {k: v for k, v in doc.items() if k not in pending and k != "updated_at"}
        try:
            result = await self._collection.update_one(
                {"academy_id": subscription.academy_id, "pending_checkout_token": expected_token},
                {"$set": {**pending, "updated_at": now}, "$setOnInsert": rest},
                upsert=True,
            )
        except DuplicateKeyError:
            # The row exists with another token (platform_tenant_subscriptions
            # _academy_unique): a concurrent request claimed it first.
            return False
        return result.matched_count == 1 or result.upserted_id is not None


def _plan_from_doc(doc: dict[str, Any]) -> PlatformPlan:
    return PlatformPlan(
        **{
            **doc,
            "created_at": _as_utc(doc["created_at"]),
            "updated_at": _as_utc(doc["updated_at"]),
        }
    )


def _subscription_from_doc(doc: dict[str, Any]) -> TenantSubscription:
    values = dict(doc)
    for field in (
        "current_period_start",
        "current_period_end",
        "trial_started_at",
        "trial_ends_at",
        "cancelled_at",
        "stripe_subscription_created_at",
        "pending_checkout_created_at",
        "created_at",
        "updated_at",
    ):
        values[field] = _as_utc(values.get(field))
    return TenantSubscription(**values)


def _as_utc(value: Any) -> Any:
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value
