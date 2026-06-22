"""Billing application ports."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel

from backend.v2.contexts.billing.domain.ledger import (
    InvoiceLine,
    LedgerAllocationResult,
    LedgerInvoice,
    LedgerPayment,
    PaymentAllocation,
)
from backend.v2.contexts.billing.domain.models import CreditLedgerEntry, Payment, Subscription
from backend.v2.contexts.billing.domain.proration import (
    BillingCalculationSnapshot,
    BillingPeriod,
    ClassOccurrence,
)
from backend.v2.contexts.billing.domain.session_type import (
    SessionType,
    StudentBillingEnrollment,
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
    async def get(self, subscription_id: str) -> Subscription | None: ...
    async def get_by_stripe_sub(self, stripe_sub: str) -> Subscription | None: ...
    async def get_by_checkout_session(self, checkout_session_id: str) -> Subscription | None: ...
    async def latest_for_enrollment(self, enrollment_id: str) -> Subscription | None: ...


class ParentStripeCustomerRepository(Protocol):
    async def get_stripe_customer_id(self, *, parent_id: str) -> str | None: ...
    async def set_stripe_customer_id(self, *, parent_id: str, stripe_customer_id: str) -> None: ...


class EnrollmentAutopayStateRepository(Protocol):
    """Cross-context port: Billing pushes subscription lifecycle state onto
    the Enrollment aggregate so parent-facing autopay status stays accurate.
    """

    async def set_autopay_state(
        self,
        *,
        enrollment_id: str,
        subscription_status: str,
        stripe_subscription_id: str | None,
    ) -> None: ...


class EnrollmentBillingIdentity(BaseModel):
    model_config = {"frozen": True}

    academy_id: str
    parent_id: str
    student_id: str | None = None
    enrollment_id: str
    session_id: str | None = None


class EnrollmentBillingIdentityRepository(Protocol):
    """Cross-context read port for mapping subscription payments to enrollment owners."""

    async def get_billing_identity(
        self,
        enrollment_id: str,
    ) -> EnrollmentBillingIdentity | dict[str, str | None] | None: ...


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
    async def store_received(
        self,
        event: dict[str, Any],
        *,
        raw_payload: bytes,
        academy_id: str,
    ) -> bool: ...
    async def claim_next(
        self,
        *,
        academy_id: str,
        processor_id: str,
        lock_seconds: int = 300,
    ) -> dict[str, Any] | None: ...
    async def mark_processed(self, event_id: str) -> None: ...
    async def mark_failed(self, event_id: str, error: str) -> None: ...
    async def mark_quarantined(self, event_id: str, error: str) -> None: ...


class StripeInvoiceProcessingRepository(Protocol):
    async def record_recovery_point(
        self,
        *,
        academy_id: str,
        stripe_invoice_id: str,
        stripe_subscription_id: str | None,
        event_id: str,
        recovery_point: str,
        ledger_invoice_id: str | None = None,
        ledger_payment_id: str | None = None,
        legacy_payment_id: str | None = None,
        last_error: str | None = None,
        updated_at: datetime,
    ) -> None: ...


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

    async def create_autopay_setup_checkout_session(
        self,
        *,
        parent_id: str,
        enrollment_id: str,
        session_id: str,
        success_url: str,
        cancel_url: str,
        metadata: dict[str, str],
    ) -> tuple[str, str]:
        """Returns (checkout_session_id, redirect_url) for saved-card setup."""

    async def create_customer_portal_session(
        self,
        *,
        parent_id: str,
        return_url: str,
        stripe_customer_id: str | None,
    ) -> str:
        """Returns portal redirect URL."""

    def verify_webhook(self, payload: bytes, signature: str) -> dict[str, object]: ...

    async def retrieve_checkout_session(self, checkout_session_id: str) -> dict[str, Any]:
        """Fetch current Stripe Checkout Session state for reconciliation."""

    async def retrieve_invoice(self, stripe_invoice_id: str) -> dict[str, Any]:
        """Fetch current Stripe invoice state for reconciliation."""

    async def retrieve_subscription(self, stripe_subscription_id: str) -> dict[str, Any]:
        """Fetch current Stripe subscription state for reconciliation."""

    async def retrieve_payment_intent(self, stripe_payment_intent_id: str) -> dict[str, Any]:
        """Fetch current Stripe PaymentIntent state for reconciliation."""

    async def search_app_owned_payment_intents(
        self, *, academy_id: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Find recently paid PaymentIntents carrying app-owned invoice metadata."""

    async def issue_refund(self, payment_intent_id: str, amount_cents: int | None) -> str:
        """Returns Stripe refund id."""

    async def cancel_subscription(
        self, stripe_subscription_id: str, *, at_period_end: bool
    ) -> None:
        """Cancel a Stripe subscription now or at period end."""

    async def pause_subscription_collection(
        self,
        stripe_subscription_id: str,
        *,
        behavior: Literal["void", "keep_as_draft", "mark_uncollectible"] = "void",
    ) -> None:
        """Pause invoice collection for an active subscription."""

    async def resume_subscription_collection(self, stripe_subscription_id: str) -> None:
        """Resume invoice collection for a paused subscription."""

    async def update_subscription_proration(
        self,
        stripe_subscription_id: str,
        *,
        new_price_cents: int,
        billing_period_start: datetime,
        billing_period_end: datetime,
    ) -> str:
        """Legacy subscription price sync without letting Stripe create invoices."""

    def create_connect_link(self, *, redirect_uri: str, state: str) -> str:
        """Return Stripe OAuth authorize URL for Express onboarding."""
        ...

    async def exchange_connect_code(self, code: str) -> str:
        """Exchange OAuth authorization code for stripe_user_id (connected account ID)."""
        ...


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


