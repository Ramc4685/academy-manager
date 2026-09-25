"""Billing application ports."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import date, datetime
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
    AppliedCreditState,
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
    #: Other stored references to the same parent (``firebase_uid``,
    #: ``auth_uid``, users ``_id``) grouped into this row, so a family whose
    #: students store different ids is one row, not two. Cards, balances and
    #: autopay filed under any of them belong to this row.
    aliases: tuple[str, ...] = ()


class ParentBalanceSnapshot(BaseModel):
    """Aggregate balance plus the exact next invoice offered for charging."""

    model_config = {"frozen": True}

    outstanding_cents: int = 0
    charge_invoice_id: str | None = None
    charge_enrollment_id: str | None = None
    charge_amount_cents: int = 0


class LoginAccountDirectory(Protocol):
    async def login_account_parent_ids(
        self, parent_ids: list[str], *, academy_id: str
    ) -> set[str]: ...

    async def has_login_account(self, parent_id: str, *, academy_id: str) -> bool: ...


class ParentStudentRoster(Protocol):
    async def list_parents(self, *, academy_id: str) -> list[ParentRosterEntry]: ...

    async def students_for_parents(
        self, parent_ids: list[str], *, academy_id: str
    ) -> dict[str, list[BillingSetupStudent]]: ...

    async def get_parent(self, parent_id: str, *, academy_id: str) -> ParentRosterEntry | None: ...

    async def students_for_parent(
        self, parent_id: str, *, academy_id: str
    ) -> list[BillingSetupStudent]: ...


class BillingCustomerDirectory(Protocol):
    async def list_customers(self, *, academy_id: str) -> list[ParentBillingCustomerSnapshot]: ...

    async def get_customer(
        self, parent_id: str, *, academy_id: str
    ) -> ParentBillingCustomerSnapshot | None: ...


class EnrollmentAutopayDirectory(Protocol):
    async def list_autopay_states(self, *, academy_id: str) -> list[EnrollmentAutopaySnapshot]: ...

    async def list_parent_autopay_states(
        self, parent_id: str, *, academy_id: str
    ) -> list[EnrollmentAutopaySnapshot]: ...


class OutstandingBalanceDirectory(Protocol):
    async def billing_setup_by_parent(
        self, *, academy_id: str
    ) -> dict[str, ParentBalanceSnapshot]: ...

    async def billing_setup_for_parent(
        self, parent_id: str, *, academy_id: str
    ) -> ParentBalanceSnapshot | None: ...


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
    """The parent's Stripe customer and saved payment methods.

    ``stripe_account_id`` names the Stripe account those ids live on: None
    (the default, and every house-academy call) is the PLATFORM; otherwise the
    academy's connected account. Implementations must never let a customer or
    payment method stored for one account be read back or promoted for another.
    """

    async def get_stripe_customer_id(self, *, parent_id: str) -> str | None: ...
    async def set_stripe_customer_id(
        self,
        *,
        parent_id: str,
        stripe_customer_id: str,
        stripe_account_id: str | None = None,
    ) -> None: ...
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
        stripe_account_id: str | None = None,
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
        stripe_account_id: str | None = None,
    ) -> None: ...


class SavedPaymentMethodReader(Protocol):
    """Reads the parent's stored chargeable card on one Stripe account.

    Direct-charge autopay charges exactly the customer and payment method the
    app stored for the academy's connected account — never a platform-wide
    Customer search, which cannot see connected-account customers and could
    surface a card from another account.
    """

    async def get_saved_payment_method(
        self, *, parent_id: str, stripe_account_id: str | None
    ) -> tuple[str, str] | None:
        """(stripe_customer_id, payment_method_id) on ``stripe_account_id``, or None."""
        ...


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
    async def applied_credit_state(self, invoice_id: str) -> AppliedCreditState: ...
    async def repair_credit_projections(self, invoice_id: str) -> int: ...
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
    # Returns the resulting status, "failed" or "quarantined": retries are
    # bounded, so recording a failure may be the moment the event gives up and
    # the caller needs to alert (issue #437).
    async def mark_failed(self, event_id: str, error: str) -> str: ...
    async def mark_quarantined(
        self, event_id: str, error: str, *, reason_code: str = ...
    ) -> None: ...


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


class StripeCheckoutSessionNotExpirable(ValueError):
    """Stripe refused the expiry because the session is already in a terminal
    state — complete, or already expired.

    This is the ONLY benign expiry failure, and it is the race a supersede
    exists to survive: the parent paid on the old tab. Callers may swallow it.

    Subclasses ``ValueError`` so callers written against the gateway's older
    blanket ``ValueError`` contract keep working.
    """


class StripeTransientFailure(ValueError):
    """Stripe could not be reached, or failed in a way that may succeed on a
    retry — connection errors, timeouts, rate limits, 5xx.

    Indistinguishable from the terminal case before #549, which meant a network
    blip while retiring a superseded Checkout Session left that session PAYABLE
    with an INFO log and no reconciliation handle. Callers must never treat this
    as "already paid, nothing to do".
    """


class StripeGateway(Protocol):
    """Stripe anti-corruption port.

    Account dimension: every method touching Checkout Sessions, Customers,
    PaymentIntents, SetupIntents, PaymentMethods or Refunds takes an optional
    ``stripe_account``. ``None`` means the PLATFORM account (the house academy)
    and must produce exactly the platform call; a connected account id sends
    the Stripe-Account header, so the object is created on / read from that
    account. Stripe objects are account-scoped: an id minted on one account is
    ``resource_missing`` on every other account.
    """

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
        application_fee_cents: int = 0,
        stripe_account: str | None = None,
    ) -> tuple[str, str]:
        """Returns (checkout_session_id, redirect_url).

        ``stripe_account`` makes it a DIRECT charge created ON the academy's
        connected account, carrying ``application_fee_amount=application_fee_cents``
        (the academy's platform fee, default 0; omitted when 0). Every charge
        path uses this. ``connected_account_id`` (a platform destination charge)
        is legacy and has no caller. A non-zero fee without an account, or one
        larger than ``amount_cents``, raises ``ValueError``.
        """

    async def expire_checkout_session(
        self, checkout_session_id: str, *, stripe_account: str | None = None
    ) -> None:
        """Expire an open Checkout Session so it can never be paid.

        Called when a newer session supersedes it: two live sessions for the
        same enrollment is how one registration gets charged twice. Stripe
        REJECTS expiring a session that is already complete or expired, so
        callers must treat a failure here as benign — it means the parent
        already paid on that session, and the state written around this call
        must stand regardless.
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
        stripe_account: str | None = None,
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
        stripe_account: str | None = None,
    ) -> tuple[str, str]:
        """Returns (checkout_session_id, redirect_url) for saved-card setup.

        ``stripe_account`` runs the setup ON the academy's connected account, so
        the customer, SetupIntent and saved card all live there, where its
        direct charges run. ``connected_account_id`` (``on_behalf_of``) is legacy
        and has no caller.
        """

    async def create_invoice_checkout_session(
        self,
        *,
        invoice_id: str,
        amount_cents: int,
        currency: str,
        success_url: str,
        cancel_url: str,
        metadata: dict[str, str],
        idempotency_key: str | None = None,
        connected_account_id: str | None = None,
        save_payment_method_for_autopay: bool = False,
        autopay_enrollment_ids: list[str] | None = None,
        application_fee_cents: int = 0,
        stripe_account: str | None = None,
    ) -> tuple[str, str]:
        """Returns (checkout_session_id, redirect_url) for a ledger-invoice payment.

        ``stripe_account`` makes it a DIRECT charge on the academy's connected
        account (``application_fee_amount`` when non-zero); callers scope the
        idempotency key to that account. ``connected_account_id`` (a destination
        charge) is legacy and has no caller.
        ``save_payment_method_for_autopay`` saves the payment method for
        off-session autopay against an always-created customer.
        """

    async def create_customer_portal_session(
        self,
        *,
        parent_id: str,
        return_url: str,
        stripe_customer_id: str | None,
        stripe_account: str | None = None,
    ) -> str:
        """Returns portal redirect URL."""

    def verify_webhook(self, payload: bytes, signature: str) -> dict[str, object]: ...

    async def retrieve_checkout_session(
        self, checkout_session_id: str, *, stripe_account: str | None = None
    ) -> dict[str, Any]:
        """Fetch current Stripe Checkout Session state for reconciliation."""

    async def retrieve_invoice(self, stripe_invoice_id: str) -> dict[str, Any]:
        """Fetch current Stripe invoice state for reconciliation."""

    async def void_stripe_invoice(self, stripe_invoice_id: str) -> None:
        """Void an open/draft Stripe Invoicing invoice (issue #784).

        Called when the app voids a ledger invoice that Stripe also knows
        about. Without it the family keeps getting Stripe's own reminders and
        can still pay an invoice the academy has written off. Stripe refuses to
        void an invoice that was already paid; the caller logs that rather than
        rolling back the ledger-side void.
        """

    async def retrieve_subscription(self, stripe_subscription_id: str) -> dict[str, Any]:
        """Fetch current Stripe subscription state for reconciliation."""

    async def retrieve_payment_intent(
        self, stripe_payment_intent_id: str, *, stripe_account: str | None = None
    ) -> dict[str, Any]:
        """Fetch current Stripe PaymentIntent state for reconciliation."""

    async def retrieve_setup_intent(
        self, stripe_setup_intent_id: str, *, stripe_account: str | None = None
    ) -> dict[str, Any]:
        """Fetch current Stripe SetupIntent state for saved-payment-method setup."""

    async def retrieve_payment_method(
        self, stripe_payment_method_id: str, *, stripe_account: str | None = None
    ) -> dict[str, Any]:
        """Fetch current Stripe PaymentMethod state for saved-payment-method setup."""

    async def set_customer_default_payment_method(
        self,
        *,
        stripe_customer_id: str,
        stripe_payment_method_id: str,
        metadata: dict[str, str],
        stripe_account: str | None = None,
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
        self, *, stripe_customer_id: str, limit: int = 100, stripe_account: str | None = None
    ) -> list[dict[str, Any]]:
        """List a customer's recent succeeded charges (legacy invoice match candidates).

        Legacy/migrated payments carry no app metadata, so they cannot be matched
        by metadata. This surfaces a customer's historical charges so an admin can
        review and confirm a charge ↔ invoice match by hand (issue #242 WI-3).
        """

    async def issue_refund(
        self,
        payment_intent_id: str,
        amount_cents: int | None,
        *,
        idempotency_key: str | None = None,
        stripe_account: str | None = None,
    ) -> str:
        """Returns Stripe refund id.

        ``idempotency_key`` is forwarded as Stripe's ``Idempotency-Key``: a
        repeat with the same key returns the original refund, never a second.
        """

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

    async def retrieve_connected_account(self, stripe_account_id: str) -> dict[str, Any]:
        """Return the connected account's current Stripe state (a v1 Account:
        ``charges_enabled``, ``payouts_enabled``, ``capabilities``,
        ``requirements.disabled_reason``). Raises ``ValueError`` on failure."""
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
        application_fee_cents: int = 0,
        stripe_account: str | None = None,
    ) -> tuple[str, str, str | None]:
        """Confirm an off-session autopay charge; returns (pi_id, status, decline_code).

        ``stripe_account`` makes it a DIRECT charge on the academy's connected
        account: ``customer_id`` and ``payment_method_id`` must live on that
        account, and ``application_fee_amount=application_fee_cents`` (the
        academy's platform fee, default 0, set by a platform admin) is sent when
        non-zero. Without it the charge is on the platform (house academy).
        ``connected_account_id`` (a destination charge) is legacy and has no
        caller. A non-zero fee without an account, or one larger than
        ``amount_cents``, raises ``ValueError``.
        """
        ...

    async def get_default_payment_method(
        self, *, academy_id: str, parent_id: str, stripe_account: str | None = None
    ) -> tuple[str, str] | None:
        """(stripe_customer_id, default payment_method_id) for a parent's saved
        card on ``stripe_account`` (platform when None), or None."""
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
    async def list_all(self) -> list[SessionType]:
        """Active *and* archived rows — the only way to reach a soft-deleted type."""
        ...

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

    async def upsert(self, settings: BillingSettings) -> None:
        """Persist academy-editable settings. Never writes ``application_fee_bps``."""
        ...

    async def set_application_fee_bps(self, fee_bps: int) -> None:
        """Platform-admin only: set this academy's application fee (basis points)."""
        ...


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
        skip_if_disconnected: bool = False,
    ) -> bool: ...


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
    async def list_undelivered_invoices_for_period(
        self, period: str, *, limit: int = 100
    ) -> list[LedgerInvoice]: ...
    async def list_overdue_invoices(
        self, *, due_before: date, limit: int = 200
    ) -> list[LedgerInvoice]:
        """Collectable invoices whose due date is strictly before ``due_before``.

        Drives the automated late-fee pass (issue #552). ``due_before`` is
        exclusive so the caller can express "the grace period has fully
        elapsed" as ``today - grace_days`` without an off-by-one.
        """
        ...

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


