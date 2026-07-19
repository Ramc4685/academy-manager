"""Billing application ports."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any, Literal, Protocol, TypeVar

from pydantic import BaseModel

from backend.v2.contexts.billing.domain.autopay_status import AutopayEnrollmentStatus
from backend.v2.contexts.billing.domain.billing_settings import BillingSettings
from backend.v2.contexts.billing.domain.connected_account import (
    ConnectedAccount,
    ConnectedAccountStatus,
)
from backend.v2.contexts.billing.domain.ledger import (
    InvoiceLine,
    LedgerAllocationResult,
    LedgerInvoice,
    LedgerPayment,
    PaymentAllocation,
)
from backend.v2.contexts.billing.domain.models import (
    AutopayConsent,
    CreditLedgerEntry,
    Payment,
    Subscription,
)
from backend.v2.contexts.billing.domain.proration import (
    BillingCalculationSnapshot,
    BillingPeriod,
    ClassOccurrence,
)
from backend.v2.contexts.billing.domain.session_type import (
    SessionType,
    StudentBillingEnrollment,
)

T = TypeVar("T")


class BillingSetupStudent(BaseModel):
    model_config = {"frozen": True}

    student_id: str
    full_name: str


class ParentBillingCustomerSnapshot(BaseModel):
    """Stripe setup fields needed by the Billing Setup read model."""

    model_config = {"frozen": True}

    parent_id: str
    stripe_customer_id: str | None = None
    card_label: str | None = None
    card_last4: str | None = None
    last_invited_at: datetime | None = None


class EnrollmentAutopaySnapshot(BaseModel):
    model_config = {"frozen": True}

    enrollment_id: str
    parent_id: str
    autopay_enrollment_status: AutopayEnrollmentStatus


class ParentRosterEntry(BaseModel):
    model_config = {"frozen": True}

    parent_id: str
    parent_name: str
    parent_email: str | None = None


class ParentBalanceSnapshot(BaseModel):
    """Aggregate balance plus the exact next invoice offered for charging."""

    model_config = {"frozen": True}

    outstanding_cents: int = 0
    charge_invoice_id: str | None = None
    charge_amount_cents: int = 0


class LoginAccountDirectory(Protocol):
    async def login_account_parent_ids(
        self, parent_ids: list[str], *, academy_id: str
    ) -> set[str]: ...


class ParentStudentRoster(Protocol):
    async def list_parents(self, *, academy_id: str) -> list[ParentRosterEntry]: ...

    async def students_for_parents(
        self, parent_ids: list[str], *, academy_id: str
    ) -> dict[str, list[BillingSetupStudent]]: ...


class BillingCustomerDirectory(Protocol):
    async def list_customers(self, *, academy_id: str) -> list[ParentBillingCustomerSnapshot]: ...


class EnrollmentAutopayDirectory(Protocol):
    async def list_autopay_states(self, *, academy_id: str) -> list[EnrollmentAutopaySnapshot]: ...


class OutstandingBalanceDirectory(Protocol):
    async def billing_setup_by_parent(
        self, *, academy_id: str
    ) -> dict[str, ParentBalanceSnapshot]: ...


class InviteEmailOutcome(BaseModel):
    model_config = {"frozen": True}

    ok: bool
    failed_reason: str | None = None


class InviteEmailPort(Protocol):
    async def send_invite_email(
        self,
        *,
        user_id: str,
        email: str,
        display_name: str,
        subject: str,
        body: str,
    ) -> InviteEmailOutcome: ...


class ParentContact(BaseModel):
    model_config = {"frozen": True}

    parent_id: str
    email: str
    display_name: str


class ParentContactLookup(Protocol):
    async def get_parent_contact(
        self, parent_id: str, *, academy_id: str
    ) -> ParentContact | None: ...


class CardSetupLinkPort(Protocol):
    async def create_card_setup_link(
        self, *, parent_id: str, academy_id: str, return_url: str
    ) -> str: ...


class AcademyNameLookup(Protocol):
    async def get_academy_name(self, academy_id: str) -> str | None: ...


class TransactionRunner(Protocol):
    async def run(self, work: Callable[[Any | None], Awaitable[T]]) -> T: ...


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
    async def set_default_payment_method(
        self,
        *,
        parent_id: str,
        stripe_customer_id: str,
        stripe_payment_method_id: str,
        payment_method_type: str,
        stripe_mandate_id: str | None,
        setup_intent_id: str,
        checkout_session_id: str | None,
        completed_at: datetime,
        current_consent_id: str | None = None,
        consent_text_version: str | None = None,
        ach_mandate_version: str | None = None,
        card_disclosure_version: str | None = None,
        setup_status: str = "active",
        payment_method_role: str = "primary",
        payment_method_label: str | None = None,
        payment_method_last4: str | None = None,
        session: Any | None = None,
    ) -> None: ...
    async def promote_payment_method_to_default(
        self,
        *,
        parent_id: str,
        stripe_payment_method_id: str,
        payment_method_type: str,
        stripe_mandate_id: str | None,
        payment_method_label: str | None = None,
        payment_method_last4: str | None = None,
    ) -> None: ...


class AutopayConsentRepository(Protocol):
    async def append(
        self, consent: AutopayConsent, *, session: Any | None = None
    ) -> AutopayConsent: ...
    async def list_for_parent(self, *, parent_id: str) -> list[AutopayConsent]: ...


class EnrollmentAutopayStateRepository(Protocol):
    """Port for the single per-enrollment autopay-status store
    (``student_billing_enrollments``).

    ``autopay_enrollment_status`` carries the enrollment-lifecycle axis (see
    `contexts.billing.domain.autopay_status`) — independent of any single
    charge attempt's outcome. This routes through the SAME guarded transition
    path that pause/resume use, so the webhook/legacy-convergence path cannot
    silently diverge (BLOCKING #1 collapse). Returns True if the transition was
    applied, False if it was a rejected (illegal / not-found) transition — a
    no-op that is logged, never raised, so idempotent replay stays safe.
    """

    async def set_autopay_state(
        self,
        *,
        enrollment_id: str,
        autopay_enrollment_status: str,
        session: Any | None = None,
    ) -> bool: ...

    async def mark_autopay_active_from_setup(
        self, *, enrollment_id: str, session: Any | None = None
    ) -> bool:
        """Setup completed successfully — walk the enrollment to ``active``
        through the guarded transition path (handles first setup and re-setup
        from ``disabled``). Returns True if it ends up ``active``."""
        ...


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


class StripeResourceNotFound(Exception):
    """Raised by the gateway when Stripe reports a resource does not exist
    (e.g. an unknown payment_intent or invoice id). Distinct from transport /
    auth failures so callers can map it to a 404 rather than a 500."""


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
        connected_account_id: str | None = None,
    ) -> tuple[str, str]:
        """Returns (checkout_session_id, redirect_url).

        When ``connected_account_id`` is set, the checkout's PaymentIntent is a
        destination charge to the academy's connected account.
        """

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
        connected_account_id: str | None = None,
    ) -> tuple[str, str]:
        """Returns (checkout_session_id, redirect_url) for saved-card setup.

        When ``connected_account_id`` is set, the eventual off-session charges
        route to that connected academy account (``setup_intent_data.on_behalf_of``).
        """

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

    async def retrieve_setup_intent(self, stripe_setup_intent_id: str) -> dict[str, Any]:
        """Fetch current Stripe SetupIntent state for saved-payment-method setup."""

    async def retrieve_payment_method(self, stripe_payment_method_id: str) -> dict[str, Any]:
        """Fetch current Stripe PaymentMethod state for saved-payment-method setup."""

    async def set_customer_default_payment_method(
        self,
        *,
        stripe_customer_id: str,
        stripe_payment_method_id: str,
        metadata: dict[str, str],
    ) -> None:
        """Set the Customer default PM used by off-session autopay charges."""

    async def search_app_owned_payment_intents(
        self, *, academy_id: str, limit: int = 100, stripe_account: str | None = None
    ) -> list[dict[str, Any]]:
        """Find recent app-owned PaymentIntents (succeeded or ACH `processing`).

        When ``stripe_account`` is set (Slice I), the search is scoped to that
        connected account rather than the platform account — money routed
        through a connected account is otherwise invisible to this search.
        """

    async def list_charges_for_customer(
        self, *, stripe_customer_id: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        """List a customer's recent succeeded charges (legacy invoice match candidates).

        Legacy/migrated payments carry no app metadata, so they cannot be matched
        by metadata. This surfaces a customer's historical charges so an admin can
        review and confirm a charge ↔ invoice match by hand (issue #242 WI-3).
        """

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

    async def create_connected_account(
        self,
        *,
        academy_id: str,
        display_name: str | None = None,
        contact_email: str | None = None,
        idempotency_key: str | None = None,
    ) -> str:
        """Create an Accounts v2 connected account and return its id.

        Slice I: NEVER the legacy ``type: express/custom/standard`` or v1
        ``controller`` shape. The platform accepts payment liability through
        ``defaults.responsibilities``.
        """
        ...

    async def create_account_onboarding_link(
        self,
        *,
        stripe_account_id: str,
        refresh_url: str,
        return_url: str,
    ) -> str:
        """Create a hosted onboarding AccountLink for a connected account."""
        ...

    async def create_off_session_payment_intent(
        self,
        *,
        amount_cents: int,
        currency: str,
        customer_id: str,
        payment_method_id: str,
        idempotency_key: str,
        metadata: dict[str, str],
        connected_account_id: str | None = None,
    ) -> tuple[str, str, str | None]:
        """Confirm an off-session autopay charge; returns (pi_id, status, decline_code).

        When ``connected_account_id`` is set, this is a destination charge to the
        connected academy account (``on_behalf_of`` + ``transfer_data.destination``,
        ``application_fee_amount=0`` for now). Customers live on the platform.
        """
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


class BillingCounterRepository(Protocol):
    """Port for atomic per-academy counters (Slice S0/D — e.g. invoice numbering)."""

    async def next_value(self, *, scope: str) -> int: ...


class BillingSettingsRepository(Protocol):
    """Port for academy-scoped billing configuration (Slice S0/D)."""

    async def get(self) -> BillingSettings: ...
    async def upsert(self, settings: BillingSettings) -> None: ...


class ConnectedAccountRepository(Protocol):
    """Port for the per-academy Stripe Connect account store (Slice I).

    Tenant-scoped: every method resolves through the request's academy_id, so
    an academy can only read/write its own connected account, and can only
    resolve its own ``stripe_account_id`` (used by the Connect webhook guard).
    """

    async def get_for_academy(self) -> ConnectedAccount | None: ...
    async def get_by_stripe_account_id(self, stripe_account_id: str) -> ConnectedAccount | None: ...
    async def upsert(self, account: ConnectedAccount) -> None: ...
    async def update_status(
        self,
        *,
        stripe_account_id: str,
        status: ConnectedAccountStatus,
        capabilities: dict[str, str] | None = None,
        charges_enabled: bool | None = None,
        payouts_enabled: bool | None = None,
    ) -> None: ...


class LedgerRepository(Protocol):
    """Port for ledger invoice + line persistence (Phase 2A+)."""

    async def get_invoice(self, invoice_id: str) -> LedgerInvoice | None: ...
    async def get_invoice_by_stripe_invoice_id(
        self, stripe_invoice_id: str
    ) -> LedgerInvoice | None: ...
    async def list_invoices_for_student(
        self, student_id: str, *, limit: int = 100
    ) -> list[LedgerInvoice]: ...
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

    async def mark_payment_refunded(
        self,
        payment_id: str,
        *,
        refunded_cents: int,
        status: str,
        updated_at: datetime,
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

    async def reverse_payment_allocation(
        self,
        *,
        allocation_idempotency_key: str,
        reversal_idempotency_key: str,
        reason: str,
        return_code: str | None,
        reversed_at: datetime,
    ) -> dict[str, Any] | None: ...

    async def list_allocations_for_payment(self, payment_id: str) -> list[PaymentAllocation]: ...

    async def sum_allocations_for_invoice(self, invoice_id: str) -> int: ...

    async def apply_invoice_refund(
        self, *, invoice_id: str, amount_cents: int
    ) -> LedgerInvoice: ...
