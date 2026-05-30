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
        self.portal_sessions: list[dict[str, Any]] = []
        self.refunds: list[dict[str, Any]] = []
        self.cancelled_subscriptions: list[dict[str, Any]] = []
        self.subscription_prorations: list[dict[str, Any]] = []

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
        return f"in_proration_{new_ulid()}"
