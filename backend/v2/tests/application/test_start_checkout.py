"""StartCheckout use-case tests."""

from __future__ import annotations

import pytest

from backend.v2.contexts.billing.application.use_cases.start_checkout import (
    StartCheckout,
    StartCheckoutCommand,
)
from backend.v2.contexts.billing.domain.models import Payment
from backend.v2.contexts.billing.infrastructure.fake_stripe_gateway import (
    FakeStripeGateway,
)


class FakePaymentRepo:
    def __init__(self) -> None:
        self.saved: list[Payment] = []

    async def save(self, p: Payment) -> None:
        self.saved.append(p)

    async def get(self, pid):
        for p in self.saved:
            if p.payment_id == pid:
                return p
        return None

    async def get_by_stripe_pi(self, _):
        return None

    async def get_by_checkout_session(self, _):
        return None

    async def list_for_parent(self, _):
        return []


@pytest.mark.asyncio
async def test_start_checkout_creates_payment_and_stripe_session() -> None:
    stripe = FakeStripeGateway()
    repo = FakePaymentRepo()
    uc = StartCheckout(payment_repo=repo, stripe=stripe, academy_id="acad")
    result = await uc.execute(
        StartCheckoutCommand(
            parent_id="p1",
            session_id="s1",
            amount_cents=15000,
            success_url="https://app/success",
            cancel_url="https://app/cancel",
        )
    )
    assert result.payment_id
    assert result.redirect_url.startswith("https://fake.stripe.com/")
    assert len(repo.saved) == 1
    assert repo.saved[0].status == "pending"
    assert repo.saved[0].amount_cents == 15000
    assert len(stripe.checkouts) == 1
    assert stripe.checkouts[0]["metadata"]["payment_id"] == result.payment_id
