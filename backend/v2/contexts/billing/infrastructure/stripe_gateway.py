"""Stripe anti-corruption layer.

The ONLY file in v2 that may import `stripe`. Returns/accepts domain types.
Tests fake this entirely via the StripeGateway Protocol.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Literal

from backend.v2.contexts.billing.application.ports import StripeGateway


class RealStripeGateway(StripeGateway):
    def __init__(
        self, *, api_key: str, webhook_secret: str, connect_client_id: str | None = None
    ) -> None:
        # Lazy import keeps the rest of the app importable without stripe
        # installed (tests use a fake gateway).
        import stripe  # type: ignore[import-not-found]

        stripe.api_key = api_key
        self._stripe = stripe
        self._webhook_secret = webhook_secret
        self._connect_client_id = connect_client_id

    async def create_checkout_session(
        self,
        *,
        parent_id: str,
        session_id: str,
        amount_cents: int,
        success_url: str,
        cancel_url: str,
        metadata: dict[str, str],
    ) -> tuple[str, str]:
        def _create() -> Any:
            return self._stripe.checkout.Session.create(
                mode="payment",
                line_items=[
                    {
                        "price_data": {
                            "currency": "usd",
                            "product_data": {"name": f"Academy session {session_id}"},
                            "unit_amount": amount_cents,
                        },
                        "quantity": 1,
                    }
                ],
                success_url=success_url,
                cancel_url=cancel_url,
                metadata=metadata,
            )

        result = await asyncio.to_thread(_create)
        return str(result.id), str(result.url)

    async def create_subscription_checkout_session(
        self,
        *,
        parent_id: str,
        enrollment_id: str,
        session_id: str,
        amount_cents: int,
        success_url: str,
        cancel_url: str,
        metadata: dict[str, str],
    ) -> tuple[str, str, str]:
        def _create() -> Any:
            return self._stripe.checkout.Session.create(
                mode="subscription",
                line_items=[
                    {
                        "price_data": {
                            "currency": "usd",
                            "product_data": {"name": f"Academy session {session_id}"},
                            "unit_amount": amount_cents,
                            "recurring": {"interval": "month"},
                        },
                        "quantity": 1,
                    }
                ],
                success_url=success_url,
                cancel_url=cancel_url,
                client_reference_id=parent_id,
                metadata=metadata,
                subscription_data={
                    "metadata": metadata | {"enrollment_id": enrollment_id},
                },
            )

        result = await asyncio.to_thread(_create)
        stripe_subscription_id = str(getattr(result, "subscription", "") or "")
        return str(result.id), str(result.url), stripe_subscription_id

    async def create_customer_portal_session(
        self,
        *,
        parent_id: str,
        return_url: str,
        stripe_customer_id: str | None,
    ) -> str:
        if not stripe_customer_id:
            raise ValueError(
                "Billing portal will be available after the first successful autopay setup."
            )

        def _create() -> Any:
            return self._stripe.billing_portal.Session.create(
                customer=stripe_customer_id,
                return_url=return_url,
            )

        result = await asyncio.to_thread(_create)
        return str(result.url)

    def verify_webhook(self, payload: bytes, signature: str) -> dict[str, object]:
        return self._stripe.Webhook.construct_event(payload, signature, self._webhook_secret)  # type: ignore[no-any-return]

    async def issue_refund(self, payment_intent_id: str, amount_cents: int | None) -> str:
        def _create() -> Any:
            kwargs: dict[str, Any] = {"payment_intent": payment_intent_id}
            if amount_cents is not None:
                kwargs["amount"] = amount_cents
            return self._stripe.Refund.create(**kwargs)

        result = await asyncio.to_thread(_create)
        return str(result.id)

    async def cancel_subscription(
        self, stripe_subscription_id: str, *, at_period_end: bool
    ) -> None:
        def _cancel() -> None:
            if at_period_end:
                self._stripe.Subscription.modify(
                    stripe_subscription_id,
                    cancel_at_period_end=True,
                )
            else:
                self._stripe.Subscription.delete(stripe_subscription_id)

        await asyncio.to_thread(_cancel)

    async def pause_subscription_collection(
        self,
        stripe_subscription_id: str,
        *,
        behavior: Literal["void", "keep_as_draft", "mark_uncollectible"] = "void",
    ) -> None:
        def _pause() -> None:
            self._stripe.Subscription.modify(
                stripe_subscription_id,
                pause_collection={"behavior": behavior},
            )

        await asyncio.to_thread(_pause)

    async def resume_subscription_collection(self, stripe_subscription_id: str) -> None:
        def _resume() -> None:
            self._stripe.Subscription.modify(
                stripe_subscription_id,
                pause_collection="",
            )

        await asyncio.to_thread(_resume)

    async def update_subscription_proration(
        self,
        stripe_subscription_id: str,
        *,
        new_price_cents: int,
        billing_period_start: datetime,
        billing_period_end: datetime,
    ) -> str:
        def _update() -> str:
            subscription = self._stripe.Subscription.retrieve(stripe_subscription_id)
            item_id = subscription["items"]["data"][0]["id"]
            self._stripe.Subscription.modify(
                stripe_subscription_id,
                items=[
                    {
                        "id": item_id,
                        "price_data": {
                            "currency": "usd",
                            "product_data": {"name": "Academy session type"},
                            "unit_amount": new_price_cents,
                            "recurring": {"interval": "month"},
                        },
                    }
                ],
                proration_behavior="create_prorations",
                proration_date=int(billing_period_start.timestamp()),
            )
            invoice = self._stripe.Invoice.create(
                subscription=stripe_subscription_id,
                metadata={
                    "billing_period_start": billing_period_start.isoformat(),
                    "billing_period_end": billing_period_end.isoformat(),
                },
            )
            finalized = self._stripe.Invoice.finalize_invoice(invoice["id"])
            return str(finalized["id"])

        return await asyncio.to_thread(_update)
