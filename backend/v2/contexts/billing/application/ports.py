"""Billing application ports."""

from __future__ import annotations

from typing import Protocol

from backend.v2.contexts.billing.domain.models import Payment, Subscription


class PaymentRepository(Protocol):
    async def save(self, payment: Payment) -> None: ...
    async def get(self, payment_id: str) -> Payment | None: ...
    async def get_by_stripe_pi(self, stripe_pi: str) -> Payment | None: ...
    async def get_by_checkout_session(self, checkout_session_id: str) -> Payment | None: ...
    async def list_for_parent(self, parent_id: str) -> list[Payment]: ...
    async def list_all(self) -> list[Payment]: ...


class SubscriptionRepository(Protocol):
    async def save(self, subscription: Subscription) -> None: ...
    async def get_by_stripe_sub(self, stripe_sub: str) -> Subscription | None: ...


class StripeEventDedup(Protocol):
    """Mongo-backed per-Stripe-event idempotency check.

    Mirrors legacy `stripe_webhook_events`. Insert-first lock pattern.
    """

    async def claim(self, event_id: str, event_type: str) -> bool: ...
    async def mark_processed(self, event_id: str) -> None: ...
    async def mark_failed(self, event_id: str, error: str) -> None: ...


class StripeGateway(Protocol):
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
        """Returns (checkout_session_id, redirect_url)."""

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
        """Returns (checkout_session_id, redirect_url, stripe_subscription_id)."""

    async def create_customer_portal_session(
        self,
        *,
        parent_id: str,
        return_url: str,
        stripe_customer_id: str | None,
    ) -> str:
        """Returns portal redirect URL."""

    def verify_webhook(self, payload: bytes, signature: str) -> dict[str, object]: ...

    async def issue_refund(self, payment_intent_id: str, amount_cents: int | None) -> str:
        """Returns Stripe refund id."""


class CapacityReservation(Protocol):
    """Cross-context port: Billing uses this to ask Enrollment whether a
    capacity-reserved seat is available for a session.
    """

    async def try_reserve(self, session_id: str) -> bool: ...
    async def release(self, session_id: str) -> None: ...
