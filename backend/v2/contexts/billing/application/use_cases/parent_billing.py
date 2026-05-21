"""Parent billing use cases for autopay and checkout status."""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field
from backend.v2.shared.ids import new_ulid

from backend.v2.contexts.billing.application.ports import (
    PaymentRepository,
    StripeGateway,
    SubscriptionRepository,
)
from backend.v2.contexts.billing.domain.errors import CheckoutCreationFailed, PaymentNotFound
from backend.v2.contexts.billing.domain.models import Subscription


class StartSubscriptionCheckoutCommand(BaseModel):
    model_config = {"frozen": True}

    parent_id: str
    enrollment_id: str
    session_id: str
    amount_cents: int = Field(gt=0)
    success_url: str
    cancel_url: str


class StartSubscriptionCheckoutResult(BaseModel):
    model_config = {"frozen": True}

    subscription_id: str
    checkout_session_id: str
    redirect_url: str


class CheckoutStatusResult(BaseModel):
    model_config = {"frozen": True}

    checkout_session_id: str
    payment_id: str | None = None
    status: str
    parent_id: str


class StartSubscriptionCheckout:
    def __init__(
        self,
        *,
        subscriptions: SubscriptionRepository,
        stripe: StripeGateway,
        academy_id: str,
        clock=lambda: datetime.now(timezone.utc),
    ) -> None:
        self._subscriptions = subscriptions
        self._stripe = stripe
        self._academy_id = academy_id
        self._now = clock

    async def execute(
        self, cmd: StartSubscriptionCheckoutCommand
    ) -> StartSubscriptionCheckoutResult:
        subscription_id = str(new_ulid())
        try:
            checkout_id, url, stripe_subscription_id = (
                await self._stripe.create_subscription_checkout_session(
                    parent_id=cmd.parent_id,
                    enrollment_id=cmd.enrollment_id,
                    session_id=cmd.session_id,
                    amount_cents=cmd.amount_cents,
                    success_url=cmd.success_url,
                    cancel_url=cmd.cancel_url,
                    metadata={
                        "academy_id": self._academy_id,
                        "subscription_id": subscription_id,
                        "parent_id": cmd.parent_id,
                        "enrollment_id": cmd.enrollment_id,
                        "session_id": cmd.session_id,
                    },
                )
            )
        except Exception as exc:  # pragma: no cover - infra path
            raise CheckoutCreationFailed(str(exc)) from exc

        now = self._now()
        await self._subscriptions.save(
            Subscription(
                subscription_id=subscription_id,
                academy_id=self._academy_id,
                parent_id=cmd.parent_id,
                enrollment_id=cmd.enrollment_id,
                session_id=cmd.session_id,
                stripe_subscription_id=stripe_subscription_id,
                status="incomplete",
                payment_mode="monthly",
                created_at=now,
                updated_at=now,
            )
        )
        return StartSubscriptionCheckoutResult(
            subscription_id=subscription_id,
            checkout_session_id=checkout_id,
            redirect_url=url,
        )


class CreateCustomerPortalSessionCommand(BaseModel):
    model_config = {"frozen": True}

    parent_id: str
    return_url: str
    stripe_customer_id: str | None = None


class CreateCustomerPortalSessionResult(BaseModel):
    model_config = {"frozen": True}

    redirect_url: str


class CreateCustomerPortalSession:
    def __init__(self, *, stripe: StripeGateway) -> None:
        self._stripe = stripe

    async def execute(
        self, cmd: CreateCustomerPortalSessionCommand
    ) -> CreateCustomerPortalSessionResult:
        try:
            url = await self._stripe.create_customer_portal_session(
                parent_id=cmd.parent_id,
                return_url=cmd.return_url,
                stripe_customer_id=cmd.stripe_customer_id,
            )
        except Exception as exc:  # pragma: no cover - infra path
            raise CheckoutCreationFailed(str(exc)) from exc
        return CreateCustomerPortalSessionResult(redirect_url=url)


class GetCheckoutStatus:
    def __init__(self, *, payments: PaymentRepository) -> None:
        self._payments = payments

    async def execute(self, checkout_session_id: str, *, parent_id: str) -> CheckoutStatusResult:
        payment = await self._payments.get_by_checkout_session(checkout_session_id)
        if payment is None or payment.parent_id != parent_id:
            raise PaymentNotFound(
                "checkout session not found",
                checkout_session_id=checkout_session_id,
            )
        return CheckoutStatusResult(
            checkout_session_id=checkout_session_id,
            payment_id=payment.payment_id,
            status=payment.status,
            parent_id=payment.parent_id,
        )
