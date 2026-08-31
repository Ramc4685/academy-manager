"""Stripe anti-corruption layer.

The ONLY file in v2 that may import `stripe`. Returns/accepts domain types.
Tests fake this entirely via the StripeGateway Protocol.
"""

from __future__ import annotations

import asyncio
import logging
import urllib.parse
from datetime import UTC, datetime
from typing import Any, Literal

from backend.v2.contexts.billing.application.ports import (
    StripeCheckoutSessionNotExpirable,
    StripeGateway,
    StripeResourceNotFound,
    StripeTransientFailure,
)

log = logging.getLogger(__name__)

# Stripe caps each metadata value at 500 characters.
_STRIPE_METADATA_VALUE_LIMIT = 500

# Registration-checkout sessions expire shortly after creation so a parent
# cannot pay a stale quote (issue #530): the amount is frozen from a
# BillingCalculationSnapshot with a 15-minute TTL, but a Checkout Session
# otherwise stays payable for ~24h. Stripe's minimum ``expires_at`` is
# 30 minutes from creation; 31 keeps a margin for clock skew so Stripe
# never rejects the create call.
_CHECKOUT_SESSION_TTL_SECONDS = 31 * 60


def _autopay_enrollment_ids_value(enrollment_ids: list[str] | None) -> str:
    """Comma-join distinct enrollment ids for Stripe metadata.

    Respects Stripe's 500-char metadata value cap by dropping WHOLE trailing
    ids (never truncating one mid-id) and logging a warning — the webhook
    worker can still activate the ids that fit.
    """
    distinct: list[str] = []
    for enrollment_id in enrollment_ids or []:
        if enrollment_id and enrollment_id not in distinct:
            distinct.append(enrollment_id)
    joined = ",".join(distinct)
    dropped = 0
    while distinct and len(joined) > _STRIPE_METADATA_VALUE_LIMIT:
        distinct.pop()
        dropped += 1
        joined = ",".join(distinct)
    if dropped:
        log.warning(
            "autopay opt-in enrollment_ids metadata exceeded %d chars — "
            "dropped %d trailing enrollment id(s), kept %d",
            _STRIPE_METADATA_VALUE_LIMIT,
            dropped,
            len(distinct),
        )
    return joined


