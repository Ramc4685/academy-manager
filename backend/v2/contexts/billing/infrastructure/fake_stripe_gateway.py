"""Fake StripeGateway for dev/test.

Records calls; returns deterministic IDs. Real Stripe stays out of CI.
"""

from __future__ import annotations

import json
from typing import Any
from ulid import ULID

from backend.v2.contexts.billing.application.ports import StripeGateway


class FakeStripeGateway(StripeGateway):
    def __init__(self) -> None:
        self.checkouts: list[dict[str, Any]] = []
        self.refunds: list[dict[str, Any]] = []

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
        checkout_id = f"cs_test_{ULID()}"
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

    def verify_webhook(self, payload: bytes, signature: str) -> dict[str, object]:
        # Tests pass already-parsed events as JSON body and a fixed sig.
        if signature != "test_signature":
            raise ValueError("invalid signature")
        return json.loads(payload.decode("utf-8"))

    async def issue_refund(self, payment_intent_id: str, amount_cents: int | None) -> str:
        refund_id = f"re_test_{ULID()}"
        self.refunds.append(
            {
                "refund_id": refund_id,
                "payment_intent_id": payment_intent_id,
                "amount_cents": amount_cents,
            }
        )
        return refund_id
