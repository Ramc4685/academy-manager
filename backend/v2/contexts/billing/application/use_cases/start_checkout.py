"""Start a Stripe Checkout Session.

Creates a `Payment(status=pending)` in our DB and a corresponding Stripe
Checkout Session. Returns the redirect URL the client navigates to.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel

from backend.v2.contexts.billing.application.ports import (
    ConnectedAccountRepository,
    PaymentRepository,
    StripeGateway,
)
from backend.v2.contexts.billing.domain.errors import CheckoutCreationFailed
from backend.v2.contexts.billing.domain.models import Payment
from backend.v2.shared.ids import new_ulid


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
        connected_accounts: ConnectedAccountRepository | None = None,
        clock=lambda: datetime.now(UTC),
    ) -> None:
        self._payments = payment_repo
        self._stripe = stripe
        self._academy_id = academy_id
        self._connected_accounts = connected_accounts
        self._now = clock

    async def execute(self, cmd: StartCheckoutCommand) -> StartCheckoutResult:
        connected_account_id = await self._ready_connected_account_id()
        payment_id = str(new_ulid())
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
                connected_account_id=connected_account_id,
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

    async def _ready_connected_account_id(self) -> str | None:
        # Destination-charge routing (Slice I posture): when the connected-accounts
        # repo is wired, funds must settle to the academy's connected account —
        # refuse a platform charge if it is not charge-ready.
        if self._connected_accounts is None:
            return None
        account = await self._connected_accounts.get_for_academy()
        if account is None or not account.is_ready_for_charges():
            raise CheckoutCreationFailed("Stripe connected account is not ready for checkout.")
        return account.stripe_account_id
