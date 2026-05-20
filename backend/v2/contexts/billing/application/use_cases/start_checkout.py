"""Start a Stripe Checkout Session.

Creates a `Payment(status=pending)` in our DB and a corresponding Stripe
Checkout Session. Returns the redirect URL the client navigates to.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel
from ulid import ULID

from backend.v2.contexts.billing.application.ports import (
    PaymentRepository,
    StripeGateway,
)
from backend.v2.contexts.billing.domain.errors import CheckoutCreationFailed
from backend.v2.contexts.billing.domain.models import Payment


class StartCheckoutCommand(BaseModel):
    model_config = {"frozen": True}

    parent_id: str
    session_id: str
    amount_cents: int
    calculation_snapshot_id: str | None = None
    success_url: str
    cancel_url: str


class StartCheckoutResult(BaseModel):
    model_config = {"frozen": True}

    payment_id: str
    checkout_session_id: str
    redirect_url: str


class StartCheckout:
    def __init__(
        self,
        *,
        payment_repo: PaymentRepository,
        stripe: StripeGateway,
        academy_id: str,
        clock=lambda: datetime.now(timezone.utc),
    ) -> None:
        self._payments = payment_repo
        self._stripe = stripe
        self._academy_id = academy_id
        self._now = clock

    async def execute(self, cmd: StartCheckoutCommand) -> StartCheckoutResult:
        payment_id = str(ULID())
        try:
            checkout_id, url = await self._stripe.create_checkout_session(
                parent_id=cmd.parent_id,
                session_id=cmd.session_id,
                amount_cents=cmd.amount_cents,
                success_url=cmd.success_url,
                cancel_url=cmd.cancel_url,
                metadata={
                    "academy_id": self._academy_id,
                    "payment_id": payment_id,
                    "parent_id": cmd.parent_id,
                    "session_id": cmd.session_id,
                    "calculation_snapshot_id": cmd.calculation_snapshot_id or "",
                },
            )
        except Exception as exc:  # pragma: no cover - infra-only path
            raise CheckoutCreationFailed(str(exc)) from exc

        now = self._now()
        payment = Payment(
            payment_id=payment_id,
            academy_id=self._academy_id,
            parent_id=cmd.parent_id,
            session_id=cmd.session_id,
            stripe_checkout_session_id=checkout_id,
            calculation_snapshot_id=cmd.calculation_snapshot_id,
            amount_cents=cmd.amount_cents,
            status="pending",
            created_at=now,
            updated_at=now,
        )
        await self._payments.save(payment)
        return StartCheckoutResult(
            payment_id=payment_id,
            checkout_session_id=checkout_id,
            redirect_url=url,
        )
