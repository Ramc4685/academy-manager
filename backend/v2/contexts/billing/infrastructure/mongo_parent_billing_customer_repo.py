"""Tenant-scoped parent Stripe customer storage.

Holds payment-method / Stripe-customer data only. Autopay enrollment status
is per-enrollment (see ``student_billing_enrollments`` and
``MongoStudentBillingEnrollmentRepository``), NOT per-parent: each child's
enrollment has its own autopay on/off/paused state, so pausing one child must
not affect siblings. Only the saved payment method / Stripe customer stays
per-parent here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

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
        current_consent_id: str | None = None,
        consent_text_version: str | None = None,
        ach_mandate_version: str | None = None,
        card_disclosure_version: str | None = None,
        setup_status: str = "active",
        payment_method_role: str = "primary",
        session: Any | None = None,
    ) -> None:
        now = datetime.now(UTC)
        role = payment_method_role if payment_method_role in {"primary", "fallback"} else "primary"
        method_projection: dict[str, object] = {
            "role": role,
            "stripe_payment_method_id": stripe_payment_method_id,
            "payment_method_type": payment_method_type,
            "setup_intent_id": setup_intent_id,
            "setup_status": setup_status,
            "updated_at": completed_at,
        }
        if stripe_mandate_id:
            method_projection["stripe_mandate_id"] = stripe_mandate_id
        if checkout_session_id:
            method_projection["checkout_session_id"] = checkout_session_id
        update: dict[str, object] = {
            "parent_id": parent_id,
            "stripe_customer_id": stripe_customer_id,
            "autopay_setup_intent_id": setup_intent_id,
            "autopay_setup_completed_at": completed_at,
            "updated_at": now,
            f"{role}_payment_method_id": stripe_payment_method_id,
            f"{role}_payment_method_type": payment_method_type,
            f"{role}_setup_intent_id": setup_intent_id,
            f"{role}_setup_status": setup_status,
        }
        if current_consent_id:
            update["current_autopay_consent_id"] = current_consent_id
        if consent_text_version:
            update["current_consent_text_version"] = consent_text_version
        if ach_mandate_version:
            update["current_ach_mandate_version"] = ach_mandate_version
            update.pop("current_card_disclosure_version", None)
        if card_disclosure_version:
            update["current_card_disclosure_version"] = card_disclosure_version
            update.pop("current_ach_mandate_version", None)
        if role == "primary":
            update["primary_payment_method_id"] = stripe_payment_method_id
            update["primary_payment_method_type"] = payment_method_type
            update["primary_setup_status"] = setup_status
        if role == "primary" and setup_status == "active":
            update["default_payment_method_id"] = stripe_payment_method_id
            update["payment_method_type"] = payment_method_type
            if stripe_mandate_id:
                update["stripe_mandate_id"] = stripe_mandate_id
        if stripe_mandate_id:
            update[f"{role}_stripe_mandate_id"] = stripe_mandate_id
        if checkout_session_id:
            update["autopay_setup_checkout_session_id"] = checkout_session_id
        unset: dict[str, str] = {}
        if ach_mandate_version:
            unset["current_card_disclosure_version"] = ""
        if card_disclosure_version:
            unset["current_ach_mandate_version"] = ""
        mutation: dict[str, object] = {
            "$set": update,
            "$setOnInsert": {"created_at": now},
        }
        if unset:
            mutation["$unset"] = unset
        await self._update_one(
            {"parent_id": parent_id},
            mutation,
            upsert=True,
            session=session,
        )
        await self._update_one(
            {"parent_id": parent_id},
            {"$pull": {"autopay_payment_methods": {"role": role}}},
            upsert=False,
            session=session,
        )
        await self._update_one(
            {"parent_id": parent_id},
            {"$push": {"autopay_payment_methods": method_projection}},
            upsert=False,
            session=session,
        )
