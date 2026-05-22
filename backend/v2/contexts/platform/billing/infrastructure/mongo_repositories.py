"""Mongo repositories for SaaS platform billing.

These collections are platform-owned and intentionally separate from parent
tuition billing collections such as `subscriptions` and `payments`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

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
        "created_at",
        "updated_at",
    ):
        values[field] = _as_utc(values.get(field))
    return TenantSubscription(**values)


def _as_utc(value: Any) -> Any:
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value
