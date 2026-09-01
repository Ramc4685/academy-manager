"""Fake StripeGateway for dev/test.

Records calls; returns deterministic IDs. Real Stripe stays out of CI.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from backend.v2.contexts.billing.application.ports import (
    StripeCheckoutSessionNotExpirable,
    StripeGateway,
)
from backend.v2.shared.ids import new_ulid


class FakeStripeGateway(StripeGateway):
    def __init__(self) -> None:
        self.checkouts: list[dict[str, Any]] = []
        self.subscription_checkouts: list[dict[str, Any]] = []
        self.autopay_setup_checkouts: list[dict[str, Any]] = []
        self.portal_sessions: list[dict[str, Any]] = []
        self.refunds: list[dict[str, Any]] = []
        self.cancelled_subscriptions: list[dict[str, Any]] = []
        self.paused_subscriptions: list[dict[str, Any]] = []
        self.resumed_subscriptions: list[dict[str, Any]] = []
        self.subscription_prorations: list[dict[str, Any]] = []
        self.connect_links: list[dict[str, str]] = []
        self.connect_codes: list[str] = []
        # Slice I — Connect (Accounts v2 + destination charges).
        self.connected_accounts: list[dict[str, Any]] = []
        self.account_onboarding_links: list[dict[str, Any]] = []
        self.off_session_payment_intents: list[dict[str, Any]] = []
        self.payment_intents: list[dict[str, Any]] = []
        self.setup_intents: dict[str, dict[str, Any]] = {}
        self.payment_methods: dict[str, dict[str, Any]] = {}
        self.customer_default_payment_methods: list[dict[str, Any]] = []
        # customer_id -> list of charge dicts (legacy match candidates, #242 WI-3)
        self.charges_by_customer: dict[str, list[dict[str, Any]]] = {}
        # stripe_account -> extra PaymentIntents only visible when a
        # reconciliation search is scoped to that connected account (Slice I).
        self.connected_payment_intents: dict[str, list[dict[str, Any]]] = {}
        # Checkout sessions retired by a supersede.
        self.expired_checkouts: list[str] = []
        # Ids that refuse to expire, mirroring Stripe's behaviour for a session
        # that is already complete or expired. Tests add to this to exercise
        # the "parent paid on the old tab" race.
        self.unexpirable_checkouts: set[str] = set()

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
        checkout_id = f"cs_test_{new_ulid()}"
        record = {
            "checkout_id": checkout_id,
            "parent_id": parent_id,
            "session_id": session_id,
            "amount_cents": amount_cents,
            "success_url": success_url,
            "cancel_url": cancel_url,
            "metadata": metadata,
            "connected_account_id": connected_account_id,
        }
        self.checkouts.append(record)
        return checkout_id, f"https://fake.stripe.com/c/{checkout_id}"

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
        checkout_id = f"cs_sub_test_{new_ulid()}"
        stripe_subscription_id = f"sub_test_{new_ulid()}"
        self.subscription_checkouts.append(
            {
                "checkout_id": checkout_id,
                "stripe_subscription_id": stripe_subscription_id,
                "parent_id": parent_id,
                "enrollment_id": enrollment_id,
                "session_id": session_id,
                "amount_cents": amount_cents,
                "success_url": success_url,
                "cancel_url": cancel_url,
                "metadata": metadata,
            }
        )
        return checkout_id, f"https://fake.stripe.com/c/{checkout_id}", stripe_subscription_id

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
        checkout_id = f"cs_setup_test_{new_ulid()}"
        setup_intent_id = f"seti_fake_{checkout_id}"
        payment_method_id = f"pm_fake_{checkout_id}"
        self.autopay_setup_checkouts.append(
            {
                "checkout_id": checkout_id,
                "parent_id": parent_id,
                "enrollment_id": enrollment_id,
                "session_id": session_id,
                "success_url": success_url,
                "cancel_url": cancel_url,
                "metadata": metadata,
                "setup_intent_id": setup_intent_id,
                # Slice I: connected academy account the eventual off-session
                # charges route to (setup_intent_data.on_behalf_of).
                "connected_account_id": connected_account_id,
            }
        )
        self.setup_intents[setup_intent_id] = {
            "id": setup_intent_id,
            "object": "setup_intent",
            "customer": "cus_fake_parent",
            "payment_method": payment_method_id,
            "mandate": f"mandate_fake_{checkout_id}",
            "metadata": dict(metadata),
        }
        self.payment_methods[payment_method_id] = {
            "id": payment_method_id,
            "object": "payment_method",
            "type": "card",
        }
        return checkout_id, f"https://fake.stripe.com/c/{checkout_id}"

    async def create_customer_portal_session(
        self,
        *,
        parent_id: str,
        return_url: str,
        stripe_customer_id: str | None,
    ) -> str:
        portal_id = f"bps_test_{new_ulid()}"
        self.portal_sessions.append(
            {
                "portal_id": portal_id,
                "parent_id": parent_id,
                "return_url": return_url,
                "stripe_customer_id": stripe_customer_id,
            }
        )
        return f"https://fake.stripe.com/portal/{portal_id}"

    def verify_webhook(self, payload: bytes, signature: str) -> dict[str, object]:
        # Tests pass already-parsed events as JSON body and a fixed sig.
        if signature != "test_signature":
            raise ValueError("invalid signature")
        return json.loads(payload.decode("utf-8"))

    async def retrieve_checkout_session(self, checkout_session_id: str) -> dict[str, Any]:
        for record in self.subscription_checkouts + self.autopay_setup_checkouts + self.checkouts:
            if record["checkout_id"] == checkout_session_id:
                metadata = dict(record.get("metadata") or {})
                return {
                    "id": checkout_session_id,
                    "object": "checkout.session",
                    "status": "complete",
                    "payment_status": "paid",
                    "amount_total": record.get("amount_cents"),
                    "currency": "usd",
                    "customer": "cus_fake_parent",
                    "subscription": record.get("stripe_subscription_id"),
                    "setup_intent": record.get(
                        "setup_intent_id", f"seti_fake_{checkout_session_id}"
                    ),
                    "invoice": f"in_fake_{checkout_session_id}",
                    "client_reference_id": record.get("parent_id"),
                    "metadata": metadata,
                }
        return {"id": checkout_session_id, "object": "checkout.session"}

    async def expire_checkout_session(self, checkout_session_id: str) -> None:
        if checkout_session_id in self.unexpirable_checkouts:
            # Mirrors the real gateway: "unexpirable" means already complete or
            # expired, which is the TERMINAL case callers may swallow. A generic
            # ValueError here would fake the transient case instead (#549).
            raise StripeCheckoutSessionNotExpirable(
                f"checkout session is not expirable: {checkout_session_id}"
            )
        self.expired_checkouts.append(checkout_session_id)

    async def retrieve_invoice(self, stripe_invoice_id: str) -> dict[str, Any]:
        return {
            "id": stripe_invoice_id,
            "object": "invoice",
            "status": "paid",
            "amount_paid": 0,
            "currency": "usd",
            "payment_intent": f"pi_fake_{stripe_invoice_id}",
        }

    async def retrieve_subscription(self, stripe_subscription_id: str) -> dict[str, Any]:
        return {
            "id": stripe_subscription_id,
            "object": "subscription",
        }

    async def retrieve_payment_intent(self, stripe_payment_intent_id: str) -> dict[str, Any]:
        return {
            "id": stripe_payment_intent_id,
            "object": "payment_intent",
        }

    async def retrieve_setup_intent(self, stripe_setup_intent_id: str) -> dict[str, Any]:
        return self.setup_intents.get(
            stripe_setup_intent_id,
            {
                "id": stripe_setup_intent_id,
                "object": "setup_intent",
                "customer": "cus_fake_parent",
                "payment_method": f"pm_fake_{stripe_setup_intent_id}",
                "metadata": {},
            },
        )

    async def retrieve_payment_method(self, stripe_payment_method_id: str) -> dict[str, Any]:
        return self.payment_methods.get(
            stripe_payment_method_id,
            {
                "id": stripe_payment_method_id,
                "object": "payment_method",
                "type": "card",
            },
        )

    async def set_customer_default_payment_method(
        self,
        *,
        stripe_customer_id: str,
        stripe_payment_method_id: str,
        metadata: dict[str, str],
    ) -> None:
        self.customer_default_payment_methods.append(
            {
                "stripe_customer_id": stripe_customer_id,
                "stripe_payment_method_id": stripe_payment_method_id,
                "metadata": metadata,
            }
        )

    async def search_app_owned_payment_intents(
        self, *, academy_id: str, limit: int = 100, stripe_account: str | None = None
    ) -> list[dict[str, Any]]:
        source = (
            self.connected_payment_intents.get(stripe_account, [])
            if stripe_account
            else self.payment_intents
        )
        matched = [
            pi
            for pi in source
            if str((pi.get("metadata") or {}).get("academy_id") or "") == academy_id
            and str(pi.get("status") or "").lower() in {"succeeded", "processing"}
        ]
        return matched[: max(1, min(int(limit), 100))]

    async def list_charges_for_customer(
        self, *, stripe_customer_id: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        charges = self.charges_by_customer.get(stripe_customer_id, [])
        return charges[: max(1, min(int(limit), 100))]

    async def issue_refund(self, payment_intent_id: str, amount_cents: int | None) -> str:
        refund_id = f"re_test_{new_ulid()}"
        self.refunds.append(
            {
                "refund_id": refund_id,
                "payment_intent_id": payment_intent_id,
                "amount_cents": amount_cents,
            }
        )
        return refund_id

    async def cancel_subscription(
        self, stripe_subscription_id: str, *, at_period_end: bool
    ) -> None:
        self.cancelled_subscriptions.append(
            {
                "stripe_subscription_id": stripe_subscription_id,
                "at_period_end": at_period_end,
            }
        )

    async def pause_subscription_collection(
        self,
        stripe_subscription_id: str,
        *,
        behavior: str = "void",
    ) -> None:
        self.paused_subscriptions.append(
            {
                "stripe_subscription_id": stripe_subscription_id,
                "behavior": behavior,
            }
        )

    async def resume_subscription_collection(self, stripe_subscription_id: str) -> None:
        self.resumed_subscriptions.append({"stripe_subscription_id": stripe_subscription_id})

    async def update_subscription_proration(
        self,
        stripe_subscription_id: str,
        *,
        new_price_cents: int,
        billing_period_start: datetime,
        billing_period_end: datetime,
    ) -> str:
        self.subscription_prorations.append(
            {
                "stripe_subscription_id": stripe_subscription_id,
                "new_price_cents": new_price_cents,
                "billing_period_start": billing_period_start,
                "billing_period_end": billing_period_end,
            }
        )
        return ""

    def create_connect_link(self, *, redirect_uri: str, state: str) -> str:
        self.connect_links.append({"redirect_uri": redirect_uri, "state": state})
        return f"https://fake-stripe-connect.example.com/oauth?state={state}&redirect_uri={redirect_uri}"

    async def exchange_connect_code(self, code: str) -> str:
        self.connect_codes.append(code)
        return f"acct_fake_{code}"

    async def create_connected_account(
        self,
        *,
        academy_id: str,
        display_name: str | None = None,
        contact_email: str | None = None,
        idempotency_key: str | None = None,
    ) -> str:
        account_id = f"acct_fake_{academy_id}_{new_ulid()}"
        self.connected_accounts.append(
            {
                "stripe_account_id": account_id,
                "academy_id": academy_id,
                "display_name": display_name,
                "contact_email": contact_email,
                "idempotency_key": idempotency_key or f"connect-account:{academy_id}",
                "dashboard": "full",
                "configuration": {
                    "merchant": {
                        "capabilities": {
                            "card_payments": {"requested": True},
                        }
                    }
                },
                "defaults": {
                    "currency": "usd",
                    "responsibilities": {
                        "fees_collector": "application",
                        "losses_collector": "application",
                    },
                },
            }
        )
        return account_id

    async def create_account_onboarding_link(
        self,
        *,
        stripe_account_id: str,
        refresh_url: str,
        return_url: str,
    ) -> str:
        self.account_onboarding_links.append(
            {
                "stripe_account_id": stripe_account_id,
                "refresh_url": refresh_url,
                "return_url": return_url,
            }
        )
        return f"https://fake-stripe-connect.example.com/onboard/{stripe_account_id}"

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
        pi_id = f"pi_fake_{new_ulid()}"
        record: dict[str, Any] = {
            "id": pi_id,
            "amount_cents": amount_cents,
            "currency": currency,
            "customer_id": customer_id,
            "payment_method_id": payment_method_id,
            "idempotency_key": idempotency_key,
            "metadata": dict(metadata),
            # Slice I: destination-charge routing (on_behalf_of +
            # transfer_data.destination) when the academy has a connected account.
            "connected_account_id": connected_account_id,
            "on_behalf_of": connected_account_id,
            "transfer_data": (
                {"destination": connected_account_id} if connected_account_id else None
            ),
            "application_fee_amount": 0 if connected_account_id else None,
        }
        self.off_session_payment_intents.append(record)
        return pi_id, "succeeded", None
