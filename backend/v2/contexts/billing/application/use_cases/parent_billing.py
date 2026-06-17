"""Parent billing use cases for autopay and checkout status."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field

from backend.v2.contexts.billing.application.ports import (
    EnrollmentAutopayStateRepository,
    ParentStripeCustomerRepository,
    PaymentRepository,
    StripeGateway,
    SubscriptionRepository,
)
from backend.v2.contexts.billing.domain.errors import CheckoutCreationFailed, PaymentNotFound
from backend.v2.contexts.billing.domain.models import Subscription
from backend.v2.shared.ids import new_ulid


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
        clock=lambda: datetime.now(UTC),
    ) -> None:
        self._subscriptions = subscriptions
        self._stripe = stripe
        self._academy_id = academy_id
        self._now = clock

    async def execute(
        self, cmd: StartSubscriptionCheckoutCommand
    ) -> StartSubscriptionCheckoutResult:
        existing = await self._subscriptions.latest_for_enrollment(cmd.enrollment_id)
        if (
            existing is not None
            and existing.parent_id == cmd.parent_id
            and existing.status == "incomplete"
            and existing.stripe_checkout_session_id
        ):
            checkout = await self._stripe.retrieve_checkout_session(
                existing.stripe_checkout_session_id
            )
            checkout_status = str(checkout.get("status") or "")
            checkout_url = str(checkout.get("url") or "")
            if checkout_status == "open" and checkout_url:
                return StartSubscriptionCheckoutResult(
                    subscription_id=existing.subscription_id,
                    checkout_session_id=existing.stripe_checkout_session_id,
                    redirect_url=checkout_url,
                )
            if checkout_status == "complete":
                return StartSubscriptionCheckoutResult(
                    subscription_id=existing.subscription_id,
                    checkout_session_id=existing.stripe_checkout_session_id,
                    redirect_url=_success_url_with_checkout_session(
                        cmd.success_url,
                        existing.stripe_checkout_session_id,
                    ),
                )

        subscription_id = str(new_ulid())
        success_url = _success_url_with_checkout_session_placeholder(cmd.success_url)
        try:
            (
                checkout_id,
                url,
                stripe_subscription_id,
            ) = await self._stripe.create_subscription_checkout_session(
                parent_id=cmd.parent_id,
                enrollment_id=cmd.enrollment_id,
                session_id=cmd.session_id,
                amount_cents=cmd.amount_cents,
                success_url=success_url,
                cancel_url=cmd.cancel_url,
                metadata={
                    "academy_id": self._academy_id,
                    "app_subscription_id": subscription_id,
                    # Legacy key retained so older deployed code and any
                    # already-created Checkout Sessions keep reconciling.
                    "subscription_id": subscription_id,
                    "parent_id": cmd.parent_id,
                    "enrollment_id": cmd.enrollment_id,
                    "session_id": cmd.session_id,
                },
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
                stripe_checkout_session_id=checkout_id,
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
    def __init__(
        self,
        *,
        payments: PaymentRepository,
        subscriptions: SubscriptionRepository | None = None,
        stripe: StripeGateway | None = None,
        parent_customers: ParentStripeCustomerRepository | None = None,
        enrollment_autopay: EnrollmentAutopayStateRepository | None = None,
        clock=lambda: datetime.now(UTC),
    ) -> None:
        self._payments = payments
        self._subscriptions = subscriptions
        self._stripe = stripe
        self._parent_customers = parent_customers
        self._enrollment_autopay = enrollment_autopay
        self._now = clock

    async def execute(self, checkout_session_id: str, *, parent_id: str) -> CheckoutStatusResult:
        payment = await self._payments.get_by_checkout_session(checkout_session_id)
        if payment is not None:
            if payment.parent_id != parent_id:
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
        if self._subscriptions is None:
            raise PaymentNotFound(
                "checkout session not found",
                checkout_session_id=checkout_session_id,
            )
        subscription = await self._subscriptions.get_by_checkout_session(checkout_session_id)
        if subscription is None or subscription.parent_id != parent_id:
            raise PaymentNotFound(
                "checkout session not found",
                checkout_session_id=checkout_session_id,
            )
        if self._stripe is not None and subscription.status == "incomplete":
            checkout = await self._stripe.retrieve_checkout_session(checkout_session_id)
            subscription = await self._reconcile_subscription_checkout(subscription, checkout)
        return CheckoutStatusResult(
            checkout_session_id=checkout_session_id,
            payment_id=None,
            status=subscription.status,
            parent_id=subscription.parent_id,
        )

    async def _reconcile_subscription_checkout(
        self,
        subscription: Subscription,
        checkout: dict[str, object],
    ) -> Subscription:
        status = str(checkout.get("status") or "")
        stripe_subscription_id = str(checkout.get("subscription") or "")
        if status != "complete" or not stripe_subscription_id:
            return subscription
        updated = subscription.model_copy(
            update={
                "stripe_subscription_id": stripe_subscription_id,
                "status": "active",
                "updated_at": self._now(),
            }
        )
        await self._subscriptions.save(updated)  # type: ignore[union-attr]
        stripe_customer_id = str(checkout.get("customer") or "")
        if self._parent_customers is not None and stripe_customer_id:
            await self._parent_customers.set_stripe_customer_id(
                parent_id=updated.parent_id,
                stripe_customer_id=stripe_customer_id,
            )
        if self._enrollment_autopay is not None and updated.enrollment_id:
            await self._enrollment_autopay.set_autopay_state(
                enrollment_id=updated.enrollment_id,
                subscription_status="active",
                stripe_subscription_id=stripe_subscription_id,
            )
        return updated


def _success_url_with_checkout_session_placeholder(success_url: str) -> str:
    if "checkout_session_id=" in success_url:
        return success_url
    separator = "&" if "?" in success_url else "?"
    return f"{success_url}{separator}checkout_session_id={{CHECKOUT_SESSION_ID}}"


def _success_url_with_checkout_session(success_url: str, checkout_session_id: str) -> str:
    with_placeholder = _success_url_with_checkout_session_placeholder(success_url)
    return with_placeholder.replace("{CHECKOUT_SESSION_ID}", checkout_session_id)
