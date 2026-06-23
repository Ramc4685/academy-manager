"""Mongo repository for Stripe subscription invoice business processing state."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.v2.shared.tenancy import TenantScopedRepository


class MongoStripeInvoiceProcessingRepository(TenantScopedRepository):
    collection_name = "stripe_invoice_processing"

    async def record_recovery_point(
        self,
        *,
        academy_id: str,
        stripe_invoice_id: str,
        stripe_subscription_id: str | None,
        event_id: str,
        recovery_point: str,
        ledger_invoice_id: str | None = None,
        ledger_payment_id: str | None = None,
        legacy_payment_id: str | None = None,
        last_error: str | None = None,
        updated_at: datetime,
    ) -> None:
        business_key = f"stripe_invoice:{stripe_invoice_id}"
        set_fields: dict[str, Any] = {
            "academy_id": academy_id,
            "business_key": business_key,
            "stripe_invoice_id": stripe_invoice_id,
            "stripe_subscription_id": stripe_subscription_id,
            "recovery_point": recovery_point,
            "last_error": last_error,
            "updated_at": updated_at,
        }
        if ledger_invoice_id is not None:
            set_fields["ledger_invoice_id"] = ledger_invoice_id
        if ledger_payment_id is not None:
            set_fields["ledger_payment_id"] = ledger_payment_id
        if legacy_payment_id is not None:
            set_fields["legacy_payment_id"] = legacy_payment_id

        await self.collection.update_one(
            {"academy_id": academy_id, "business_key": business_key},
            {
                "$set": set_fields,
                "$addToSet": {"event_ids": event_id},
                "$setOnInsert": {"created_at": updated_at},
            },
            upsert=True,
        )