class RealStripeGateway(StripeGateway):
    def __init__(
        self,
        *,
        api_key: str,
        webhook_secret: str,
        connect_webhook_secret: str | None = None,
        connect_client_id: str | None = None,
        skip_signature_verify: bool = False,
    ) -> None:
        # Lazy import keeps the rest of the app importable without stripe
        # installed (tests use a fake gateway).
        import stripe

        stripe.api_key = api_key
        self._stripe = stripe
        # Accounts v2 (/v2/core/accounts) is only exposed on StripeClient,
        # not the module-level namespace.
        self._client = stripe.StripeClient(api_key)
        self._webhook_secrets = [webhook_secret]
        if connect_webhook_secret and connect_webhook_secret not in self._webhook_secrets:
            self._webhook_secrets.append(connect_webhook_secret)
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
        connected_account_id: str | None = None,
    ) -> tuple[str, str]:
        """When ``connected_account_id`` is set, the checkout's PaymentIntent is a
        DESTINATION charge (``on_behalf_of`` + ``transfer_data.destination``),
        matching ``create_invoice_checkout_session`` and the autopay fund flow.
        """

        def _create() -> Any:
            request: dict[str, Any] = {
                "mode": "payment",
                "line_items": [
                    {
                        "price_data": {
                            "currency": "usd",
                            "product_data": {"name": f"Academy session {session_id}"},
                            "unit_amount": amount_cents,
                        },
                        "quantity": 1,
                    }
                ],
                "success_url": success_url,
                "cancel_url": cancel_url,
                "metadata": metadata,
                # Cap how long the frozen quote amount stays payable — see
                # _CHECKOUT_SESSION_TTL_SECONDS (issue #530).
                "expires_at": int(datetime.now(UTC).timestamp()) + _CHECKOUT_SESSION_TTL_SECONDS,
            }
            if connected_account_id:
                request["payment_intent_data"] = {
                    "metadata": metadata,
                    "on_behalf_of": connected_account_id,
                    "transfer_data": {"destination": connected_account_id},
                    "application_fee_amount": 0,
                }
            return self._stripe.checkout.Session.create(**request)

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

    async def create_autopay_setup_checkout_session(
        self,
        *,
        parent_id: str,
        enrollment_id: str,
        session_id: str,
        success_url: str,
        cancel_url: str,
        metadata: dict[str, str],
        connected_account_id: str | None = None,
    ) -> tuple[str, str]:
        setup_metadata = metadata | {
            "enrollment_id": enrollment_id,
            "session_id": session_id,
            "source": metadata.get("source") or "autopay_setup",
        }
        # Customers are created on the PLATFORM; when the academy has a connected
        # account, the eventual off-session charges route to it as the merchant of
        # record via setup_intent_data.on_behalf_of.
        setup_intent_data: dict[str, Any] = {"metadata": setup_metadata}
        if connected_account_id:
            setup_intent_data["on_behalf_of"] = connected_account_id

        def _create() -> Any:
            return self._stripe.checkout.Session.create(
                mode="setup",
                currency="usd",
                success_url=success_url,
                cancel_url=cancel_url,
                client_reference_id=parent_id,
                customer_creation="always",
                metadata=setup_metadata,
                setup_intent_data=setup_intent_data,
            )

        result = await asyncio.to_thread(_create)
        return str(result.id), str(result.url)

    async def create_invoice_checkout_session(
        self,
        *,
        invoice_id: str,
        amount_cents: int,
        currency: str,
        success_url: str,
        cancel_url: str,
        metadata: dict[str, str],
        idempotency_key: str | None = None,
        connected_account_id: str | None = None,
        save_payment_method_for_autopay: bool = False,
        autopay_enrollment_ids: list[str] | None = None,
    ) -> tuple[str, str]:
        """When ``connected_account_id`` is set, the checkout's PaymentIntent is a
        DESTINATION charge: the connected academy account is the merchant of
        record (``on_behalf_of``) and funds settle to it
        (``transfer_data.destination``) — same fund flow as
        ``create_off_session_payment_intent``. The platform accepts liability,
        so ``application_fee_amount`` stays 0.

        When ``save_payment_method_for_autopay`` is set, the payment doubles as
        an autopay enrollment: the payment method is saved for off-session use
        (``setup_future_usage``) against an always-created customer, and the
        session carries ``autopay_optin``/``enrollment_ids`` metadata for the
        completion handlers. Default False keeps the request byte-identical to
        the plain one-time payment.
        """
        session_metadata = metadata
        if save_payment_method_for_autopay:
            session_metadata = dict(metadata)
            session_metadata["autopay_optin"] = "true"
            enrollment_ids_value = _autopay_enrollment_ids_value(autopay_enrollment_ids)
            if enrollment_ids_value:
                session_metadata["enrollment_ids"] = enrollment_ids_value

        def _create() -> Any:
            payment_intent_data: dict[str, Any] = {"metadata": session_metadata}
            if save_payment_method_for_autopay:
                payment_intent_data["setup_future_usage"] = "off_session"
            if connected_account_id:
                payment_intent_data["on_behalf_of"] = connected_account_id
                payment_intent_data["transfer_data"] = {"destination": connected_account_id}
                payment_intent_data["application_fee_amount"] = 0
            request: dict[str, Any] = {
                "mode": "payment",
                "line_items": [
                    {
                        "price_data": {
                            "currency": currency,
                            "product_data": {"name": f"Academy invoice {invoice_id}"},
                            "unit_amount": amount_cents,
                        },
                        "quantity": 1,
                    }
                ],
                "success_url": success_url,
                "cancel_url": cancel_url,
                "client_reference_id": metadata.get("parent_id"),
                "metadata": session_metadata,
                "payment_intent_data": payment_intent_data,
            }
            if save_payment_method_for_autopay:
                # The saved payment method must attach to a customer.
                request["customer_creation"] = "always"
            if idempotency_key:
                request["idempotency_key"] = idempotency_key
            return self._stripe.checkout.Session.create(**request)

        result = await asyncio.to_thread(_create)
        return str(result.id), str(result.url)

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
            last_exc: Exception | None = None
            for secret in self._webhook_secrets:
                try:
                    self._stripe.Webhook.construct_event(payload, signature, secret)
                    break
                except Exception as exc:
                    last_exc = exc
            else:
                assert last_exc is not None
                raise last_exc
        return json.loads(payload)  # type: ignore[no-any-return]

    async def retrieve_checkout_session(self, checkout_session_id: str) -> dict[str, Any]:
        def _retrieve() -> Any:
            return self._stripe.checkout.Session.retrieve(checkout_session_id)

        result = await self._run_stripe_retrieve(
            _retrieve,
            label="Stripe Checkout Session",
        )
        return _stripe_object_to_dict(result)

    async def expire_checkout_session(self, checkout_session_id: str) -> None:
        def _expire() -> None:
            self._stripe.checkout.Session.expire(checkout_session_id)

        try:
            await asyncio.to_thread(_expire)
        except self._stripe.StripeError as exc:
            # Stripe refuses to expire a session that is already complete or
            # expired. That is the exact race a supersede has to survive and the
            # only failure a caller may swallow. Everything else — a connection
            # drop, a timeout, a rate limit, a 5xx — leaves the session PAYABLE,
            # and collapsing both into one ValueError is what made the swallow
            # unsafe (#549). Classify here, where the Stripe exception types are
            # actually visible; this is the only file allowed to import stripe.
            if self._is_transient_stripe_error(exc):
                raise StripeTransientFailure(
                    f"Stripe Checkout Session expiry could not be completed: {exc}"
                ) from exc
            raise StripeCheckoutSessionNotExpirable(
                f"Stripe Checkout Session expiry refused: {exc}"
            ) from exc

    def _is_transient_stripe_error(self, exc: Exception) -> bool:
        """True when the call may succeed on a retry.

        Deliberately fails SAFE: anything not recognisably a deterministic
        client-side refusal (a 4xx the API actually evaluated) counts as
        transient, so an unfamiliar failure is reconciled rather than filed away
        as "already paid".
        """
        transient_types = tuple(
            cls
            for cls in (
                getattr(self._stripe, "APIConnectionError", None),
                getattr(self._stripe, "RateLimitError", None),
                getattr(self._stripe, "APIError", None),
            )
            if isinstance(cls, type)
        )
        if transient_types and isinstance(exc, transient_types):
            # `stripe.APIError` is the generic 5xx/unknown-response class, and
            # the deterministic refusals (InvalidRequestError, ...) are siblings
            # of it rather than subclasses.
            return True
        status = getattr(exc, "http_status", None)
        if status is None:
            # No HTTP exchange completed — the request never got an answer.
            return True
        return int(status) >= 500 or int(status) == 429

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

    async def retrieve_setup_intent(self, stripe_setup_intent_id: str) -> dict[str, Any]:
        def _retrieve() -> Any:
            return self._stripe.SetupIntent.retrieve(stripe_setup_intent_id)

        result = await self._run_stripe_retrieve(_retrieve, label="Stripe SetupIntent")
        return _stripe_object_to_dict(result)

    async def retrieve_payment_method(self, stripe_payment_method_id: str) -> dict[str, Any]:
        def _retrieve() -> Any:
            return self._stripe.PaymentMethod.retrieve(stripe_payment_method_id)

        result = await self._run_stripe_retrieve(_retrieve, label="Stripe PaymentMethod")
        return _stripe_object_to_dict(result)

    async def set_customer_default_payment_method(
        self,
        *,
        stripe_customer_id: str,
        stripe_payment_method_id: str,
        metadata: dict[str, str],
    ) -> None:
        def _modify() -> Any:
            return self._stripe.Customer.modify(
                stripe_customer_id,
                invoice_settings={"default_payment_method": stripe_payment_method_id},
                metadata=metadata,
            )

        try:
            await asyncio.to_thread(_modify)
        except self._stripe.StripeError as exc:
            raise ValueError(
                f"Stripe Customer default payment method update failed: {exc}"
            ) from exc

    async def search_app_owned_payment_intents(
        self, *, academy_id: str, limit: int = 100, stripe_account: str | None = None
    ) -> list[dict[str, Any]]:
        safe_academy_id = academy_id.replace('"', '\\"')
        safe_limit = max(1, min(int(limit), 100))
        # `succeeded` covers card/instant settlement; `processing` is the ACH
        # in-flight state (§7.2) — both must be visible to reconciliation, or
        # ACH payments are invisible until they happen to also show up via a
        # later run after settlement.
        queries = [
            f'metadata["academy_id"]:"{safe_academy_id}" AND status:"succeeded"',
            f'metadata["academy_id"]:"{safe_academy_id}" AND status:"processing"',
        ]

        def _search() -> list[dict[str, Any]]:
            by_id: dict[str, dict[str, Any]] = {}
            for query in queries:
                kwargs: dict[str, Any] = {"query": query, "limit": safe_limit}
                if stripe_account:
                    kwargs["stripe_account"] = stripe_account
                payment_intents = self._stripe.PaymentIntent.search(**kwargs)
                data = getattr(payment_intents, "data", None) or []
                for item in data:
                    converted = _stripe_object_to_dict(item)
                    pi_id = str(converted.get("id") or "")
                    if pi_id and pi_id not in by_id:
                        by_id[pi_id] = converted
            return list(by_id.values())[:safe_limit]

        try:
            return await asyncio.to_thread(_search)
        except self._stripe.StripeError as exc:
            raise ValueError(f"Stripe PaymentIntent search failed: {exc}") from exc

    async def list_charges_for_customer(
        self, *, stripe_customer_id: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 100))

        def _list() -> list[dict[str, Any]]:
            charges = self._stripe.Charge.list(
                customer=stripe_customer_id,
                limit=safe_limit,
            )
            data = getattr(charges, "data", None) or []
            return [_stripe_object_to_dict(item) for item in data]

        try:
            return await asyncio.to_thread(_list)
        except self._stripe.StripeError as exc:
            raise ValueError(f"Stripe Charge list failed: {exc}") from exc

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
                proration_behavior="none",
                metadata={
                    "app_proration_period_start": billing_period_start.isoformat(),
                    "app_proration_period_end": billing_period_end.isoformat(),
                },
            )
            return ""

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

    async def create_connected_account(
        self,
        *,
        academy_id: str,
        display_name: str | None = None,
        contact_email: str | None = None,
        idempotency_key: str | None = None,
    ) -> str:
        """Create an Accounts v2 connected account via ``POST /v2/core/accounts``.

        Configured through Accounts v2 ``configuration`` and
        ``defaults.responsibilities`` (never legacy ``type`` or v1
        ``controller``). The platform accepts payment liability for destination
        charges and uses an idempotency key so retries after local persistence
        failures do not create duplicate Stripe accounts.
        """
        request: dict[str, Any] = {
            # Express dashboard: Stripe rejects "full" when the application
            # collects fees/losses (destination charges, platform liability).
            "dashboard": "express",
            "configuration": {
                "merchant": {
                    "capabilities": {
                        "card_payments": {"requested": True},
                    }
                },
                # Destination charges transfer funds to the connected account,
                # which requires the recipient stripe_transfers capability —
                # without it Stripe rejects checkout/PI creation with
                # insufficient_capabilities_for_transfer.
                "recipient": {
                    "capabilities": {
                        "stripe_balance": {
                            "stripe_transfers": {"requested": True},
                        }
                    }
                },
            },
            "defaults": {
                "currency": "usd",
                "responsibilities": {
                    "fees_collector": "application",
                    "losses_collector": "application",
                },
            },
            "identity": {"country": "us"},
            "metadata": {"academy_id": academy_id},
        }
        if display_name:
            request["display_name"] = display_name
        if contact_email:
            request["contact_email"] = contact_email

        def _create() -> Any:
            return self._client.v2.core.accounts.create(
                params=request,
                options={"idempotency_key": idempotency_key or f"connect-account:{academy_id}"},
            )

        try:
            account = await asyncio.to_thread(_create)
        except self._stripe.StripeError as exc:
            raise ValueError(f"Stripe connected account creation failed: {exc}") from exc
        return str(account["id"])

    async def create_account_onboarding_link(
        self,
        *,
        stripe_account_id: str,
        refresh_url: str,
        return_url: str,
    ) -> str:
        """Create a hosted onboarding AccountLink for the connected account."""

        def _create() -> Any:
            return self._stripe.AccountLink.create(
                account=stripe_account_id,
                refresh_url=refresh_url,
                return_url=return_url,
                type="account_onboarding",
            )

        try:
            link = await asyncio.to_thread(_create)
        except self._stripe.StripeError as exc:
            raise ValueError(f"Stripe account onboarding link creation failed: {exc}") from exc
        return str(link["url"])

    async def _run_stripe_retrieve(self, fn: Any, *, label: str) -> Any:
        try:
            return await asyncio.to_thread(fn)
        except self._stripe.StripeError as exc:
            # Stripe returns http_status 404 for unknown resource ids (e.g.
            # "No such payment_intent"). Surface as a typed not-found so callers
            # map it to 404 instead of a 500; everything else stays a 5xx-class
            # lookup failure.
            if getattr(exc, "http_status", None) == 404:
                raise StripeResourceNotFound(f"{label} not found: {exc}") from exc
            raise ValueError(f"{label} lookup failed: {exc}") from exc

    async def get_default_payment_method(
        self, *, academy_id: str, parent_id: str
    ) -> tuple[str, str] | None:
        """Return (stripe_customer_id, payment_method_id) or None if no saved card."""

        def _find() -> tuple[str, str] | None:
            query = f'metadata["academy_id"]:"{academy_id}" AND metadata["parent_id"]:"{parent_id}"'
            customers = self._stripe.Customer.search(
                query=query,
                limit=1,
            )
            data = getattr(customers, "data", None) or []
            if not data:
                return None
            customer = data[0]
            invoice_settings = getattr(customer, "invoice_settings", None)
            pm_id = getattr(invoice_settings, "default_payment_method", None)
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
        connected_account_id: str | None = None,
    ) -> tuple[str, str, str | None]:
        """Return (pi_id, pi_status, decline_code_or_None).

        Slice I: when ``connected_account_id`` is set, this is a DESTINATION
        charge — the connected academy account is the merchant of record
        (``on_behalf_of``) and funds settle to it (``transfer_data.destination``).
        The platform accepts liability, so ``application_fee_amount`` stays 0.
        The Customer stays on the platform (no ``stripe_account`` header).
        """

        def _create() -> Any:
            request: dict[str, Any] = {
                "amount": amount_cents,
                "currency": currency,
                "customer": customer_id,
                "payment_method": payment_method_id,
                "off_session": True,
                "confirm": True,
                "idempotency_key": idempotency_key,
                "metadata": metadata,
            }
            if connected_account_id:
                request["on_behalf_of"] = connected_account_id
                request["transfer_data"] = {"destination": connected_account_id}
                request["application_fee_amount"] = 0
            return self._stripe.PaymentIntent.create(**request)

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
