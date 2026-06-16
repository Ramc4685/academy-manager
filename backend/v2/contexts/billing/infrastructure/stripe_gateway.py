"""Stripe anti-corruption layer.

The ONLY file in v2 that may import `stripe`. Returns/accepts domain types.
Tests fake this entirely via the StripeGateway Protocol.
"""

from __future__ import annotations

import asyncio
import urllib.parse
from datetime import datetime
from typing import Any, Literal

from backend.v2.contexts.billing.application.ports import StripeGateway


class RealStripeGateway(StripeGateway):
    def __init__(
        self,
        *,
        api_key: str,
        webhook_secret: str,
        connect_client_id: str | None = None,
        skip_signature_verify: bool = False,
    ) -> None:
        # Lazy import keeps the rest of the app importable without stripe
        # installed (tests use a fake gateway).
        import stripe  # type: ignore[import-not-found]

        stripe.api_key = api_key
        self._stripe = stripe
        self._webhook_secret = webhook_secret
        self._connect_client_id = connect_client_id
        self._skip_signature_verify = skip_signature_verify

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
        import json

        if not self._skip_signature_verify:
            # Raises SignatureVerificationError on mismatch. We discard the
            # returned stripe.Event because in stripe-python >=15 StripeObject
            # no longer subclasses dict; the handler requires a plain dict, so
            # we parse the (now verified) raw payload instead.
            self._stripe.Webhook.construct_event(payload, signature, self._webhook_secret)
        return json.loads(payload)  # type: ignore[no-any-return]

    async def retrieve_checkout_session(self, checkout_session_id: str) -> dict[str, Any]:
        def _retrieve() -> Any:
            return self._stripe.checkout.Session.retrieve(checkout_session_id)

        result = await self._run_stripe_retrieve(
            _retrieve,
            label="Stripe Checkout Session",
        )
        return _stripe_object_to_dict(result)

    async def retrieve_invoice(self, stripe_invoice_id: str) -> dict[str, Any]:
        def _retrieve() -> Any:
            return self._stripe.Invoice.retrieve(stripe_invoice_id)

        result = await self._run_stripe_retrieve(_retrieve, label="Stripe Invoice")
        return _stripe_object_to_dict(result)

    async def retrieve_subscription(self, stripe_subscription_id: str) -> dict[str, Any]:
        def _retrieve() -> Any:
            return self._stripe.Subscription.retrieve(stripe_subscription_id)

        result = await self._run_stripe_retrieve(_retrieve, label="Stripe Subscription")
        return _stripe_object_to_dict(result)

    async def retrieve_payment_intent(self, stripe_payment_intent_id: str) -> dict[str, Any]:
        def _retrieve() -> Any:
            return self._stripe.PaymentIntent.retrieve(stripe_payment_intent_id)

        result = await self._run_stripe_retrieve(_retrieve, label="Stripe PaymentIntent")
        return _stripe_object_to_dict(result)

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

    def create_connect_link(self, *, redirect_uri: str, state: str) -> str:
        if not self._connect_client_id:
            raise ValueError("Stripe Connect client ID is not configured")
        params = urllib.parse.urlencode(
            {
                "client_id": self._connect_client_id,
                "response_type": "code",
                "scope": "read_write",
                "redirect_uri": redirect_uri,
                "state": state,
            }
        )
        return f"https://connect.stripe.com/oauth/authorize?{params}"

    async def exchange_connect_code(self, code: str) -> str:
        def _exchange() -> str:
            try:
                response = self._stripe.OAuth.token(grant_type="authorization_code", code=code)
            except self._stripe.StripeError as exc:
                raise ValueError(f"Stripe Connect code exchange failed: {exc}") from exc
            account_id = response.get("stripe_user_id")
            if not account_id:
                raise ValueError("Stripe Connect code exchange returned no stripe_user_id")
            return str(account_id)

        return await asyncio.to_thread(_exchange)

    async def _run_stripe_retrieve(self, fn: Any, *, label: str) -> Any:
        try:
            return await asyncio.to_thread(fn)
        except self._stripe.StripeError as exc:
            raise ValueError(f"{label} lookup failed: {exc}") from exc

    async def get_default_payment_method(
        self, *, academy_id: str, parent_id: str
    ) -> tuple[str, str] | None:
        """Return (stripe_customer_id, payment_method_id) or None if no saved card."""

        def _find() -> tuple[str, str] | None:
            query = (
                f'metadata["academy_id"]:"{academy_id}" ' f'AND metadata["parent_id"]:"{parent_id}"'
            )
            customers = self._stripe.Customer.search(
                query=query,
                limit=1,
            )
            data = customers.get("data", [])
            if not data:
                return None
            customer = data[0]
            pm_id = (customer.get("invoice_settings") or {}).get("default_payment_method")
            if not pm_id:
                return None
            return str(customer["id"]), str(pm_id)

        try:
            return await asyncio.to_thread(_find)
        except self._stripe.StripeError as exc:
            raise ValueError(f"Stripe customer lookup failed: {exc}") from exc

    async def create_off_session_payment_intent(
        self,
        *,
        amount_cents: int,
        currency: str,
        customer_id: str,
        payment_method_id: str,
        idempotency_key: str,
        metadata: dict[str, str],
    ) -> tuple[str, str, str | None]:
        """Return (pi_id, pi_status, decline_code_or_None)."""

        def _create() -> Any:
            return self._stripe.PaymentIntent.create(
                amount=amount_cents,
                currency=currency,
                customer=customer_id,
                payment_method=payment_method_id,
                off_session=True,
                confirm=True,
                idempotency_key=idempotency_key,
                metadata=metadata,
            )

        try:
            pi = await asyncio.to_thread(_create)
            return str(pi["id"]), str(pi["status"]), None
        except self._stripe.CardError as exc:
            err = exc.error
            return "", "failed", str(getattr(err, "decline_code", None) or str(exc))
        except self._stripe.StripeError as exc:
            raise ValueError(f"Stripe PaymentIntent creation failed: {exc}") from exc


def _stripe_object_to_dict(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        return result
    to_dict = getattr(result, "to_dict_recursive", None)
    if callable(to_dict):
        return to_dict()
    private_to_dict = getattr(result, "_to_dict_recursive", None)
    if callable(private_to_dict):
        return private_to_dict()
    return dict(result)