# --- Owner (franchise) rollup ports (UIM11) ---------------------------------
#
# The rollup is the one read surface that spans academies. Both ports take an
# explicit `academy_id` so the aggregation layer iterates a membership-derived
# academy list rather than issuing any cross-tenant query.


class OwnerAcademyRef(BaseModel):
    """An academy the caller owns, resolved from their own memberships."""

    model_config = {"frozen": True}

    academy_id: str
    academy_name: str | None = None


class OwnerAcademyDirectory(Protocol):
    """Resolves the academy set a user owns. The ONLY source of rollup scope."""

    async def list_owner_academies(self, user_id: str) -> list[OwnerAcademyRef]: ...


class AcademyFinancialSnapshot(BaseModel):
    model_config = {"frozen": True}

    revenue_by_month: dict[str, int] = {}
    collected_cents: int = 0
    outstanding_cents: int = 0
    outstanding_invoice_count: int = 0


class AcademyFinancialSnapshotReader(Protocol):
    async def read(
        self, *, academy_id: str, months: tuple[str, ...] | None = None
    ) -> AcademyFinancialSnapshot: ...


class ParentAliasSetView(Protocol):
    """Identity: one users document and every id it may be referenced by."""

    @property
    def canonical_id(self) -> str: ...

    @property
    def aliases(self) -> frozenset[str]: ...


class ParentIdentityAliases(Protocol):
    """Identity: resolve a parent id to all of its aliases, one equality lookup
    per identity field (never an ``$or`` across fields, #878/#894)."""

    async def resolve_parent_aliases(
        self, raw_ids: Sequence[str]
    ) -> Mapping[str, ParentAliasSetView]: ...


class ParentInvoiceLedger(Protocol):
    """Tenant-scoped invoice reads for the parent portal (#932)."""

    async def list_invoices_for_parent_aliases(
        self, parent_ids: Sequence[str], *, limit: int = 100
    ) -> list[LedgerInvoice]: ...

    async def get_invoice(self, invoice_id: str) -> LedgerInvoice | None: ...

    async def get_lines_for_invoice(self, invoice_id: str) -> list[InvoiceLine]: ...
