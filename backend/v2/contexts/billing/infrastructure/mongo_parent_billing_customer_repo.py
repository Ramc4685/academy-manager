"""Tenant-scoped parent Stripe customer storage."""

from __future__ import annotations

from datetime import UTC, datetime

from backend.v2.shared.tenancy import TenantScopedRepository


class MongoParentBillingCustomerRepository(TenantScopedRepository):
    collection_name = "parent_billing_customers"

    async def get_stripe_customer_id(self, *, parent_id: str) -> str | None:
        doc = await self._find_one({"parent_id": parent_id})
        if not doc:
            return None
        customer_id = doc.get("stripe_customer_id")
        return str(customer_id) if customer_id else None

    async def set_stripe_customer_id(self, *, parent_id: str, stripe_customer_id: str) -> None:
        now = datetime.now(UTC)
        await self._update_one(
            {"parent_id": parent_id},
            {
                "$set": {
                    "parent_id": parent_id,
                    "stripe_customer_id": stripe_customer_id,
                    "updated_at": now,
                },
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )
