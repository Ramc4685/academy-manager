"""Stripe anti-corruption layer.

The ONLY file in v2 that may import `stripe`. Returns/accepts domain types.
Tests fake this entirely via the StripeGateway Protocol.
"""

from __future__ import annotations

import asyncio
from typing import Any

from backend.v2.contexts.billing.application.ports import StripeGateway


class RealStripeGateway(StripeGateway):
    def __init__(self, *, api_key: str, webhook_secret: str) -> None:
        # Lazy import keeps the rest of the app importable without stripe
        # installed (tests use a fake gateway).
        import stripe  # type: ignore[import-not-found]

        stripe.api_key = api_key
        self._stripe = stripe
        self._webhook_secret = webhook_secret

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
                payment_method_types=["card"],
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
                payment_method_types=["card"],
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
                    "proration_behavior": "none",
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
            raise ValueError(f"parent {parent_id} has no Stripe customer")

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
