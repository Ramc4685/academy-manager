"""Billing application ports."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from backend.v2.contexts.billing.domain.models import CreditLedgerEntry, Payment, Subscription
from backend.v2.contexts.billing.domain.proration import (
    BillingCalculationSnapshot,
    BillingPeriod,
    ClassOccurrence,
)


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
    async def latest_for_enrollment(self, enrollment_id: str) -> Subscription | None: ...


class CreditLedgerRepository(Protocol):
    async def create(self, entry: CreditLedgerEntry) -> None: ...
    async def list_for_parent(self, parent_id: str) -> list[CreditLedgerEntry]: ...
    async def balance_for_parent(self, parent_id: str) -> int: ...
    async def apply_available_credits(
        self, *, parent_id: str, invoice_id: str, amount_due_cents: int
    ) -> int: ...
    async def find_active_for_enrollment(
        self, *, enrollment_id: str, type: str
    ) -> CreditLedgerEntry | None: ...


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

    async def cancel_subscription(
        self, stripe_subscription_id: str, *, at_period_end: bool
    ) -> None:
        """Cancel a Stripe subscription now or at period end."""


class CapacityReservation(Protocol):
    """Cross-context port: Billing uses this to ask Enrollment whether a
    capacity-reserved seat is available for a session.
    """

    async def try_reserve(self, session_id: str) -> bool: ...
    async def release(self, session_id: str) -> None: ...


# ---------------------------------------------------------------------------
# Ports for QuoteEnrollment use case
# ---------------------------------------------------------------------------


class SessionLoader(Protocol):
    """Fetch a raw session document by its ID."""

    async def get_by_id(self, session_id: str) -> dict | None: ...


class OccurrenceCatalog(Protocol):
    """Enumerate class occurrences for a session within a billing period."""

    async def list_for_session(
        self, session_doc: dict, period: BillingPeriod
    ) -> list[ClassOccurrence]: ...


class SnapshotWriter(Protocol):
    """Persist billing calculation snapshots (storage only, no policy)."""

    async def persist_open(
        self,
        *,
        snapshot: BillingCalculationSnapshot,
        session_id: str,
        parent_id: str | None,
        student_id: str | None,
        enrollment_id: str | None,
        ttl_minutes: int,
        now: datetime,
    ) -> BillingCalculationSnapshot:
        """Store snapshot as OPEN and return the stored copy with snapshot_id / expires_at."""
        ...

    async def consume(self, snapshot_id: str) -> BillingCalculationSnapshot | None:
        """Atomically transition OPEN → CONSUMED and return the updated snapshot."""
        ...

    async def persist_consumed_first_month(
        self,
        *,
        snapshot: BillingCalculationSnapshot,
        enrollment_id: str,
        session_id: str,
        student_id: str,
        now: datetime,
    ) -> str:
        """Store a CONSUMED first-month proration snapshot; return snapshot_id."""
        ...

    async def persist_monthly_tuition(
        self,
        *,
        snapshot: BillingCalculationSnapshot,
        enrollment_id: str,
        session_id: str,
        student_id: str,
    ) -> str:
        """Store a CONSUMED monthly-tuition snapshot; return snapshot_id."""
        ...
