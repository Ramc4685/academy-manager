"""Fake StripeGateway for dev/test.

Records calls; returns deterministic IDs. Real Stripe stays out of CI.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from backend.v2.contexts.billing.application.ports import StripeGateway
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
        self.payment_intents: list[dict[str, Any]] = []
        # customer_id -> list of charge dicts (legacy match candidates, #242 WI-3)
        self.charges_by_customer: dict[str, list[dict[str, Any]]] = {}

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
        checkout_id = f"cs_test_{new_ulid()}"
        record = {
            "checkout_id": checkout_id,
            "parent_id": parent_id,
            "session_id": session_id,
            "amount_cents": amount_cents,
            "success_url": success_url,
            "cancel_url": cancel_url,
            "metadata": metadata,
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
    ) -> tuple[str, str]:
        checkout_id = f"cs_setup_test_{new_ulid()}"
        self.autopay_setup_checkouts.append(
            {
                "checkout_id": checkout_id,
                "parent_id": parent_id,
                "enrollment_id": enrollment_id,
                "session_id": session_id,
                "success_url": success_url,
                "cancel_url": cancel_url,
                "metadata": metadata,
            }
        )
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

    async def search_app_owned_payment_intents(
        self, *, academy_id: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        matched = [
            pi
            for pi in self.payment_intents
            if str((pi.get("metadata") or {}).get("academy_id") or "") == academy_id
            and str(pi.get("status") or "").lower() == "succeeded"
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