# ---------------------------------------------------------------------------
# Ports for session-type-driven billing
# ---------------------------------------------------------------------------


class SessionTypeRepository(Protocol):
    async def save(self, session_type: SessionType) -> None: ...
    async def get(self, session_type_id: str) -> SessionType | None: ...
    async def list_active(self) -> list[SessionType]: ...
    async def soft_delete(self, session_type_id: str) -> None: ...


class StudentBillingEnrollmentRepository(Protocol):
    async def save(self, enrollment: StudentBillingEnrollment) -> None: ...
    async def get(self, enrollment_id: str) -> StudentBillingEnrollment | None: ...
    async def list_for_student(self, student_id: str) -> list[StudentBillingEnrollment]: ...
    async def list_for_parent(self, parent_id: str) -> list[StudentBillingEnrollment]: ...
    async def get_by_stripe_subscription(
        self, stripe_subscription_id: str
    ) -> StudentBillingEnrollment | None: ...


class LedgerRepository(Protocol):
    """Port for ledger invoice + line persistence (Phase 2A+)."""

    async def get_invoice(self, invoice_id: str) -> LedgerInvoice | None: ...
    async def get_invoice_by_stripe_invoice_id(
        self, stripe_invoice_id: str
    ) -> LedgerInvoice | None: ...
    async def get_open_invoice_for_student(
        self, student_id: str, period: str
    ) -> LedgerInvoice | None: ...
    async def get_open_invoice_for_enrollment(
        self, enrollment_id: str, period: str
    ) -> LedgerInvoice | None: ...
    async def get_invoice_for_enrollment_period(
        self,
        enrollment_id: str,
        period: str,
        *,
        statuses: set[str] | None = None,
    ) -> LedgerInvoice | None: ...
    async def get_payment_by_stripe_payment_intent_id(
        self, stripe_payment_intent_id: str
    ) -> LedgerPayment | None: ...
    async def get_payment_allocation_by_idempotency_key(
        self, idempotency_key: str
    ) -> PaymentAllocation | None: ...
    async def get_lines_for_invoice(self, invoice_id: str) -> list[InvoiceLine]: ...
    async def save_invoice(self, invoice: LedgerInvoice) -> LedgerInvoice: ...
    async def save_line(self, line: InvoiceLine) -> InvoiceLine: ...
    async def delete_invoice_line(self, *, invoice_id: str, line_id: str) -> bool: ...
    async def create_invoice(
        self,
        invoice: LedgerInvoice,
        *,
        lines: list[InvoiceLine],
        idempotency_key: str,
    ) -> LedgerInvoice: ...

    async def record_payment(
        self,
        payment: LedgerPayment,
        *,
        idempotency_key: str,
    ) -> LedgerPayment: ...

    async def record_payment_attempt(
        self,
        *,
        invoice_id: str,
        parent_id: str,
        amount_cents: int,
        currency: str,
        status: str,
        stripe_payment_intent_id: str | None,
        stripe_checkout_session_id: str | None,
        failure_code: str | None,
        failure_message: str | None,
        idempotency_key: str,
        created_by_event_id: str | None = None,
    ) -> dict[str, Any]: ...

    async def allocate_payment(
        self,
        *,
        payment_id: str,
        invoice_id: str,
        amount_cents: int,
        idempotency_key: str,
    ) -> LedgerAllocationResult: ...
