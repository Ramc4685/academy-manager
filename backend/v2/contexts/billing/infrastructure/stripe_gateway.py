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

    def verify_webhook(self, payload: bytes, signature: str) -> dict[str, object]:
        return self._stripe.Webhook.construct_event(
            payload, signature, self._webhook_secret
        )  # type: ignore[no-any-return]

    async def issue_refund(self, payment_intent_id: str, amount_cents: int | None) -> str:
        def _create() -> Any:
            kwargs: dict[str, Any] = {"payment_intent": payment_intent_id}
            if amount_cents is not None:
                kwargs["amount"] = amount_cents
            return self._stripe.Refund.create(**kwargs)

        result = await asyncio.to_thread(_create)
        return str(result.id)
