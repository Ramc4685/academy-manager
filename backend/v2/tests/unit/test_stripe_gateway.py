from __future__ import annotations

import pytest

from backend.v2.contexts.billing.infrastructure.fake_stripe_gateway import FakeStripeGateway


@pytest.mark.asyncio
async def test_fake_gateway_records_subscription_collection_pause() -> None:
    stripe = FakeStripeGateway()

    await stripe.pause_subscription_collection("sub_123", behavior="void")

    assert stripe.paused_subscriptions == [
        {"stripe_subscription_id": "sub_123", "behavior": "void"}
    ]


@pytest.mark.asyncio
async def test_fake_gateway_records_subscription_collection_resume() -> None:
    stripe = FakeStripeGateway()

    await stripe.resume_subscription_collection("sub_123")

    assert stripe.resumed_subscriptions == [{"stripe_subscription_id": "sub_123"}]
