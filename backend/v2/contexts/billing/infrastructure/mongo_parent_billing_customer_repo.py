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

    async def set_default_payment_method(
        self,
        *,
        parent_id: str,
        stripe_customer_id: str,
        stripe_payment_method_id: str,
        payment_method_type: str,
        stripe_mandate_id: str | None,
        setup_intent_id: str,
        checkout_session_id: str | None,
        completed_at: datetime,
    ) -> None:
        now = datetime.now(UTC)
        update: dict[str, object] = {
            "parent_id": parent_id,
            "stripe_customer_id": stripe_customer_id,
            "default_payment_method_id": stripe_payment_method_id,
            "payment_method_type": payment_method_type,
            "autopay_status": "active",
            "autopay_setup_intent_id": setup_intent_id,
            "autopay_setup_completed_at": completed_at,
            "updated_at": now,
        }
        if stripe_mandate_id:
            update["stripe_mandate_id"] = stripe_mandate_id
        if checkout_session_id:
            update["autopay_setup_checkout_session_id"] = checkout_session_id
        await self._update_one(
            {"parent_id": parent_id},
            {
                "$set": update,
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )
