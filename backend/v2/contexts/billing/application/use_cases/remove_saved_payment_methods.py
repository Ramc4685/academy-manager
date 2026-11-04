"""Remove a family's saved cards when its account is deleted (mobile M5, D3).

The Stripe customer is kept (owner decision 6) so refunds and disputes on past
payments still work during the 7-year retention; only the payment methods go,
at Stripe and in ``parent_billing_customers``. Runs inside the academy's tenant
scope. Idempotent: a second run finds nothing to detach.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from backend.v2.contexts.billing.application.ports import StripeGateway


class SavedPaymentMethodStore(Protocol):
    async def customer_ref(self, *, parent_id: str) -> tuple[str, str | None] | None: ...

    async def clear_saved_payment_methods(self, *, parent_id: str) -> None: ...


class RemoveSavedPaymentMethods:
    def __init__(self, *, customers: SavedPaymentMethodStore, stripe: StripeGateway) -> None:
        self._customers = customers
        self._stripe = stripe

    async def execute(self, *, parent_ids: Sequence[str]) -> int:
        detached = 0
        for parent_id in parent_ids:
            ref = await self._customers.customer_ref(parent_id=parent_id)
            if ref is None:
                continue
            customer_id, stripe_account = ref
            # Stripe first: if it fails, the local fields still point at the
            # cards and the retry detaches them.
            detached += await self._stripe.detach_customer_payment_methods(
                customer_id, stripe_account=stripe_account
            )
            await self._customers.clear_saved_payment_methods(parent_id=parent_id)
        return detached
