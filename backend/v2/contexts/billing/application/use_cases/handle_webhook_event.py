"""Stripe webhook handler.

Verifies signature (via gateway), idempotently claims the event id, and
dispatches to per-event-type handlers. Each transition emits a domain
event into the outbox so cross-context handlers (Enrollment confirm,
auto-refund, comms) can react asynchronously.

Mirrors the legacy state machine documented in the Wave-2 research
artifact, but encapsulates each transition in a use case so tests cover
each case in isolation.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from pymongo.errors import DuplicateKeyError

from backend.v2.contexts.billing.application.ports import (
    AutopayConsentRepository,
    EnrollmentAutopayStateRepository,
    EnrollmentBillingIdentity,
    EnrollmentBillingIdentityRepository,
    FamilyAutopayPauser,
    LedgerRepository,
    ParentStripeCustomerRepository,
    PaymentDisputeRepository,
    PaymentRepository,
    StripeEventDedup,
    StripeGateway,
    StripeInvoiceProcessingRepository,
    StudentBillingEnrollmentRepository,
    SubscriptionRepository,
    TransactionRunner,
)
from backend.v2.contexts.billing.application.use_cases.billing_settings_admin import (
    BillingAuditAppender,
)
from backend.v2.contexts.billing.application.use_cases.checkout_allocation import (
    allocate_checkout_payment_across_invoices,
)
from backend.v2.contexts.billing.application.use_cases.invoice_numbering import (
    mint_invoice_number,
)
from backend.v2.contexts.billing.application.use_cases.parent_billing import (
    AutopayConsentCaptureContext,
    CompleteAutopaySetup,
)
from backend.v2.contexts.billing.application.use_cases.record_payment_dispute import (
    RecordPaymentDispute,
)
from backend.v2.contexts.billing.domain.ach_returns import normalize_nacha_return_code
from backend.v2.contexts.billing.domain.billing_audit import BillingAuditEntry
from backend.v2.contexts.billing.domain.checkout_hold import release_checkout_hold
from backend.v2.contexts.billing.domain.connected_account import (
    ConnectedAccount,
    liability_from_stripe_account,
)
from backend.v2.contexts.billing.domain.dunning import (
    UNRECONCILED_RETURN,
    UNSUPPORTED_PARTIAL_RETURN,
)
from backend.v2.contexts.billing.domain.errors import (
    InvalidWebhookSignature,
    PaymentNotFound,
    StripeAccountMismatch,
    WebhookAccountLookupUnavailable,
)
from backend.v2.contexts.billing.domain.events import (
    PAYMENT_RETURNED_NOTICE_PREFIX,
    CheckoutExpired,
    CheckoutExpiredPayload,
    DunningNoticeRequested,
    DunningNoticeRequestedPayload,
    InvoiceFailed,
    InvoiceLifecyclePayload,
    InvoicePaid,
    PaymentFailed,
    PaymentFailedPayload,
    PaymentReceiptRequested,
    PaymentReceiptRequestedPayload,
    PaymentRefunded,
    PaymentRefundedPayload,
    PaymentSucceeded,
    PaymentSucceededPayload,
    SubscriptionUpdated,
    SubscriptionUpdatedPayload,
)
from backend.v2.contexts.billing.domain.ledger import (
    InvoiceLine,
    LedgerInvoice,
    LedgerPayment,
)
from backend.v2.contexts.billing.domain.models import (
    Payment,
    can_transition_payment_projection,
)
from backend.v2.shared.events import Outbox
from backend.v2.shared.ids import new_ulid
from backend.v2.shared.observability.ops_alerts import capture_message
from backend.v2.shared.tenancy import tenant_scope
from backend.v2.shared.time.academy_timezone import (
    AcademyTimezoneReader,
    resolve_reporting_timezone,
)

# Every off-session PaymentIntent ChargeInvoiceViaAutopay creates: the scheduled
# autopay run and the two admin "charge now" buttons. A settling bank debit from
# either admin button used to fall through to the legacy path and never close
# the invoice (L1).
_OFF_SESSION_CHARGE_SOURCES = frozenset({"autopay", "admin_manual", "admin_billing_setup"})
log = logging.getLogger(__name__)

# Terminal Checkout Session outcomes. After any of these the session can no longer
# collect, so the manual-pay hold has to come off or autopay waits out the backstop
# for nothing. An unsettled (ACH) completion is included deliberately: it records a
# "processing" payment attempt, and the dunning claim already parks on that.
_CHECKOUT_HOLD_RELEASING_EVENTS = frozenset(
    {
        "checkout.session.completed",
        "checkout.session.expired",
        "checkout.session.async_payment_succeeded",
        "checkout.session.async_payment_failed",
    }
)

SUBSCRIPTION_INVOICE_RECOVERY_POINTS = {
    "received",
    "subscription_resolved",
    "ledger_invoice_synced",
    "ledger_payment_recorded",
    "ledger_allocated",
    "legacy_projection_saved",
    "processed",
    "quarantined",
}


# A Checkout session only proves money arrived for these payment_status values.
# Cards settle inline ("paid"); a zero-amount session is "no_payment_required".
# Delayed-notification methods (ACH / us_bank_account) complete as "unpaid" and
# settle later via checkout.session.async_payment_succeeded.
CHECKOUT_SETTLED_PAYMENT_STATUSES = frozenset({"paid", "no_payment_required"})


def _optional_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _checkout_session_is_settled(session: dict[str, Any]) -> bool:
    """True when a Checkout session's funds have actually arrived.

    Anything we cannot read as settled is treated as unsettled: a completion
    event is not proof of payment, so the ledger waits for the async event.
    """
    return str(session.get("payment_status") or "") in CHECKOUT_SETTLED_PAYMENT_STATUSES


def _checkout_invoice_ids(metadata: dict[str, Any]) -> list[str]:
    """Target invoice ids for a Checkout session (single pay-link or balance)."""
    single = str(metadata.get("invoice_id") or "").strip()
    if single:
        return [single]
    raw = str(metadata.get("invoice_ids") or "")
    return [item.strip() for item in raw.split(",") if item.strip()]


class _QuarantineStripeEvent(Exception):
    """Stored event is valid Stripe input but unsafe to project into Mongo."""


# Storage bucket for events that carry no tenant marker at all in multi-academy
# mode. It is not a real academy: no per-academy drain ever calls ``claim_next``
# with it, so an event stored here can never be processed, and it never inflates
# a real academy's billing-health quarantine counts.
UNATTRIBUTED_QUARANTINE_ACADEMY = "__unattributed__"

# ``quarantine_reason`` recorded for those events (kept distinct from the
# store's ``rejected_by_guard`` / ``retry_limit_exceeded`` so an ops sweep can
# select exactly "nobody could tell whose event this was").
QUARANTINE_UNATTRIBUTED = "unattributed_no_tenant_marker"

# ``quarantine_reason`` for a Connect event whose ``metadata.academy_id`` names
# a different academy than the one that owns the event's ``account``. The
# account is Stripe's own statement of where the money moved; metadata is text
# our code (or anyone able to edit the object on that account) wrote. The two
# disagreeing means something is wrong, so neither is trusted to project.
QUARANTINE_ACCOUNT_METADATA_CONFLICT = "connect_account_metadata_conflict"

# ``quarantine_reason`` for a ``metadata.source == "platform_plan"`` event that
# carries a top-level ``account``. Platform-plan objects live on the platform
# account only, so a Connect event tagged as one is metadata someone wrote on
# a connected account: it is neither synced nor processed as tuition.
QUARANTINE_PLATFORM_PLAN_ON_CONNECT_ACCOUNT = "platform_plan_on_connect_account"


class AccountAcademyResolver(Protocol):
    """Resolves a Stripe Connect account id to its owning academy id.

    ``academy_id_for_account`` must answer across EVERY academy (composition
    backs it with the platform-scoped ``ConnectedAccountDirectory``): ingest
    attributes direct-charge events for accounts the boot academy does not
    own. ``get_by_stripe_account_id`` / ``update_status`` stay scoped to the
    handler's own academy.

    Typed against this Protocol (rather than ``Any``) so a composition-root
    mismatch — e.g. passing the raw ``ConnectedAccountRepository`` instead of
    the ``_ConnectAccountResolver`` shim that bridges its method name — fails
    at type-check time instead of at the first live webhook (the Slice-B
    lesson: an untyped port/repo name mismatch reached production before).
    """

    async def academy_id_for_account(self, stripe_account_id: str) -> str | None: ...

    async def get_by_stripe_account_id(self, stripe_account_id: str) -> ConnectedAccount | None: ...

    async def update_status(
        self,
        *,
        stripe_account_id: str,
        status: str,
        charges_enabled: bool | None,
        payouts_enabled: bool | None,
        capabilities: dict[str, str],
        skip_if_disconnected: bool = False,
        liability: dict[str, str] | None = None,
    ) -> bool: ...


#: ``async (event_type, event) -> None``: the platform billing context's
#: ``SyncTenantSubscriptionFromStripe``. An academy paying CourtMastr for a
#: plan (``metadata.source == "platform_plan"``) is not parent tuition, so
#: those events never reach the tuition handlers.
PlatformPlanSync = Callable[[str, dict[str, Any]], Awaitable[None]]
PLATFORM_PLAN_EVENT_TYPES = frozenset(
    {
        "checkout.session.completed",
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
    }
)


class HandleWebhookEvent:
    def __init__(
        self,
        *,
        stripe: StripeGateway,
        dedup: StripeEventDedup,
        payments: PaymentRepository,
        subscriptions: SubscriptionRepository,
        outbox: Outbox,
        academy_id: str,
        billing_enrollments: StudentBillingEnrollmentRepository | None = None,
        billing_ledger: LedgerRepository | None = None,
        billing_counters: Any | None = None,
        billing_settings: Any | None = None,
        parent_customers: ParentStripeCustomerRepository | None = None,
        enrollment_autopay: EnrollmentAutopayStateRepository | None = None,
        consent_repo: AutopayConsentRepository | None = None,
        transaction_runner: TransactionRunner | None = None,
        enrollment_identity: EnrollmentBillingIdentityRepository | None = None,
        invoice_processing: StripeInvoiceProcessingRepository | None = None,
        connected_accounts: AccountAcademyResolver | None = None,
        payment_disputes: PaymentDisputeRepository | None = None,
        platform_plan_sync: PlatformPlanSync | None = None,
        family_autopay: FamilyAutopayPauser | None = None,
        expected_livemode: bool | None = None,
        tenancy_mode: str = "single_academy",
        academy_timezone: AcademyTimezoneReader | None = None,
        billing_audit: BillingAuditAppender | None = None,
        clock=lambda: datetime.now(UTC),
    ) -> None:
        self._stripe = stripe
        self._billing_audit = billing_audit
        self._dedup = dedup
        self._payments = payments
        self._subscriptions = subscriptions
        self._billing_enrollments = billing_enrollments
        self._billing_ledger = billing_ledger
        self._billing_counters = billing_counters
        self._billing_settings = billing_settings
        self._parent_customers = parent_customers
        self._enrollment_autopay = enrollment_autopay
        self._consent_repo = consent_repo
        self._transaction_runner = transaction_runner
        self._enrollment_identity = enrollment_identity
        self._invoice_processing = invoice_processing
        self._connected_accounts = connected_accounts
        self._platform_plan_sync = platform_plan_sync
        self._family_autopay = family_autopay
        self._expected_livemode = expected_livemode
        self._tenancy_mode = tenancy_mode
        self._academy_timezone = academy_timezone
        self._outbox = outbox
        self._academy_id = academy_id
        self._now = clock
        self._record_dispute: RecordPaymentDispute | None = None
        if payment_disputes is not None:
            self._record_dispute = RecordPaymentDispute(
                disputes=payment_disputes,
                payments=payments,
                ledger=billing_ledger,
                outbox=outbox,
                academy_id=academy_id,
                clock=clock,
            )
        self._complete_autopay_setup: CompleteAutopaySetup | None = None
        if parent_customers is not None and enrollment_autopay is not None:
            self._complete_autopay_setup = CompleteAutopaySetup(
                stripe=stripe,
                parent_customers=parent_customers,
                enrollment_autopay=enrollment_autopay,
                consent_repo=consent_repo,
                outbox=outbox,
                transaction_runner=transaction_runner,
                academy_id=academy_id,
                clock=clock,
            )

    async def accept(self, payload: bytes, signature: str) -> dict[str, Any]:
        """Verify and persist a Stripe event, then return quickly.

        Business projection happens later via ``process_next`` so Stripe
        delivery is not blocked on Mongo ledger/customer/subscription writes.
        """
        event = self._verify(payload, signature)
        event_id, event_type = self._event_identity(event)

        academy_id, quarantine_reason, reason_code = await self._ingest_academy_id(event)
        with tenant_scope(academy_id):
            stored = await self._dedup.store_received(
                event,
                raw_payload=payload,
                academy_id=academy_id,
            )
            if not stored:
                # Also covers a Stripe retry of an event we already quarantined:
                # the insert-first store is the dedup, so there is no second
                # row, no second quarantine mark and no second alert.
                log.info("stripe_webhook_already_stored event_id=%s", event_id)
                return {"received": True, "stored": False, "type": event_type}
            if quarantine_reason is None:
                return {"received": True, "stored": True, "type": event_type}
            await self._dedup.mark_quarantined(event_id, quarantine_reason, reason_code=reason_code)
        log.warning(
            "stripe_webhook_event_unattributed"
            if reason_code == QUARANTINE_UNATTRIBUTED
            else "stripe_webhook_event_account_metadata_conflict"
            if reason_code == QUARANTINE_ACCOUNT_METADATA_CONFLICT
            else "stripe_webhook_event_platform_plan_on_connect_account",
            extra={
                "event_id": event_id,
                "event_type": event_type,
                "tenancy_mode": self._tenancy_mode,
            },
        )
        self._alert_quarantined(
            event_id=event_id,
            event_type=event_type,
            reason=reason_code,
            error=quarantine_reason,
            # The row lives under the sentinel bucket, not the boot academy;
            # the alert must point ops at the same academy_id as the row.
            academy_id=academy_id,
        )
        # 200 on purpose: the event is persisted and needs a human, not a retry.
        return {
            "received": True,
            "stored": True,
            "type": event_type,
            "status": "quarantined",
        }

    async def _ingest_academy_id(self, event: dict[str, Any]) -> tuple[str, str | None, str]:
        """Tenant attribution at INGEST time (issues #532 and the unattributed
        follow-up; Connect ownership for direct charges).

        The /webhooks/stripe endpoint is served by the boot-academy handler,
        but the drain claims stored events per academy — an event stamped with
        the wrong academy would be claimed by the wrong per-academy processor
        and quarantined by its cross-academy guard instead of reaching its own.

        Returns ``(academy_id_to_store_under, quarantine_reason, reason_code)``;
        the reason is ``None`` whenever the event may be processed normally.

        Resolution order:
        1. Top-level ``account`` (Connect events: every direct charge on a
           non-house academy's connected account) resolved to its OWNER across
           all academies. The account is authoritative:
           - owner found, ``metadata.academy_id`` absent or equal: the owner.
           - owner found, ``metadata.academy_id`` names ANOTHER academy:
             quarantined under the owner (``QUARANTINE_ACCOUNT_METADATA_CONFLICT``).
             Metadata never overrides the account. The owner's processing
             guard would reject it too (metadata != its academy), so a drain
             racing the quarantine mark cannot project it either.
           - no owner (unknown account): stored under this handler's
             academy, where the processing-side guard
             (``resolve_academy_for_event``) re-resolves and quarantines with
             its own alert. Deferring keeps an account row written a moment
             after Stripe emitted its first event from becoming a terminal
             ingest quarantine.
           - the lookup itself FAILED: ``WebhookAccountLookupUnavailable``
             (503). Nothing is stored, so Stripe redelivers the event later;
             storing it under the boot academy would strand it there as a
             quarantined row the owner's processor never claims.
        2. No ``account`` (a platform event — the house academy, and legacy
           destination charges): ``metadata.academy_id`` exactly as before.
        3. Neither marker:
           - ``single_academy`` mode: this handler's academy. There is exactly
             one tenant (``primary_academy_id``) by construction, so a platform
             event with no marker cannot belong to anyone else; every event
             type the platform account emits is safe to attribute here.
           - ``multi_academy`` mode: nobody. One endpoint ingests every
             academy's traffic, so attributing to the boot academy would credit
             a tenant at random. The event is stored under
             ``UNATTRIBUTED_QUARANTINE_ACADEMY`` and quarantined by ``accept``.

        Raises only ``WebhookAccountLookupUnavailable`` past signature
        verification, and only when the owner lookup errors.
        """
        metadata = self._event_metadata(event)
        metadata_academy = metadata.get("academy_id")
        account_id = str(event.get("account") or "")
        if account_id and metadata.get("source") == "platform_plan":
            return (
                self._academy_id,
                f"metadata.source=platform_plan on connected account {account_id}; "
                "platform-plan events come from the platform account only",
                QUARANTINE_PLATFORM_PLAN_ON_CONNECT_ACCOUNT,
            )
        if account_id:
            owner: str | None = None
            if self._connected_accounts is not None:
                try:
                    owner = await self._connected_accounts.academy_id_for_account(account_id)
                except Exception as exc:
                    log.warning(
                        "stripe_webhook_ingest_account_resolution_failed account=%s err=%s",
                        account_id,
                        exc,
                    )
                    raise WebhookAccountLookupUnavailable(
                        "Connected-account owner lookup failed; retry the delivery."
                    ) from exc
            if not owner:
                return self._academy_id, None, QUARANTINE_UNATTRIBUTED
            if metadata_academy and metadata_academy != owner:
                return (
                    owner,
                    f"metadata.academy_id={metadata_academy} conflicts with the owner "
                    f"{owner} of connected account {account_id}; the account wins and "
                    "the event is not projected",
                    QUARANTINE_ACCOUNT_METADATA_CONFLICT,
                )
            return owner, None, QUARANTINE_UNATTRIBUTED
        if metadata_academy:
            return metadata_academy, None, QUARANTINE_UNATTRIBUTED
        if self._tenancy_mode == "single_academy":
            return self._academy_id, None, QUARANTINE_UNATTRIBUTED
        return (
            UNATTRIBUTED_QUARANTINE_ACADEMY,
            "no metadata.academy_id and no Connect account on the event; "
            f"refusing to attribute to boot academy {self._academy_id} in multi_academy mode",
            QUARANTINE_UNATTRIBUTED,
        )

    async def process_next(
        self,
        *,
        processor_id: str,
        lock_seconds: int = 300,
    ) -> dict[str, Any]:
        with tenant_scope(self._academy_id):
            event_doc = await self._dedup.claim_next(
                academy_id=self._academy_id,
                processor_id=processor_id,
                lock_seconds=lock_seconds,
            )
            if event_doc is None:
                return {"processed": False, "empty": True}

            event_id = str(event_doc.get("event_id") or "")
            event_type = str(event_doc.get("event_type") or "")
            try:
                event = self._event_from_stored_payload(event_doc)
                event_type = event_type or str(event.get("type", ""))
                self._validate_livemode(event)
                # Account ownership BEFORE hydration: hydrating reads the
                # object from Stripe with the event's ``Stripe-Account``
                # header, which must never happen for an account this
                # academy does not own (or no academy owns).
                await self.resolve_academy_for_event(event)
                event = await self._hydrate_current_stripe_object(event_type, event)
                # Metadata guards run on the hydrated object, as before.
                self._validate_event_guards(event)
                await self._dispatch(event_type, event)
                await self._dedup.mark_processed(event_id)
                return {"processed": True, "event_id": event_id, "type": event_type}
            except _QuarantineStripeEvent as exc:
                await self._dedup.mark_quarantined(event_id, str(exc))
                self._alert_quarantined(
                    event_id=event_id,
                    event_type=event_type,
                    reason="rejected_by_guard",
                    error=str(exc),
                )
                return {
                    "processed": False,
                    "event_id": event_id,
                    "type": event_type,
                    "status": "quarantined",
                    "error": str(exc),
                }
            except Exception as exc:
                # Retries are bounded (#437): this may be the attempt that gives
                # up, in which case the event is now quarantined and nothing will
                # look at it again unless someone is told.
                status = await self._dedup.mark_failed(event_id, str(exc))
                if status == "quarantined":
                    self._alert_quarantined(
                        event_id=event_id,
                        event_type=event_type,
                        reason="retry_limit_exceeded",
                        error=str(exc),
                    )
                return {
                    "processed": False,
                    "event_id": event_id,
                    "type": event_type,
                    "status": status,
                    "error": str(exc),
                }

    def _alert_quarantined(
        self,
        *,
        event_id: str,
        event_type: str,
        reason: str,
        error: str,
        academy_id: str | None = None,
    ) -> None:
        """Tell someone an event has stopped being retried (issues #437, #428).

        Quarantine is terminal — the drain never claims the event again — so
        this fires exactly once per event, not once per retry. Before this, a
        poisoned event's only trace was a `failed` tally in a log line.

        Never raises: an alerting problem must not turn a recorded quarantine
        into an unrecorded crash.
        """
        extra = {
            "event_id": event_id,
            "event_type": event_type,
            # Default to the handler's academy (processing-side quarantines are
            # always its own rows); ingest passes the bucket the row was stored
            # under so the log never re-attributes an unattributed event.
            "academy_id": academy_id if academy_id is not None else self._academy_id,
            "quarantine_reason": reason,
        }
        try:
            log.error("stripe_webhook_event_quarantined", extra=extra)
            capture_message(
                f"Stripe webhook event quarantined ({reason}): {event_id} [{event_type}] — {error}"
            )
        except Exception:  # pragma: no cover - defensive
            log.warning("stripe_webhook_quarantine_alert_failed", exc_info=True)

    async def execute(self, payload: bytes, signature: str) -> dict[str, Any]:
        event = self._verify(payload, signature)
        event_id, event_type = self._event_identity(event)

        with tenant_scope(self._academy_id):
            claimed = await self._dedup.claim(event_id, event_type)
            if not claimed:
                log.info("stripe_webhook_deduped event_id=%s", event_id)
                return {"received": True, "deduped": True}

            try:
                await self._dispatch(event_type, event)
                await self._dedup.mark_processed(event_id)
                return {"received": True, "type": event_type}
            except _QuarantineStripeEvent as exc:
                mark_quarantined = getattr(self._dedup, "mark_quarantined", None)
                if mark_quarantined is not None:
                    await mark_quarantined(event_id, str(exc))
                else:
                    await self._dedup.mark_failed(event_id, str(exc))
                self._alert_quarantined(
                    event_id=event_id,
                    event_type=event_type,
                    reason="rejected_by_guard",
                    error=str(exc),
                )
                return {
                    "received": True,
                    "type": event_type,
                    "status": "quarantined",
                    "error": str(exc),
                }
            except Exception as exc:
                status = await self._dedup.mark_failed(event_id, str(exc))
                if status == "quarantined":
                    self._alert_quarantined(
                        event_id=event_id,
                        event_type=event_type,
                        reason="retry_limit_exceeded",
                        error=str(exc),
                    )
                raise

    def _verify(self, payload: bytes, signature: str) -> dict[str, Any]:
        try:
            event = self._stripe.verify_webhook(payload, signature)
        except Exception as exc:
            raise InvalidWebhookSignature(str(exc)) from exc
        if not isinstance(event, dict):
            raise InvalidWebhookSignature("event payload did not parse to object")
        self._event_identity(event)
        return event

    @staticmethod
    def _event_identity(event: dict[str, Any]) -> tuple[str, str]:
        event_id = str(event.get("id", ""))
        event_type = str(event.get("type", ""))
        if not event_id or not event_type:
            raise InvalidWebhookSignature("event missing id or type")
        return event_id, event_type

    @staticmethod
    def _event_from_stored_payload(event_doc: dict[str, Any]) -> dict[str, Any]:
        raw_payload = event_doc.get("raw_payload")
        if isinstance(raw_payload, bytes):
            decoded = raw_payload.decode("utf-8")
        elif isinstance(raw_payload, str):
            decoded = raw_payload
        elif isinstance(raw_payload, dict):
            return raw_payload
        else:
            raise ValueError("stored Stripe event missing raw payload")
        parsed = json.loads(decoded)
        if not isinstance(parsed, dict):
            raise ValueError("stored Stripe event raw payload is not an object")
        return parsed

    def _validate_event_guards(self, event: dict[str, Any]) -> None:
        self._validate_livemode(event)
        metadata = self._event_metadata(event)
        academy_id = metadata.get("academy_id")
        if academy_id and academy_id != self._academy_id:
            raise _QuarantineStripeEvent(
                f"academy mismatch: event={academy_id} expected={self._academy_id}"
            )

    async def _validate_event_guards_async(self, event: dict[str, Any]) -> None:
        """Full guard: sync metadata checks + Connect account-based tenant check.

        Connect events (``account.*``, ``capability.*``, etc.) carry a top-level
        ``account`` field naming the connected account they occurred on. We
        resolve that account to its owning academy and quarantine anything that
        does not belong to this handler's academy (or is unknown).
        """
        self._validate_event_guards(event)
        await self.resolve_academy_for_event(event)

    async def resolve_academy_for_event(self, event: dict[str, Any]) -> str:
        """Resolve the academy a Stripe event belongs to.

        For Connect events (top-level ``account``), resolve via the
        connected-account repo and require it to match this handler's academy —
        otherwise quarantine. For platform (non-Connect) events, fall back to the
        handler's configured academy.
        """
        account_id = str(event.get("account") or "")
        if not account_id:
            return self._academy_id
        if self._connected_accounts is None:
            # No resolver wired: cannot safely attribute a Connect event.
            raise _QuarantineStripeEvent(
                f"connect event for account={account_id} but no connected-account resolver"
            )
        resolved = await self._connected_accounts.academy_id_for_account(account_id)
        if resolved is None:
            raise _QuarantineStripeEvent(f"unknown connected account: account={account_id}")
        if resolved != self._academy_id:
            raise _QuarantineStripeEvent(
                f"connect account academy mismatch: account={account_id} "
                f"resolved={resolved} expected={self._academy_id}"
            )
        return resolved

    def _validate_livemode(self, event: dict[str, Any]) -> None:
        if self._expected_livemode is not None:
            livemode = bool(event.get("livemode", False))
            if livemode != self._expected_livemode:
                raise _QuarantineStripeEvent(
                    f"livemode mismatch: event={livemode} expected={self._expected_livemode}"
                )

    @staticmethod
    def _event_metadata(event: dict[str, Any]) -> dict[str, str]:
        obj = event.get("data", {}).get("object", {})
        if not isinstance(obj, dict):
            return {}
        metadata = obj.get("metadata")
        if not isinstance(metadata, dict):
            return {}
        return {str(k): str(v) for k, v in metadata.items() if v is not None}

    async def _hydrate_current_stripe_object(
        self,
        event_type: str,
        event: dict[str, Any],
    ) -> dict[str, Any]:
        obj = event.get("data", {}).get("object", {})
        if not isinstance(obj, dict):
            return event
        object_id = str(obj.get("id") or "")
        if not object_id:
            return event
        current: dict[str, Any] | None = None
        # A direct charge's objects live on the connected account the event
        # names; a platform event carries no account and reads the platform.
        on_account = _on_account_kwargs(_event_account(event))
        if event_type in (
            "checkout.session.completed",
            "checkout.session.expired",
            "checkout.session.async_payment_succeeded",
            "checkout.session.async_payment_failed",
        ):
            current = await self._stripe.retrieve_checkout_session(object_id, **on_account)
        elif event_type in ("invoice.paid", "invoice.payment_failed"):
            current = await self._stripe.retrieve_invoice(object_id)
        elif event_type in (
            "customer.subscription.created",
            "customer.subscription.updated",
            "customer.subscription.deleted",
        ):
            current = await self._stripe.retrieve_subscription(object_id)
        elif event_type in (
            "payment_intent.succeeded",
            "payment_intent.payment_failed",
            "payment_intent.processing",
        ):
            current = await self._stripe.retrieve_payment_intent(object_id, **on_account)
        elif event_type == "setup_intent.succeeded":
            current = await self._stripe.retrieve_setup_intent(object_id, **on_account)
        if not current:
            return event
        merged = dict(obj)
        for key, value in current.items():
            if value not in (None, "", {}, []):
                merged[key] = value
        hydrated = dict(event)
        data = dict(hydrated.get("data") or {})
        data["object"] = merged
        hydrated["data"] = data
        return hydrated

    async def _dispatch(self, event_type: str, event: dict[str, Any]) -> None:
        await self._dispatch_event(event_type, event)
        # Only once the handler has actually settled the outcome. Releasing before (or
        # in a finally) would hand a still-open invoice back to autopay after a parent
        # has already paid through the session — the exact double charge this guards.
        # A handler that raised keeps the hold; Stripe retries the event, and the
        # 90-minute backstop covers a webhook that never lands at all (issue #434).
        if event_type in _CHECKOUT_HOLD_RELEASING_EVENTS:
            await self._release_checkout_holds(event)

    async def _release_checkout_holds(self, event: dict[str, Any]) -> None:
        """Free every invoice this Checkout Session was holding.

        Scoped to the session in the event: a late webhook for a session the parent
        already abandoned must not unlock an invoice whose newer session is still open.
        Best-effort per invoice — a hold we fail to clear lapses on its own within
        CHECKOUT_HOLD_WINDOW, so a failure here delays collection rather than losing it.
        """
        if self._billing_ledger is None:
            return
        obj = event.get("data", {}).get("object", {})
        if not isinstance(obj, dict):
            return
        checkout_session_id = str(obj.get("id") or "")
        if not checkout_session_id:
            return
        now = self._now()
        for invoice_id in _checkout_invoice_ids(self._event_metadata(event)):
            try:
                invoice = await self._billing_ledger.get_invoice(invoice_id)
                if invoice is None:
                    continue
                released = release_checkout_hold(
                    invoice,
                    now=now,
                    checkout_session_id=checkout_session_id,
                )
                if released is None:
                    continue
                await self._billing_ledger.save_invoice(released)
                log.info(
                    "checkout hold released invoice=%s session=%s",
                    invoice_id,
                    checkout_session_id,
                )
            except Exception as exc:
                log.warning(
                    "failed to release checkout hold invoice=%s session=%s err=%s",
                    invoice_id,
                    checkout_session_id,
                    exc,
                )

    async def _dispatch_event(self, event_type: str, event: dict[str, Any]) -> None:
        if (
            event_type in PLATFORM_PLAN_EVENT_TYPES
            and self._event_metadata(event).get("source") == "platform_plan"
        ):
            if event.get("account"):
                # Ingest already quarantines this; a drain racing that mark
                # must not sync it either.
                raise _QuarantineStripeEvent(
                    f"platform_plan event on connected account {event['account']}"
                )
            if self._platform_plan_sync is None:
                log.warning("platform_plan event ignored: no sync wired type=%s", event_type)
                return
            await self._platform_plan_sync(event_type, event)
            return
        if event_type == "checkout.session.completed":
            metadata = self._event_metadata(event)
            if metadata.get("source") == "autopay_setup":
                await self._handle_autopay_setup_checkout_completed(event)
            elif metadata.get("source") == "invoice_pay_link" or metadata.get("invoice_id"):
                await self._handle_invoice_checkout_completed(event)
            elif metadata.get("type") == "balance_payment" or metadata.get("invoice_ids"):
                await self._handle_balance_checkout_completed(event)
            else:
                await self._on_checkout_completed(event)
        elif event_type == "checkout.session.expired":
            await self._on_checkout_expired(event)
        elif event_type == "checkout.session.async_payment_succeeded":
            # Delayed-settlement funds actually arrived: the session now reads
            # payment_status "paid", so the completed handlers do the right thing.
            # Their session-keyed idempotency makes this converge with the earlier
            # unsettled pass instead of double-allocating.
            metadata = self._event_metadata(event)
            if metadata.get("source") == "invoice_pay_link" or metadata.get("invoice_id"):
                await self._handle_invoice_checkout_completed(event)
            elif metadata.get("type") == "balance_payment" or metadata.get("invoice_ids"):
                await self._handle_balance_checkout_completed(event)
            else:
                log.info(
                    "checkout.session.async_payment_succeeded ignored session=%s",
                    event.get("data", {}).get("object", {}).get("id"),
                )
        elif event_type == "checkout.session.async_payment_failed":
            metadata = self._event_metadata(event)
            if (
                metadata.get("source") == "invoice_pay_link"
                or metadata.get("invoice_id")
                or metadata.get("type") == "balance_payment"
                or metadata.get("invoice_ids")
            ):
                await self._handle_checkout_async_payment_failed(event)
            else:
                log.info(
                    "checkout.session.async_payment_failed ignored session=%s",
                    event.get("data", {}).get("object", {}).get("id"),
                )
        elif event_type == "payment_intent.succeeded":
            metadata = self._event_metadata(event)
            if metadata.get("source") in _OFF_SESSION_CHARGE_SOURCES:
                await self._handle_autopay_pi_succeeded(event)
            elif (
                metadata.get("source") == "invoice_pay_link"
                or metadata.get("type") == "balance_payment"
                or metadata.get("invoice_ids")
            ):
                log.info(
                    "payment_intent.succeeded for checkout invoice payment ignored pi=%s",
                    event.get("data", {}).get("object", {}).get("id"),
                )
            else:
                await self._on_payment_succeeded(event)
        elif event_type == "payment_intent.payment_failed":
            metadata = self._event_metadata(event)
            if metadata.get("source") in _OFF_SESSION_CHARGE_SOURCES:
                await self._handle_autopay_pi_failed(event)
            elif await self._handle_invoice_checkout_payment_failed(event):
                return
            else:
                await self._on_payment_failed(event)
        elif event_type == "payment_intent.processing":
            metadata = self._event_metadata(event)
            if metadata.get("source") in _OFF_SESSION_CHARGE_SOURCES:
                await self._handle_autopay_pi_processing(event)
            else:
                log.info(
                    "payment_intent.processing ignored pi=%s",
                    event.get("data", {}).get("object", {}).get("id"),
                )
        elif event_type == "invoice.paid":
            await self._on_invoice_paid(event)
        elif event_type == "invoice.payment_failed":
            await self._on_invoice_payment_failed(event)
        elif event_type == "charge.refunded":
            await self._on_charge_refunded(event)
        elif event_type in ("charge.dispute.created", "charge.dispute.closed"):
            await self._on_charge_dispute(event)
        elif event_type in ("refund.failed", "refund.updated"):
            await self._on_refund_failed(event)
        elif event_type in ("mandate.updated", "payment_method.automatically_updated"):
            await self._on_payment_method_unusable(event)
        elif event_type == "setup_intent.succeeded":
            metadata = self._event_metadata(event)
            if metadata.get("source") == "autopay_setup":
                await self._handle_autopay_setup_intent_succeeded(event)
            else:
                log.info(
                    "setup_intent.succeeded ignored setup_intent=%s",
                    event.get("data", {}).get("object", {}).get("id"),
                )
        elif event_type in (
            "customer.subscription.created",
            "customer.subscription.updated",
            "customer.subscription.deleted",
        ):
            await self._on_subscription_changed(event)
        elif event_type == "account.updated" or event_type.startswith("capability."):
            await self._handle_connected_account_status_updated(event)
        else:
            log.info("stripe_webhook_ignored type=%s", event_type)

    async def _handle_connected_account_status_updated(self, event: dict[str, Any]) -> None:
        if self._connected_accounts is None:
            log.warning("connect_account_status_updated: connected_accounts not configured")
            return
        obj = event.get("data", {}).get("object", {})
        if not isinstance(obj, dict):
            obj = {}
        event_type = str(event.get("type") or "")
        if event_type.startswith("capability."):
            stripe_account_id = str(obj.get("account") or event.get("account") or "")
        else:
            stripe_account_id = str(
                obj.get("id") or obj.get("account") or event.get("account") or ""
            )
        if not stripe_account_id:
            raise _QuarantineStripeEvent("Connect account status event missing account id")

        capabilities_obj = obj.get("capabilities") or {}
        capabilities: dict[str, str] = {}
        if isinstance(capabilities_obj, dict):
            capabilities = {str(key): str(value) for key, value in capabilities_obj.items()}
        elif event_type.startswith("capability."):
            capability_id = str(obj.get("id") or "")
            capability_status = str(obj.get("status") or "")
            if capability_id and capability_id != stripe_account_id and capability_status:
                capabilities[capability_id] = capability_status

        charges_enabled = _optional_bool(obj.get("charges_enabled"))
        payouts_enabled = _optional_bool(obj.get("payouts_enabled"))
        if charges_enabled is None:
            # capability.* payloads carry no account-level flags; keep the
            # status derived from the last account.updated event instead of
            # silently downgrading an active account to "restricted".
            existing = await self._connected_accounts.get_by_stripe_account_id(stripe_account_id)
            status = existing.status if existing is not None else "restricted"
        else:
            status = "active" if charges_enabled else "restricted"
        if str(obj.get("disabled_reason") or ""):
            status = "disabled"

        # An owner disconnect is local: Stripe keeps the account and keeps
        # emitting account.updated for it. Until an explicit reconnect, those
        # events must not flip it back to active (the write is conditional on
        # the row not being disconnected, atomically).
        applied = await self._connected_accounts.update_status(
            stripe_account_id=stripe_account_id,
            status=status,
            charges_enabled=charges_enabled,
            payouts_enabled=payouts_enabled,
            capabilities=capabilities,
            skip_if_disconnected=True,
            # The account's fee/loss responsibilities as this payload reports
            # them (v1 ``controller``); the charge route refuses direct
            # charges unless both are Stripe's.
            liability=liability_from_stripe_account(obj),
        )
        if applied is False:
            log.info(
                "connect_account_status_ignored_disconnected account=%s type=%s",
                stripe_account_id,
                event_type,
            )

    async def _handle_autopay_setup_checkout_completed(self, event: dict[str, Any]) -> None:
        if self._complete_autopay_setup is None:
            raise _QuarantineStripeEvent("autopay setup completion dependencies are missing")
        checkout = event["data"]["object"]
        try:
            await self._complete_autopay_setup.execute_from_checkout(
                checkout,
                consent_context=AutopayConsentCaptureContext(source="stripe_webhook"),
                # A direct-charge checkout ran ON the academy's connected
                # account; the event names it. Platform events carry none.
                **_on_account_kwargs(_event_account(event)),
            )
        except PaymentNotFound as exc:
            raise _QuarantineStripeEvent(str(exc)) from exc
        except ValueError as exc:
            raise _QuarantineStripeEvent(str(exc)) from exc

    async def _handle_autopay_setup_intent_succeeded(self, event: dict[str, Any]) -> None:
        if self._complete_autopay_setup is None:
            raise _QuarantineStripeEvent("autopay setup completion dependencies are missing")
        setup_intent = event["data"]["object"]
        try:
            await self._complete_autopay_setup.execute_from_setup_intent(
                setup_intent,
                consent_context=AutopayConsentCaptureContext(source="setup_intent_webhook"),
                **_on_account_kwargs(_event_account(event)),
            )
        except PaymentNotFound as exc:
            raise _QuarantineStripeEvent(str(exc)) from exc
        except ValueError as exc:
            raise _QuarantineStripeEvent(str(exc)) from exc

    async def _handle_invoice_checkout_completed(self, event: dict[str, Any]) -> None:
        """Handle checkout.session.completed from an invoice pay-link.

        Idempotent by checkout_session_id: if a ledger payment already exists
        for this session, the record_payment call returns the existing row and
        allocation is skipped via its own idempotency_key.
        """
        if self._billing_ledger is None:
            log.warning("invoice_checkout_completed: billing_ledger not configured — skipping")
            return

        obj = event["data"]["object"]
        checkout_session_id: str = str(obj.get("id") or "")
        metadata = obj.get("metadata") or {}
        invoice_id = str(metadata.get("invoice_id") or "")
        if not invoice_id:
            log.warning(
                "invoice_checkout_completed: no invoice_id in metadata session=%s",
                checkout_session_id,
            )
            return

        payment_intent_id: str | None = obj.get("payment_intent") or None
        if payment_intent_id:
            payment_intent_id = str(payment_intent_id)
        amount_total = int(obj.get("amount_total") or 0)
        currency = str(obj.get("currency") or "usd").lower()

        if not _checkout_session_is_settled(obj):
            await self._record_unsettled_checkout_attempt(
                event=event,
                checkout_session_id=checkout_session_id,
                invoice_ids=[invoice_id],
                parent_id=str(metadata.get("parent_id") or "unknown"),
                amount_cents=amount_total,
                currency=currency,
                payment_intent_id=payment_intent_id,
            )
            await self._maybe_activate_autopay_optin(obj, stripe_account=_event_account(event))
            return

        now = self._now()
        idempotency_key = f"invoice-checkout:{checkout_session_id}"
        ledger_payment_id = f"ledger-pay-cs:{checkout_session_id}"

        if await self._payment_intent_already_credited(
            payment_intent_id=payment_intent_id,
            ledger_payment_id=ledger_payment_id,
        ):
            return

        payment = await self._billing_ledger.record_payment(
            LedgerPayment(
                payment_id=ledger_payment_id,
                academy_id=self._academy_id,
                parent_id=str(metadata.get("parent_id") or "unknown"),
                amount_cents=amount_total,
                unapplied_amount_cents=amount_total,
                currency=currency,
                status="succeeded",
                payment_method="stripe_checkout",
                stripe_payment_intent_id=payment_intent_id,
                stripe_account_id=_event_account(event),
                application_fee_cents=_application_fee_cents(obj),
                paid_at=now,
                created_at=now,
                updated_at=now,
            ),
            idempotency_key=idempotency_key,
        )

        if amount_total > 0:
            await self._billing_ledger.allocate_payment(
                payment_id=payment.payment_id,
                invoice_id=invoice_id,
                amount_cents=amount_total,
                idempotency_key=f"invoice-checkout-alloc:{checkout_session_id}",
            )
            log.info(
                "invoice_checkout_completed: allocated payment=%s to invoice=%s amount=%d",
                payment.payment_id,
                invoice_id,
                amount_total,
            )
        await self._request_receipt(
            payment=payment,
            invoice=await self._billing_ledger.get_invoice(invoice_id),
            autopay=False,
            bank_debit=False,
        )

        await self._maybe_activate_autopay_optin(obj, stripe_account=_event_account(event))

    async def _maybe_activate_autopay_optin(
        self, checkout: dict[str, Any], *, stripe_account: str | None = None
    ) -> None:
        """Autopay activation for an opted-in payment checkout.

        Runs after the ledger bookkeeping, whose writes are idempotent, so it
        is safe for a failure here to fail the whole event: the worker retries
        the event with backoff and the replay re-runs only what didn't stick.
        Permanent metadata problems quarantine instead — retrying can't fix a
        malformed opt-in, but it should stay visible for manual replay.
        """
        metadata = checkout.get("metadata") or {}
        if not isinstance(metadata, dict) or str(metadata.get("autopay_optin") or "") != "true":
            return
        if self._complete_autopay_setup is None:
            log.warning(
                "autopay opt-in activation skipped: dependencies not configured session=%s",
                checkout.get("id"),
            )
            return
        try:
            await self._complete_autopay_setup.execute_from_payment_checkout(
                checkout,
                consent_context=AutopayConsentCaptureContext(source="stripe_webhook"),
                **_on_account_kwargs(stripe_account),
            )
        except (PaymentNotFound, ValueError) as exc:
            raise _QuarantineStripeEvent(str(exc)) from exc

    async def _handle_balance_checkout_completed(self, event: dict[str, Any]) -> None:
        """Handle checkout.session.completed for a parent balance payment."""
        if self._billing_ledger is None:
            log.warning("balance_checkout_completed: billing_ledger not configured - skipping")
            return

        obj = event["data"]["object"]
        checkout_session_id = str(obj.get("id") or "")
        metadata = obj.get("metadata") or {}
        if not isinstance(metadata, dict):
            metadata = {}
        raw_invoice_ids = str(metadata.get("invoice_ids") or "")
        invoice_ids = [item.strip() for item in raw_invoice_ids.split(",") if item.strip()]
        if not invoice_ids:
            log.warning(
                "balance_checkout_completed: no invoice_ids in metadata session=%s",
                checkout_session_id,
            )
            return

        payment_intent_id = obj.get("payment_intent") or None
        if payment_intent_id:
            payment_intent_id = str(payment_intent_id)
        amount_total = int(obj.get("amount_total") or 0)
        currency = str(obj.get("currency") or "usd").lower()
        parent_id = str(metadata.get("parent_id") or "unknown")
        now = self._now()
        ledger_payment_id = f"ledger-pay-cs:{checkout_session_id}"

        # Validate every target invoice (existence, academy, parent, currency) BEFORE
        # recording any payment, so a spoofed or cross-tenant event is quarantined without
        # first writing a ledger payment. (Matches the autopay handler's ordering.)
        invoices: list[LedgerInvoice] = []
        for invoice_id in sorted(invoice_ids):
            invoice = await self._billing_ledger.get_invoice(invoice_id)
            if invoice is None:
                raise ValueError(f"balance invoice {invoice_id!r} not found")
            if invoice.academy_id != self._academy_id:
                raise _QuarantineStripeEvent(
                    f"academy mismatch: invoice={invoice.academy_id} expected={self._academy_id}"
                )
            if invoice.parent_id != parent_id:
                raise _QuarantineStripeEvent(
                    f"parent mismatch: invoice={invoice.parent_id} checkout={parent_id}"
                )
            if currency != invoice.currency.lower():
                raise _QuarantineStripeEvent(
                    f"currency mismatch: invoice={invoice.currency} checkout={currency}"
                )
            invoices.append(invoice)

        if not _checkout_session_is_settled(obj):
            await self._record_unsettled_checkout_attempt(
                event=event,
                checkout_session_id=checkout_session_id,
                invoice_ids=invoice_ids,
                parent_id=parent_id,
                amount_cents=amount_total,
                currency=currency,
                payment_intent_id=payment_intent_id,
            )
            await self._maybe_activate_autopay_optin(obj, stripe_account=_event_account(event))
            return

        if await self._payment_intent_already_credited(
            payment_intent_id=payment_intent_id,
            ledger_payment_id=ledger_payment_id,
        ):
            return

        payment = await self._billing_ledger.record_payment(
            LedgerPayment(
                payment_id=ledger_payment_id,
                academy_id=self._academy_id,
                parent_id=parent_id,
                amount_cents=amount_total,
                unapplied_amount_cents=amount_total,
                currency=currency,
                status="succeeded",
                payment_method="stripe_checkout",
                stripe_payment_intent_id=payment_intent_id,
                stripe_account_id=_event_account(event),
                application_fee_cents=_application_fee_cents(obj),
                paid_at=now,
                created_at=now,
                updated_at=now,
            ),
            idempotency_key=f"invoice-checkout:{checkout_session_id}",
        )

        allocated = await allocate_checkout_payment_across_invoices(
            ledger=self._billing_ledger,
            payment=payment,
            invoices=invoices,
            amount_cents=amount_total,
            allocation_key_prefix=f"invoice-checkout-alloc:{checkout_session_id}",
            conflict_error=_QuarantineStripeEvent,
        )
        log.info(
            "balance_checkout_completed: allocated payment=%s invoices=%d",
            payment.payment_id,
            allocated,
        )
        await self._request_receipt(payment=payment, invoice=None, autopay=False, bank_debit=False)

        await self._maybe_activate_autopay_optin(obj, stripe_account=_event_account(event))

    async def _payment_intent_already_credited(
        self,
        *,
        payment_intent_id: str | None,
        ledger_payment_id: str,
    ) -> bool:
        """True when another path already recorded a ledger payment for this PI.

        Delayed settlement leaves days between ``checkout.session.completed`` and
        ``async_payment_succeeded``, and the scheduled PaymentIntent
        reconciliation repairs a missed webhook the moment the PI reads
        ``succeeded``. Without this check the later webhook would record a second
        ledger payment under its own session-keyed id and try to allocate it
        again, leaving either a double credit or a permanently failing event and
        an unapplied phantom payment. The reconciler makes the mirror-image check.
        """
        if self._billing_ledger is None or not payment_intent_id:
            return False
        existing = await self._billing_ledger.get_payment_by_stripe_payment_intent_id(
            payment_intent_id
        )
        if existing is None or existing.payment_id == ledger_payment_id:
            return False
        log.info(
            "checkout_payment_already_credited: pi=%s credited as payment=%s - skipping %s",
            payment_intent_id,
            existing.payment_id,
            ledger_payment_id,
        )
        return True

    async def _async_failure_detail(
        self, payment_intent_id: str | None, *, stripe_account: str | None = None
    ) -> tuple[str, str]:
        """Failure code/message for a Checkout session whose async payment failed.

        The session object carries no ``last_payment_error``, so read it off the
        PaymentIntent: the ``payment_intent.payment_failed`` handler writes the
        same attempt row (shared idempotency key) and whichever event lands first
        should record the same real reason, not a generic placeholder.
        """
        fallback = ("async_payment_failed", "Checkout payment did not settle.")
        if not payment_intent_id:
            return fallback
        try:
            pi = await self._stripe.retrieve_payment_intent(
                payment_intent_id, **_on_account_kwargs(stripe_account)
            )
        except Exception as exc:  # detail is best-effort; never fail the event over it
            log.warning(
                "checkout_async_payment_failed: could not read pi=%s for failure detail: %s",
                payment_intent_id,
                exc,
            )
            return fallback
        last_error = pi.get("last_payment_error") or {}
        if not isinstance(last_error, dict):
            return fallback
        code = str(last_error.get("decline_code") or last_error.get("code") or "")
        message = str(last_error.get("message") or "")
        if not code and not message:
            return fallback
        return (code or fallback[0], message or fallback[1])

    async def _checkout_attempt_shares(
        self,
        *,
        invoice_ids: list[str],
        amount_cents: int,
    ) -> list[tuple[str, int]]:
        """Split a Checkout total across its invoices the way allocation would.

        Mirrors ``allocate_checkout_payment_across_invoices`` (sorted by invoice
        id, filling each balance in turn) so an attempt row shows the amount that
        invoice actually had riding on the session.
        """
        if self._billing_ledger is None:
            return []
        if len(invoice_ids) == 1:
            return [(invoice_ids[0], amount_cents)]
        shares: list[tuple[str, int]] = []
        remaining = amount_cents
        for invoice_id in sorted(invoice_ids):
            if remaining <= 0:
                break
            invoice = await self._billing_ledger.get_invoice(invoice_id)
            balance = max(invoice.balance_due_cents, 0) if invoice is not None else 0
            share = min(remaining, balance)
            if share <= 0:
                continue
            shares.append((invoice_id, share))
            remaining -= share
        return shares

    async def _record_unsettled_checkout_attempt(
        self,
        *,
        event: dict[str, Any],
        checkout_session_id: str,
        invoice_ids: list[str],
        parent_id: str,
        amount_cents: int,
        currency: str,
        payment_intent_id: str | None,
    ) -> None:
        """Park an unsettled Checkout session as in-flight, without allocating.

        Same shape as the autopay ACH path (``_handle_autopay_pi_processing``):
        a ``processing`` attempt gives admins and reconciliation visibility while
        the invoice stays open and dunning keeps running, until the money is
        really there. Keyed by checkout session so replays converge on one row.
        """
        if self._billing_ledger is None:
            return
        event_id = str(event.get("id") or "")
        for invoice_id, share_cents in await self._checkout_attempt_shares(
            invoice_ids=invoice_ids,
            amount_cents=amount_cents,
        ):
            await self._billing_ledger.record_payment_attempt(
                invoice_id=invoice_id,
                parent_id=parent_id,
                amount_cents=share_cents,
                currency=currency,
                status="processing",
                stripe_payment_intent_id=payment_intent_id,
                stripe_checkout_session_id=checkout_session_id or None,
                failure_code=None,
                failure_message="Checkout payment submitted; awaiting settlement.",
                idempotency_key=(
                    f"invoice-checkout-processing:{invoice_id}:{checkout_session_id or event_id}"
                ),
                created_by_event_id=event_id or None,
            )
        log.info(
            "checkout_unsettled: recorded processing attempts session=%s invoices=%d "
            "- no ledger payment or allocation until settlement",
            checkout_session_id,
            len(invoice_ids),
        )

    async def _handle_checkout_async_payment_failed(self, event: dict[str, Any]) -> None:
        """Handle checkout.session.async_payment_failed (the ACH debit never settled).

        An unsettled session never produced a LedgerPayment, so there is nothing
        to reverse: record the failed attempt per target invoice and leave the
        invoice open and payable. Stripe also emits ``payment_intent.payment_failed``
        for the same PaymentIntent; both paths share the
        ``invoice-checkout-failed:{invoice_id}:{pi_id}`` idempotency key so the
        invoice ends up with one failure row, not two.
        """
        if self._billing_ledger is None:
            log.warning("checkout_async_payment_failed: billing_ledger not configured - skipping")
            return

        obj = event["data"]["object"]
        event_id = str(event.get("id") or "")
        checkout_session_id = str(obj.get("id") or "")
        metadata = obj.get("metadata") or {}
        if not isinstance(metadata, dict):
            metadata = {}
        invoice_ids = _checkout_invoice_ids(metadata)
        if not invoice_ids:
            log.warning(
                "checkout_async_payment_failed: no invoice ids in metadata session=%s",
                checkout_session_id,
            )
            return

        payment_intent_id = obj.get("payment_intent") or None
        if payment_intent_id:
            payment_intent_id = str(payment_intent_id)
        amount_total = int(obj.get("amount_total") or 0)
        currency = str(obj.get("currency") or "usd").lower()
        parent_id = str(metadata.get("parent_id") or "unknown")
        failure_code, failure_message = await self._async_failure_detail(
            payment_intent_id, stripe_account=_event_account(event)
        )

        for invoice_id, share_cents in await self._checkout_attempt_shares(
            invoice_ids=invoice_ids,
            amount_cents=amount_total,
        ):
            await self._billing_ledger.record_payment_attempt(
                invoice_id=invoice_id,
                parent_id=parent_id,
                amount_cents=share_cents,
                currency=currency,
                status="failed",
                stripe_payment_intent_id=payment_intent_id,
                stripe_checkout_session_id=checkout_session_id or None,
                failure_code=failure_code,
                failure_message=failure_message,
                idempotency_key=(
                    f"invoice-checkout-failed:{invoice_id}:"
                    f"{payment_intent_id or checkout_session_id or event_id}"
                ),
                created_by_event_id=event_id or None,
            )
        log.warning(
            "checkout_async_payment_failed: recorded failed attempts session=%s invoices=%d "
            "code=%s - invoice status unchanged",
            checkout_session_id,
            len(invoice_ids),
            failure_code,
        )

    async def _on_checkout_completed(self, event: dict[str, Any]) -> None:
        obj = event["data"]["object"]
        checkout_id = obj["id"]
        payment = await self._payments.get_by_checkout_session(checkout_id)
        subscription = await self._sync_subscription_from_checkout(obj)
        await self._persist_checkout_customer(
            obj,
            payment=payment,
            subscription=subscription,
            stripe_account=_event_account(event),
        )
        if payment is None:
            log.warning("checkout.completed for unknown checkout_id=%s", checkout_id)
            return
        if payment.status == "succeeded":
            return  # already processed
        updated = payment.model_copy(
            update={
                "status": "succeeded",
                "stripe_payment_intent_id": obj.get("payment_intent"),
                # The account the charge settled on (None = platform), so a
                # refund is later issued on the same account.
                "stripe_account_id": _event_account(event) or payment.stripe_account_id,
                "updated_at": self._now(),
            }
        )
        await self._payments.save(updated)
        await self._outbox.append(
            PaymentSucceeded(
                aggregate_id=updated.payment_id,
                academy_id=updated.academy_id,
                payload=PaymentSucceededPayload(
                    payment_id=updated.payment_id,
                    parent_id=updated.parent_id,
                    session_id=updated.session_id,
                    amount_cents=updated.amount_cents,
                    currency=updated.currency,
                    succeeded_at=updated.updated_at,
                ),
            )
        )

    async def _persist_checkout_customer(
        self,
        checkout: dict[str, Any],
        *,
        payment: Payment | None,
        subscription: Any | None,
        stripe_account: str | None = None,
    ) -> None:
        """Record the checkout's customer on the account the checkout ran on
        (``stripe_account``; None = the platform)."""
        if self._parent_customers is None:
            return
        stripe_customer_id = str(checkout.get("customer") or "")
        if not stripe_customer_id:
            return
        if payment is None and subscription is None:
            log.warning(
                "checkout.completed customer ignored without tenant-owned mapping checkout_id=%s",
                checkout.get("id"),
            )
            return
        parent_id = payment.parent_id if payment is not None else subscription.parent_id
        if not parent_id:
            log.warning(
                "checkout.completed customer present without parent_id checkout_id=%s",
                checkout.get("id"),
            )
            return
        await self._parent_customers.set_stripe_customer_id(
            parent_id=parent_id,
            stripe_customer_id=stripe_customer_id,
            **({"stripe_account_id": stripe_account} if stripe_account else {}),
        )

    async def _sync_subscription_from_checkout(self, checkout: dict[str, Any]) -> Any | None:
        """Backfill the Stripe subscription id captured only after Checkout
        completes (it is null at session-creation time) and activate both the
        subscription row and the enrollment's autopay state. Without this,
        enrollments stay at subscription_status="incomplete" forever and
        subscription webhooks can't find the row by stripe_subscription_id.
        """
        stripe_sub_id = str(checkout.get("subscription") or "")
        if not stripe_sub_id:
            return None
        metadata = checkout.get("metadata")
        enrollment_id: str | None = None
        internal_sub_id: str | None = None
        if isinstance(metadata, dict):
            if metadata.get("enrollment_id"):
                enrollment_id = str(metadata["enrollment_id"])
            if metadata.get("app_subscription_id"):
                internal_sub_id = str(metadata["app_subscription_id"])
            if metadata.get("subscription_id"):
                internal_sub_id = internal_sub_id or str(metadata["subscription_id"])
        # Prefer the pending row this exact checkout created (its internal id
        # rides in the session metadata). A parent can start checkout several
        # times for one enrollment, so latest_for_enrollment may point at a
        # different pending row and is only a last-resort fallback.
        subscription = None
        if internal_sub_id:
            subscription = await self._subscriptions.get(internal_sub_id)
        if subscription is None:
            subscription = await self._subscriptions.get_by_stripe_sub(stripe_sub_id)
        if subscription is None:
            checkout_id = str(checkout.get("id") or "")
            if checkout_id:
                subscription = await self._subscriptions.get_by_checkout_session(checkout_id)
        if subscription is None and enrollment_id:
            subscription = await self._subscriptions.latest_for_enrollment(enrollment_id)
        if subscription is not None:
            updated = subscription.model_copy(
                update={
                    "stripe_subscription_id": stripe_sub_id,
                    "stripe_checkout_session_id": str(checkout.get("id") or "")
                    or subscription.stripe_checkout_session_id,
                    "status": "active",
                    "updated_at": self._now(),
                }
            )
            await self._subscriptions.save(updated)
            enrollment_id = enrollment_id or updated.enrollment_id
        else:
            log.warning(
                "checkout.completed subscription ignored without tenant-owned subscription checkout_id=%s",
                checkout.get("id"),
            )
            return None
        if self._enrollment_autopay is not None and enrollment_id:
            await self._enrollment_autopay.mark_autopay_active_from_setup(
                enrollment_id=enrollment_id,
            )
        return updated

    @staticmethod
    def _checkout_parent_id(checkout: dict[str, Any]) -> str | None:
        metadata = checkout.get("metadata")
        if isinstance(metadata, dict):
            parent_id = metadata.get("parent_id")
            if parent_id:
                return str(parent_id)
        client_reference_id = checkout.get("client_reference_id")
        if client_reference_id:
            return str(client_reference_id)
        return None

    async def _on_checkout_expired(self, event: dict[str, Any]) -> None:
        obj = event["data"]["object"]
        checkout_id = obj["id"]
        payment = await self._payments.get_by_checkout_session(checkout_id)
        if payment is None or payment.status not in ("pending",):
            return
        updated = payment.model_copy(update={"status": "expired", "updated_at": self._now()})
        await self._payments.save(updated)
        await self._outbox.append(
            CheckoutExpired(
                aggregate_id=updated.payment_id,
                academy_id=updated.academy_id,
                payload=CheckoutExpiredPayload(
                    payment_id=updated.payment_id,
                    parent_id=updated.parent_id,
                    session_id=updated.session_id,
                ),
            )
        )

    async def _handle_autopay_pi_succeeded(self, event: dict[str, Any]) -> None:
        """Handle payment_intent.succeeded from an autopay charge.

        Idempotent by pi_id via idempotency_key ``autopay-pi:{pi_id}``.
        Records a LedgerPayment and allocates it to the invoice.
        """
        if self._billing_ledger is None:
            log.warning("autopay_pi_succeeded: billing_ledger not configured — skipping")
            return

        pi = event["data"]["object"]
        pi_id: str = str(pi.get("id") or "")
        metadata = pi.get("metadata") or {}
        invoice_id = str(metadata.get("invoice_id") or "")

        if not invoice_id:
            log.warning("autopay_pi_succeeded: no invoice_id in metadata pi=%s", pi_id)
            return

        invoice = await self._billing_ledger.get_invoice(invoice_id)
        if invoice is None:
            raise ValueError("autopay invoice not found")
        if invoice.academy_id != self._academy_id:
            raise _QuarantineStripeEvent(
                f"academy mismatch: invoice={invoice.academy_id} expected={self._academy_id}"
            )
        metadata_parent_id = str(metadata.get("parent_id") or "")
        if metadata_parent_id and metadata_parent_id != invoice.parent_id:
            raise _QuarantineStripeEvent(
                f"parent mismatch: invoice={invoice.parent_id} payment_intent={metadata_parent_id}"
            )

        amount_cents = int(pi.get("amount") or 0)
        if amount_cents <= 0:
            raise ValueError("autopay payment_intent missing positive amount")
        currency = str(pi.get("currency") or invoice.currency).lower()
        if currency != invoice.currency.lower():
            raise ValueError("autopay payment_intent currency does not match invoice")
        now = self._now()
        idempotency_key = f"autopay-pi:{pi_id}"
        ledger_payment_id = f"ledger-pay-autopay:{pi_id}"
        payment_metadata = await self._autopay_discount_payment_metadata(
            pi_metadata=metadata,
            invoice_id=invoice_id,
        )

        payment = await self._billing_ledger.record_payment(
            LedgerPayment(
                payment_id=ledger_payment_id,
                academy_id=invoice.academy_id,
                parent_id=invoice.parent_id,
                amount_cents=amount_cents,
                unapplied_amount_cents=amount_cents,
                currency=currency,
                status="succeeded",
                payment_method="stripe_autopay",
                stripe_payment_intent_id=pi_id,
                stripe_account_id=_event_account(event),
                application_fee_cents=_application_fee_cents(pi),
                paid_at=now,
                metadata=payment_metadata or None,
                created_at=now,
                updated_at=now,
            ),
            idempotency_key=idempotency_key,
        )

        if amount_cents > 0:
            allocation = await self._billing_ledger.allocate_payment(
                payment_id=payment.payment_id,
                invoice_id=invoice_id,
                amount_cents=amount_cents,
                idempotency_key=f"autopay-alloc:{pi_id}",
            )
            credit = getattr(allocation, "overpayment_credit", None)
            if credit is not None:
                # ACH settled after another path (e.g. an admin manual payment)
                # already covered the invoice: the surplus became an account
                # credit instead of stranding as an unapplied payment (#533).
                log.warning(
                    "autopay_pi_succeeded: invoice=%s already (partially) paid — "
                    "minted overpayment credit=%s cents=%d pi=%s",
                    invoice_id,
                    credit.credit_id,
                    credit.amount_cents,
                    pi_id,
                )
            log.info(
                "autopay_pi_succeeded: allocated payment=%s to invoice=%s pi=%s amount=%d",
                payment.payment_id,
                invoice_id,
                pi_id,
                amount_cents,
            )
        await self._request_receipt(
            payment=payment,
            invoice=invoice,
            autopay=True,
            bank_debit=_payment_intent_is_ach(pi)
            or (payment.metadata or {}).get("funding_type") == "us_bank_account",
        )

    async def _autopay_discount_payment_metadata(
        self,
        *,
        pi_metadata: dict[str, Any],
        invoice_id: str,
    ) -> dict[str, str]:
        metadata = _autopay_discount_metadata_from_pi(pi_metadata)
        metadata.setdefault("invoice_id", invoice_id)
        get_lines = getattr(self._billing_ledger, "get_lines_for_invoice", None)
        if callable(get_lines):
            lines = await get_lines(invoice_id)
            discount_line = next(
                (line for line in lines if getattr(line, "line_type", None) == "ach_discount"),
                None,
            )
            if discount_line is not None:
                metadata.setdefault("ach_discount_line_id", str(discount_line.line_id))
                metadata.setdefault("ach_discount_cents", str(abs(discount_line.amount_cents)))
                if getattr(discount_line, "source_id", None):
                    metadata.setdefault("disclosure_version", str(discount_line.source_id))
        return metadata

    async def _handle_autopay_pi_processing(self, event: dict[str, Any]) -> None:
        """Handle payment_intent.processing from an ACH autopay debit.

        ACH processing is a known in-flight state. Record an attempt for
        reconciliation/admin visibility, but do not create a LedgerPayment or
        allocate the invoice until Stripe emits payment_intent.succeeded.
        """
        if self._billing_ledger is None:
            log.warning("autopay_pi_processing: billing_ledger not configured — skipping")
            return

        pi = event["data"]["object"]
        event_id = str(event.get("id") or "")
        pi_id = str(pi.get("id") or "")
        metadata = pi.get("metadata") or {}
        invoice_id = str(metadata.get("invoice_id") or "")
        if not invoice_id:
            log.warning("autopay_pi_processing: no invoice_id in metadata pi=%s", pi_id)
            return

        invoice = await self._billing_ledger.get_invoice(invoice_id)
        if invoice is None:
            raise ValueError("autopay invoice not found")
        if invoice.academy_id != self._academy_id:
            raise _QuarantineStripeEvent(
                f"academy mismatch: invoice={invoice.academy_id} expected={self._academy_id}"
            )
        metadata_parent_id = str(metadata.get("parent_id") or "")
        if metadata_parent_id and metadata_parent_id != invoice.parent_id:
            raise _QuarantineStripeEvent(
                f"parent mismatch: invoice={invoice.parent_id} payment_intent={metadata_parent_id}"
            )

        amount_cents = int(pi.get("amount") or invoice.balance_due_cents or invoice.total_cents)
        currency = str(pi.get("currency") or invoice.currency).lower()
        await self._billing_ledger.record_payment_attempt(
            invoice_id=invoice_id,
            parent_id=invoice.parent_id,
            amount_cents=amount_cents,
            currency=currency,
            status="processing",
            stripe_payment_intent_id=pi_id or None,
            stripe_checkout_session_id=None,
            failure_code=None,
            failure_message="ACH debit submitted; awaiting settlement.",
            idempotency_key=f"autopay-processing:{invoice_id}:{pi_id or event_id}",
            created_by_event_id=event_id or None,
        )
        log.info(
            "autopay_pi_processing: recorded processing attempt pi=%s invoice=%s",
            pi_id,
            invoice_id,
        )

    async def _handle_autopay_pi_failed(self, event: dict[str, Any]) -> None:
        """Handle payment_intent.payment_failed from an autopay charge.

        Per spec: record the failed attempt, but do NOT change invoice status.
        """
        if self._billing_ledger is None:
            log.warning("autopay_pi_failed: billing_ledger not configured — skipping")
            return

        pi = event["data"]["object"]
        event_id = str(event.get("id") or "")
        pi_id: str = str(pi.get("id") or "")
        metadata = pi.get("metadata") or {}
        invoice_id = str(metadata.get("invoice_id") or "")
        if not invoice_id:
            log.warning("autopay_pi_failed: no invoice_id in metadata pi=%s", pi_id)
            return

        invoice = await self._billing_ledger.get_invoice(invoice_id)
        if invoice is None:
            raise ValueError("autopay invoice not found")
        if invoice.academy_id != self._academy_id:
            raise _QuarantineStripeEvent(
                f"academy mismatch: invoice={invoice.academy_id} expected={self._academy_id}"
            )
        metadata_parent_id = str(metadata.get("parent_id") or "")
        if metadata_parent_id and metadata_parent_id != invoice.parent_id:
            raise _QuarantineStripeEvent(
                f"parent mismatch: invoice={invoice.parent_id} payment_intent={metadata_parent_id}"
            )

        return_code = _ach_return_code_from_stripe_payment_intent(pi)
        existing_payment = await self._billing_ledger.get_payment_by_stripe_payment_intent_id(pi_id)
        if (
            return_code is not None
            and existing_payment is not None
            and existing_payment.status in {"succeeded", "partially_refunded", "refunded"}
            and (_ledger_payment_is_ach(existing_payment) or _payment_intent_is_ach(pi))
        ):
            amount_cents = int(pi.get("amount") or existing_payment.amount_cents)
            await self._reverse_returned_payment(
                event_id=event_id,
                pi_id=pi_id,
                payment=existing_payment,
                amount_cents=amount_cents,
                return_code=return_code,
                source_key=f"pi-return:{pi_id}",
            )
            return

        last_error = pi.get("last_payment_error") or {}
        if not isinstance(last_error, dict):
            last_error = {}
        decline_code = str(last_error.get("decline_code") or last_error.get("code") or "unknown")
        failure_message = str(last_error.get("message") or "Payment failed")
        amount_cents = int(pi.get("amount") or invoice.balance_due_cents or invoice.total_cents)
        currency = str(pi.get("currency") or invoice.currency).lower()
        await self._billing_ledger.record_payment_attempt(
            invoice_id=invoice_id,
            parent_id=invoice.parent_id,
            amount_cents=amount_cents,
            currency=currency,
            status="failed",
            stripe_payment_intent_id=pi_id or None,
            stripe_checkout_session_id=None,
            failure_code=decline_code,
            failure_message=failure_message,
            idempotency_key=f"autopay-failed:{invoice_id}:{pi_id or event_id}",
            created_by_event_id=event_id or None,
        )
        log.warning(
            "autopay_pi_failed: recorded attempt pi=%s invoice=%s decline_code=%s — invoice status unchanged",
            pi_id,
            invoice_id,
            decline_code,
        )

    async def _handle_invoice_checkout_payment_failed(self, event: dict[str, Any]) -> bool:
        """Record a failed manual invoice Checkout attempt without closing the invoice."""
        if self._billing_ledger is None:
            return False

        event_id = str(event.get("id") or "")
        pi = event["data"]["object"]
        pi_id = str(pi.get("id") or "")
        checkout_session_id = _checkout_session_id_from_payment_intent(pi)
        if not checkout_session_id:
            return False

        # The session lives on the same account as the PaymentIntent the
        # event names (the connected account for a direct charge).
        checkout = await self._stripe.retrieve_checkout_session(
            checkout_session_id, **_on_account_kwargs(_event_account(event))
        )
        metadata = checkout.get("metadata") or {}
        if not isinstance(metadata, dict):
            metadata = {}
        invoice_id = str(metadata.get("invoice_id") or "")
        if metadata.get("source") != "invoice_pay_link" and not invoice_id:
            return False
        if not invoice_id:
            log.warning(
                "invoice_checkout_payment_failed: no invoice_id session=%s pi=%s",
                checkout_session_id,
                pi_id,
            )
            return True

        last_error = pi.get("last_payment_error") or {}
        if not isinstance(last_error, dict):
            last_error = {}
        failure_code = str(last_error.get("decline_code") or last_error.get("code") or "unknown")
        failure_message = str(last_error.get("message") or "Payment failed")
        amount_cents = int(pi.get("amount") or checkout.get("amount_total") or 0)
        currency = str(pi.get("currency") or checkout.get("currency") or "usd").lower()
        await self._billing_ledger.record_payment_attempt(
            invoice_id=invoice_id,
            parent_id=str(metadata.get("parent_id") or "unknown"),
            amount_cents=amount_cents,
            currency=currency,
            status="failed",
            stripe_payment_intent_id=pi_id or None,
            stripe_checkout_session_id=checkout_session_id,
            failure_code=failure_code,
            failure_message=failure_message,
            idempotency_key=f"invoice-checkout-failed:{invoice_id}:{pi_id or event_id}",
            created_by_event_id=event_id or None,
        )
        log.warning(
            "invoice_checkout_payment_failed: recorded attempt invoice=%s pi=%s code=%s",
            invoice_id,
            pi_id,
            failure_code,
        )
        return True

    async def _on_payment_failed(self, event: dict[str, Any]) -> None:
        pi = event["data"]["object"]
        pi_id = pi["id"]
        payment = await self._payments.get_by_stripe_pi(pi_id)
        if payment is None:
            return
        updated = payment.model_copy(update={"status": "failed", "updated_at": self._now()})
        await self._payments.save(updated)
        await self._outbox.append(
            PaymentFailed(
                aggregate_id=updated.payment_id,
                academy_id=updated.academy_id,
                payload=PaymentFailedPayload(
                    payment_id=updated.payment_id,
                    parent_id=updated.parent_id,
                    session_id=updated.session_id,
                    reason=str(pi.get("last_payment_error", {}).get("message", "unknown")),
                ),
            )
        )

    async def _on_payment_succeeded(self, event: dict[str, Any]) -> None:
        pi = event["data"]["object"]
        pi_id = pi["id"]
        payment = await self._payments.get_by_stripe_pi(pi_id)
        if payment is None:
            return
        if payment.status == "succeeded":
            return
        updated = payment.model_copy(
            update={
                "status": "succeeded",
                "stripe_account_id": _event_account(event) or payment.stripe_account_id,
                "updated_at": self._now(),
            }
        )
        await self._payments.save(updated)
        await self._outbox.append(
            PaymentSucceeded(
                aggregate_id=updated.payment_id,
                academy_id=updated.academy_id,
                payload=PaymentSucceededPayload(
                    payment_id=updated.payment_id,
                    parent_id=updated.parent_id,
                    session_id=updated.session_id,
                    amount_cents=updated.amount_cents,
                    currency=updated.currency,
                    succeeded_at=updated.updated_at,
                ),
            )
        )

    async def _on_invoice_paid(self, event: dict[str, Any]) -> None:
        invoice = event["data"]["object"]
        if await self._handle_session_type_invoice(invoice, paid=True):
            return
        subscription = await self._subscription_from_invoice(invoice)
        if subscription is None:
            return
        event_id = str(event.get("id") or "")
        await self._record_subscription_invoice_recovery_point(
            invoice,
            subscription=subscription,
            event_id=event_id,
            recovery_point="subscription_resolved",
        )
        try:
            await self._sync_subscription_invoice_ledger(
                invoice,
                subscription=subscription,
                paid=True,
                event_id=event_id,
            )
        except _QuarantineStripeEvent as exc:
            await self._record_subscription_invoice_recovery_point(
                invoice,
                subscription=subscription,
                event_id=event_id,
                recovery_point="quarantined",
                last_error=str(exc),
            )
            raise
        payment = await self._payment_from_invoice(
            invoice,
            status="succeeded",
            subscription=subscription,
        )
        if payment is None:
            await self._record_subscription_invoice_recovery_point(
                invoice,
                subscription=subscription,
                event_id=event_id,
                recovery_point="processed",
            )
            return
        await self._payments.save(payment)
        await self._record_subscription_invoice_recovery_point(
            invoice,
            subscription=subscription,
            event_id=event_id,
            recovery_point="legacy_projection_saved",
            legacy_payment_id=payment.payment_id,
        )
        await self._outbox.append(
            PaymentSucceeded(
                aggregate_id=payment.payment_id,
                academy_id=payment.academy_id,
                payload=PaymentSucceededPayload(
                    payment_id=payment.payment_id,
                    parent_id=payment.parent_id,
                    session_id=payment.session_id,
                    amount_cents=payment.amount_cents,
                    currency=payment.currency,
                    succeeded_at=payment.updated_at,
                ),
            )
        )
        await self._record_subscription_invoice_recovery_point(
            invoice,
            subscription=subscription,
            event_id=event_id,
            recovery_point="processed",
            legacy_payment_id=payment.payment_id,
        )

    async def _on_invoice_payment_failed(self, event: dict[str, Any]) -> None:
        invoice = event["data"]["object"]
        if await self._handle_session_type_invoice(invoice, paid=False):
            return
        subscription = await self._subscription_from_invoice(invoice)
        if subscription is None:
            return
        event_id = str(event.get("id") or "")
        await self._record_subscription_invoice_recovery_point(
            invoice,
            subscription=subscription,
            event_id=event_id,
            recovery_point="subscription_resolved",
        )
        try:
            await self._sync_subscription_invoice_ledger(
                invoice,
                subscription=subscription,
                paid=False,
                event_id=event_id,
            )
        except _QuarantineStripeEvent as exc:
            await self._record_subscription_invoice_recovery_point(
                invoice,
                subscription=subscription,
                event_id=event_id,
                recovery_point="quarantined",
                last_error=str(exc),
            )
            raise
        payment = await self._payment_from_invoice(
            invoice, status="failed", subscription=subscription
        )
        if payment is None:
            await self._record_subscription_invoice_recovery_point(
                invoice,
                subscription=subscription,
                event_id=event_id,
                recovery_point="processed",
            )
            return
        await self._payments.save(payment)
        await self._record_subscription_invoice_recovery_point(
            invoice,
            subscription=subscription,
            event_id=event_id,
            recovery_point="legacy_projection_saved",
            legacy_payment_id=payment.payment_id,
        )
        await self._outbox.append(
            PaymentFailed(
                aggregate_id=payment.payment_id,
                academy_id=payment.academy_id,
                payload=PaymentFailedPayload(
                    payment_id=payment.payment_id,
                    parent_id=payment.parent_id,
                    session_id=payment.session_id,
                    reason=str(
                        invoice.get("last_finalization_error", {}).get(
                            "message", "invoice payment failed"
                        )
                    ),
                ),
            )
        )
        await self._record_subscription_invoice_recovery_point(
            invoice,
            subscription=subscription,
            event_id=event_id,
            recovery_point="processed",
            legacy_payment_id=payment.payment_id,
        )

    async def _on_charge_dispute(self, event: dict[str, Any]) -> None:
        """``charge.dispute.created`` / ``charge.dispute.closed``.

        On a direct charge the dispute arrives as a Connect event (``account``
        = the academy's connected account, already verified to belong to this
        academy by the processing guard); a house-academy dispute is a
        platform event. Either way it is recorded, mirrored onto the payment
        and the owner is notified, with no money moved: the dispute is the
        academy's to answer, and Stripe (not the platform) debits its account.
        """
        if self._record_dispute is None:
            log.warning(
                "charge_dispute: dispute store not configured; event %s not recorded",
                event.get("id"),
            )
            return
        obj = event.get("data", {}).get("object", {})
        if not isinstance(obj, dict):
            return
        try:
            await self._record_dispute.execute(obj, stripe_account_id=_event_account(event))
        except StripeAccountMismatch as exc:
            raise _QuarantineStripeEvent(str(exc)) from exc
        await self._reverse_paid_invoice_on_dispute(event, obj)

    async def _on_refund_failed(self, event: dict[str, Any]) -> None:
        """A refund that failed (closed bank, expired card) left the money in the
        Stripe balance; flag it for the owner on Billing Health (A4-8)."""
        if self._billing_ledger is None:
            return
        refund = event.get("data", {}).get("object", {})
        if not isinstance(refund, dict) or refund.get("status") != "failed":
            return
        pi_id = str(refund.get("payment_intent") or "")
        refund_id = str(refund.get("id") or "")
        if not pi_id or not refund_id:
            return
        matched = await self._billing_ledger.record_refund_failure(
            stripe_payment_intent_id=pi_id,
            refund_id=refund_id,
            reason=str(refund.get("failure_reason") or "unknown"),
            amount_cents=int(refund.get("amount") or 0),
            failed_at=self._now(),
        )
        log.warning("refund_failed refund=%s pi=%s recorded=%s", refund_id, pi_id, matched)

    async def _on_payment_method_unusable(self, event: dict[str, Any]) -> None:
        """A revoked bank mandate or a bank account Stripe has blocked (closed,
        frozen) cannot be debited again. Flag the stored method so the next
        autopay run asks the parent for a new one instead of bouncing (A4-8)."""
        if self._parent_customers is None:
            return
        obj = event.get("data", {}).get("object", {})
        if not isinstance(obj, dict):
            return
        customer_id = str(obj.get("customer") or "")
        if event.get("type") == "mandate.updated":
            if obj.get("status") != "inactive":
                return
            payment_method_id, reason = str(obj.get("payment_method") or ""), "mandate_inactive"
            customer_id = await self._payment_method_customer(
                payment_method_id, stripe_account=event.get("account")
            )
        else:
            bank = obj.get("us_bank_account") or {}
            blocked = (
                (bank.get("status_details") or {}).get("blocked")
                if isinstance(bank, dict)
                else None
            )
            if not blocked:
                return
            payment_method_id = str(obj.get("id") or "")
            reason = (
                f"bank_blocked:{blocked.get('reason') or 'unknown'}"
                if isinstance(blocked, dict)
                else "bank_blocked"
            )
        if not payment_method_id:
            return
        flagged = await self._parent_customers.flag_payment_method_blocked(
            payment_method_id=payment_method_id,
            reason=reason,
            at=self._now(),
            stripe_customer_id=customer_id or None,
        )
        log.warning(
            "payment_method_unusable pm=%s reason=%s flagged=%d", payment_method_id, reason, flagged
        )

    async def _payment_method_customer(self, payment_method_id: str, *, stripe_account: Any) -> str:
        """The Stripe customer a method belongs to ("" when unknown). A mandate
        names only its method; the id match still runs if this lookup fails."""
        if not payment_method_id:
            return ""
        try:
            method = await self._stripe.retrieve_payment_method(
                payment_method_id, stripe_account=str(stripe_account or "") or None
            )
        except Exception:
            log.warning("payment_method_customer_lookup_failed pm=%s", payment_method_id)
            return ""
        return str((method or {}).get("customer") or "")

    async def _on_charge_refunded(self, event: dict[str, Any]) -> None:
        ch = event["data"]["object"]
        ch["_event_id"] = str(event.get("id") or "")
        pi_id = ch.get("payment_intent")
        if not pi_id:
            return
        payment = await self._payments.get_by_stripe_pi(pi_id)
        if payment is None:
            # Autopay / invoice pay-link / balance-checkout charges are recorded
            # only in the ledger (no legacy `payments` row), so fall back to the
            # ledger; otherwise the refund is silently dropped.
            await self._on_charge_refunded_ledger(str(pi_id), ch, event=event)
            return
        _require_same_account(
            event, payment.stripe_account_id, what=f"payment {payment.payment_id}"
        )
        total_refunded = int(ch.get("amount_refunded", 0))
        if total_refunded == 0 or total_refunded == payment.refunded_cents:
            return
        delta = max(0, total_refunded - payment.refunded_cents)
        new_status = "refunded" if total_refunded >= payment.amount_cents else "partially_refunded"
        updated = payment.model_copy(
            update={
                "status": new_status,
                "refunded_cents": total_refunded,
                "updated_at": self._now(),
            }
        )
        await self._payments.save(updated)
        await self._outbox.append(
            PaymentRefunded(
                aggregate_id=updated.payment_id,
                academy_id=updated.academy_id,
                payload=PaymentRefundedPayload(
                    payment_id=updated.payment_id,
                    refunded_cents=delta,
                    total_refunded_cents=total_refunded,
                    reason="admin_initiated",
                ),
            )
        )

    async def _on_charge_refunded_ledger(
        self, pi_id: str, ch: dict[str, Any], *, event: dict[str, Any] | None = None
    ) -> None:
        """Record a refund for a charge that exists only in the ledger.

        Autopay direct charges, invoice pay-link checkouts, and balance
        checkouts write a ``LedgerPayment`` (no legacy ``payments`` row), so the
        legacy lookup in ``_on_charge_refunded`` misses them. Mirrors the legacy
        refund semantics: cumulative-amount idempotency, partial vs full status,
        and a ``PaymentRefunded`` event. Allocations are not reversed (the
        payment did happen — unlike an ACH return), but the refund IS
        propagated to the allocated invoices' ``refunded_cents`` so invoice
        reporting matches the admin-initiated refund path.
        """
        if self._billing_ledger is None:
            return
        payment = await self._billing_ledger.get_payment_by_stripe_payment_intent_id(pi_id)
        if payment is None:
            return
        if event is not None:
            _require_same_account(
                event, payment.stripe_account_id, what=f"payment {payment.payment_id}"
            )
        total_refunded = int(ch.get("amount_refunded", 0))
        if total_refunded == 0:
            return
        return_code = _ach_return_code_from_stripe_charge(ch)
        if return_code is not None and (_ledger_payment_is_ach(payment) or _charge_is_ach(ch)):
            await self._reverse_returned_payment(
                event_id=str(ch.get("_event_id") or ""),
                pi_id=pi_id,
                payment=payment,
                amount_cents=total_refunded,
                return_code=return_code,
                source_key=None,  # amount_refunded is cumulative
            )
            return
        # Invoice-level sync runs FIRST: if it fails, the payment row is still
        # unmarked (delta > 0), so Stripe's redelivery retries the whole thing.
        # It is idempotent (cumulative targets, shortfall-only writes), so a
        # redelivery after success applies nothing.
        await self._sync_invoice_refunds_for_ledger_payment(
            pi_id=pi_id, payment=payment, total_refunded_cents=total_refunded
        )
        # ``amount_refunded`` is cumulative for the charge only; a keyed dispute
        # already on the total must not be overwritten by it (L8).
        updated, total_moved = await self._billing_ledger.apply_payment_return(
            payment.payment_id,
            amount_cents=total_refunded,
            source_key=None,
            updated_at=self._now(),
        )
        if not total_moved:
            return
        delta = updated.refunded_cents - payment.refunded_cents
        await self._outbox.append(
            PaymentRefunded(
                aggregate_id=updated.payment_id,
                academy_id=updated.academy_id,
                payload=PaymentRefundedPayload(
                    payment_id=updated.payment_id,
                    refunded_cents=delta,
                    total_refunded_cents=total_refunded,
                    reason="admin_initiated",
                ),
            )
        )

    async def _sync_invoice_refunds_for_ledger_payment(
        self,
        *,
        pi_id: str,
        payment: LedgerPayment,
        total_refunded_cents: int,
    ) -> None:
        """Bring allocated invoices' ``refunded_cents`` up to this payment's
        cumulative refund.

        The cumulative total is distributed across the payment's allocations in
        allocation order, capped per invoice by the amount THIS payment actually
        allocated to it — refunding a payment must never attribute another
        payment's funding as refunded. Only the shortfall versus the invoice's
        current ``refunded_cents`` is written, so the sync is idempotent across
        webhook re-deliveries. If an invoice already carries refunds from other
        payments, the shortfall shrinks — under-reporting is acceptable (and
        logged); over-refunding an invoice is not.
        """
        if total_refunded_cents <= 0:
            return
        allocations = await self._billing_ledger.list_allocations_for_payment(payment.payment_id)
        per_invoice: dict[str, int] = {}
        for allocation in allocations:
            invoice_id = str(_alloc_field(allocation, "invoice_id") or "")
            amount = int(_alloc_field(allocation, "amount_cents") or 0)
            if invoice_id and amount > 0:
                per_invoice[invoice_id] = per_invoice.get(invoice_id, 0) + amount
        if not per_invoice:
            fallback = await self._invoice_for_autopay_payment(pi_id=pi_id, payment=payment)
            if fallback is not None:
                per_invoice[fallback.invoice_id] = payment.amount_cents
        remaining = total_refunded_cents
        for invoice_id, allocated in per_invoice.items():
            if remaining <= 0:
                break
            target = min(remaining, allocated)
            remaining -= target
            invoice = await self._billing_ledger.get_invoice(invoice_id)
            if invoice is None:
                continue
            shortfall = min(target, invoice.total_cents) - invoice.refunded_cents
            if shortfall <= 0:
                continue
            await self._billing_ledger.apply_invoice_refund(
                invoice_id=invoice_id, amount_cents=shortfall
            )
        if remaining > 0:
            log.warning(
                "charge_refunded_ledger: %d cents of refund for payment %s (pi=%s) "
                "not attributable to any invoice (no allocation covers it)",
                remaining,
                payment.payment_id,
                pi_id,
            )

    async def _invoice_for_autopay_payment(
        self,
        *,
        pi_id: str,
        payment: LedgerPayment,
    ) -> LedgerInvoice | None:
        metadata = payment.metadata or {}
        invoice_id = str(metadata.get("invoice_id") or "")
        if not invoice_id:
            allocation = await self._billing_ledger.get_payment_allocation_by_idempotency_key(
                f"autopay-alloc:{pi_id}"
            )
            if allocation is not None:
                invoice_id = str(getattr(allocation, "invoice_id", "") or allocation["invoice_id"])
        if not invoice_id:
            return None
        return await self._billing_ledger.get_invoice(invoice_id)

    async def _reverse_returned_payment(
        self,
        *,
        event_id: str,
        pi_id: str,
        payment: LedgerPayment,
        amount_cents: int,
        return_code: str,
        source_key: str | None,
    ) -> None:
        """Money taken back after it settled: a late bank return, a bank dispute or a
        lost dispute (A4-5). Every invoice this payment settled reopens, whatever
        paid it (autopay, pay link, balance checkout), and the family's autopay
        pauses (owner 2026-11-15).

        Every step is idempotent and the payment is marked refunded LAST, so a
        replay after any failure redoes the remaining steps; a refunded payment
        means all of them ran (L1 B1). Notices go out before the reversal so a
        replay that finds the allocations gone has nothing left to tell.
        """
        if self._billing_ledger is None or payment.status == "refunded":
            return
        ledger = self._billing_ledger
        allocations = await ledger.list_allocations_for_payment(payment.payment_id)
        # Reversals this return already wrote: proof it ran, and the invoices it
        # touched, since a reversal deletes its allocation.
        reversal_prefix = f"payment-return:{pi_id}:"
        prior_reversals = [
            reversal
            for reversal in await ledger.list_reversals_for_payment(payment.payment_id)
            if str(reversal.get("idempotency_key") or "").startswith(reversal_prefix)
        ]
        allocated: dict[str, int] = {}
        for allocation in [*allocations, *prior_reversals]:
            invoice_id = str(_alloc_field(allocation, "invoice_id") or "")
            if invoice_id:
                allocated[invoice_id] = allocated.get(invoice_id, 0) + int(
                    _alloc_field(allocation, "amount_cents") or 0
                )
        if not allocated:
            fallback = await self._invoice_for_autopay_payment(pi_id=pi_id, payment=payment)
            if fallback is not None:
                allocated[fallback.invoice_id] = 0
        invoices = [
            invoice
            for invoice in [await ledger.get_invoice(invoice_id) for invoice_id in allocated]
            if invoice is not None
        ]
        dispute = return_code.startswith("dispute:")
        partial = amount_cents < payment.amount_cents
        # Nothing reversible and no proof a reversal ran (a legacy allocation
        # without a key, or an invoice found with no allocation): the payment must
        # not read "refunded" while that invoice may still read paid. With no
        # invoice at all the money was never applied, so it simply refunds.
        unreversible = any(
            not _alloc_field(allocation, "idempotency_key") for allocation in allocations
        ) or (not allocations and not prior_reversals and bool(invoices))
        await self._pause_family_after_return(payment=payment, pi_id=pi_id, code=return_code)
        if partial or unreversible:
            # shortcut: allocations reverse whole, so a partial return is not taken
            # off the invoices: autopay pauses, a failed attempt is recorded and ops
            # is alerted to reconcile by hand. Upgrade when partial reversal exists.
            failure_code = UNSUPPORTED_PARTIAL_RETURN if partial else UNRECONCILED_RETURN
            label = "Unsupported partial ACH return" if partial else "Unreconciled payment return"
            if invoices:
                invoice = invoices[0]
                await ledger.record_payment_attempt(
                    invoice_id=invoice.invoice_id,
                    parent_id=invoice.parent_id,
                    amount_cents=amount_cents,
                    currency=invoice.currency,
                    status="failed",
                    stripe_payment_intent_id=pi_id or None,
                    stripe_checkout_session_id=None,
                    failure_code=failure_code,
                    failure_message=(
                        f"{label} {return_code} for {amount_cents} of {payment.amount_cents} cents"
                    ),
                    idempotency_key=(
                        f"autopay-ach-return-unsupported-partial:"
                        f"{invoice.invoice_id}:{pi_id}:{return_code}:{amount_cents}"
                        if partial
                        else f"payment-return-unreconciled:{invoice.invoice_id}:{pi_id}:"
                        f"{return_code}:{amount_cents}"
                    ),
                    created_by_event_id=event_id or None,
                )
            elif partial:
                # Never applied to an invoice, so no attempt row can carry it. The
                # returned part must stop being spendable unapplied money; the
                # audit entry is the owner's trail (L8). The repo never lowers or
                # doubles the total: cumulative charge refunds merge, keyed sources add once.
                updated, _ = await ledger.apply_payment_return(
                    payment.payment_id,
                    amount_cents=amount_cents,
                    source_key=source_key,
                    updated_at=self._now(),
                )
                # Every pass: ``append`` ignores a duplicate deterministic audit_id,
                # so a retry after a failed audit write still leaves the trail.
                if self._billing_audit is not None:
                    await self._billing_audit.append(
                        BillingAuditEntry(
                            # One row per keyed source, or per cumulative total.
                            audit_id=(
                                f"baud-payment-return:{pi_id}:{source_key}"
                                if source_key
                                else f"baud-payment-return:{pi_id}:{return_code}:{amount_cents}"
                            ),
                            academy_id=payment.academy_id,
                            action="payment_return_unreconciled",
                            actor_id="system",
                            at=self._now(),
                            payment_id=payment.payment_id,
                            parent_id=payment.parent_id or None,
                            reason=f"{label} {return_code}: {amount_cents} cents",
                            before={"refunded_cents": payment.refunded_cents},
                            after={"refunded_cents": updated.refunded_cents},
                        )
                    )
            capture_message(
                f"{'Partial payment' if partial else 'Payment'} return not reversed: "
                f"pi={pi_id} {amount_cents} of {payment.amount_cents} cents ({return_code}); "
                "reconcile by hand",
                level="warning",
            )
            return

        reopened_due = await self._academy_today(payment.academy_id) + timedelta(
            days=REOPENED_INVOICE_DUE_DAYS
        )
        for invoice in invoices:
            # Lead decision 2026-11-15: a reopened invoice is due again in five
            # days, so no late fee lands before the family can pay. The autopay
            # charge stamp moves too, or an old stamp re-arms the ladder at once
            # (L8). Set before the reversal so a replay that finds the
            # allocations gone is done.
            moved = {
                field: reopened_due
                for field, day in (
                    ("due_date", invoice.due_date),
                    ("autopay_charge_date", invoice.autopay_charge_date),
                )
                if day is not None and day < reopened_due
            }
            if moved:
                await ledger.save_invoice(invoice.model_copy(update=moved))
            await ledger.record_payment_attempt(
                invoice_id=invoice.invoice_id,
                parent_id=invoice.parent_id,
                amount_cents=allocated.get(invoice.invoice_id) or amount_cents,
                currency=invoice.currency,
                status="returned",
                stripe_payment_intent_id=pi_id or None,
                stripe_checkout_session_id=None,
                failure_code=return_code,
                failure_message=f"ACH return {return_code}",
                idempotency_key=(
                    f"autopay-ach-return:{invoice.invoice_id}:{pi_id}:{return_code}:{amount_cents}"
                ),
                created_by_event_id=event_id or None,
            )
            if _parent_is_told_of_return(return_code):
                await self._append_outbox_once(
                    DunningNoticeRequested(
                        event_id=f"{PAYMENT_RETURNED_NOTICE_PREFIX}{pi_id}:{invoice.invoice_id}",
                        aggregate_id=invoice.invoice_id,
                        academy_id=invoice.academy_id,
                        payload=DunningNoticeRequestedPayload(
                            invoice_id=invoice.invoice_id,
                            parent_id=invoice.parent_id,
                            period=invoice.period,
                            # The reversal below reopens this much.
                            balance_due_cents=invoice.balance_due_cents
                            + allocated.get(invoice.invoice_id, 0),
                            currency=invoice.currency,
                            attempt_no=0,
                            terminal=True,
                            failure_code=return_code,
                            bank_debit=True,
                        ),
                    )
                )
        for allocation in allocations:
            await ledger.reverse_payment_allocation(
                allocation_idempotency_key=str(_alloc_field(allocation, "idempotency_key")),
                reversal_idempotency_key=(
                    f"payment-return:{pi_id}:{_alloc_field(allocation, 'allocation_id')}"
                ),
                reason="dispute" if dispute else "ach_return",
                return_code=return_code,
                reversed_at=self._now(),
            )
        for reversal in prior_reversals:
            # A replay after a crash between the allocation delete and the repair.
            await ledger.repair_after_reversal(
                reversal_idempotency_key=str(reversal["idempotency_key"]),
                reason="dispute" if dispute else "ach_return",
                reversed_at=self._now(),
            )
        await self._append_outbox_once(
            PaymentRefunded(
                event_id=f"billing-payment-refunded:ach-return:{pi_id}:{amount_cents}:{return_code}",
                aggregate_id=payment.payment_id,
                academy_id=payment.academy_id,
                payload=PaymentRefundedPayload(
                    payment_id=payment.payment_id,
                    refunded_cents=amount_cents,
                    total_refunded_cents=amount_cents,
                    reason="other",
                ),
            )
        )
        await ledger.mark_payment_refunded(
            payment.payment_id,
            refunded_cents=amount_cents,
            status="refunded",
            updated_at=self._now(),
        )

    async def _pause_family_after_return(
        self, *, payment: LedgerPayment, pi_id: str, code: str
    ) -> None:
        """The next run must not debit the same account again (owner 2026-11-15)."""
        if self._family_autopay is None or not payment.parent_id:
            return
        await self._family_autopay.pause_family(
            academy_id=payment.academy_id,
            parent_id=payment.parent_id,
            reason=f"payment_returned:{code}",
            request_id=f"payment-return:{pi_id}",
        )

    async def _reverse_paid_invoice_on_dispute(self, event: dict[str, Any], dispute: Any) -> None:
        """A bank debit dispute is final when opened (no evidence round); any
        dispute that closes lost has taken the money back. Either reopens the
        invoices exactly like a late bank return (A4-5)."""
        if self._billing_ledger is None or not isinstance(dispute, dict):
            return
        pi_id = str(dispute.get("payment_intent") or "")
        if not pi_id:
            return
        payment = await self._billing_ledger.get_payment_by_stripe_payment_intent_id(pi_id)
        if payment is None or payment.status not in {"succeeded", "partially_refunded"}:
            return
        status = str(dispute.get("status") or "")
        details = dispute.get("payment_method_details") or {}
        bank = _ledger_payment_is_ach(payment) or (
            isinstance(details, dict) and details.get("type") == "us_bank_account"
        )
        lost = event.get("type") == "charge.dispute.closed" and status == "lost"
        opened_on_bank = (
            event.get("type") == "charge.dispute.created"
            and bank
            and not status.startswith("warning")
        )
        if not (lost or opened_on_bank):
            return
        await self._reverse_returned_payment(
            event_id=str(event.get("id") or ""),
            pi_id=pi_id,
            payment=payment,
            amount_cents=int(dispute.get("amount") or payment.amount_cents),
            return_code=f"dispute:{dispute.get('reason') or 'unknown'}",
            # One dispute can arrive as created then closed: key it, not the event.
            source_key=f"dispute:{dispute.get('id') or event.get('id') or pi_id}",
        )

    async def _request_receipt(
        self,
        *,
        payment: LedgerPayment,
        invoice: LedgerInvoice | None,
        autopay: bool,
        bank_debit: bool,
    ) -> None:
        """One receipt per ledger payment, for every way of paying (A5-2)."""
        await self._append_outbox_once(
            PaymentReceiptRequested(
                event_id=f"payment-receipt:{payment.payment_id}",
                aggregate_id=payment.payment_id,
                academy_id=payment.academy_id,
                payload=PaymentReceiptRequestedPayload(
                    payment_id=payment.payment_id,
                    parent_id=payment.parent_id,
                    amount_cents=payment.amount_cents,
                    currency=payment.currency,
                    invoice_id=invoice.invoice_id if invoice else None,
                    period=invoice.period if invoice else None,
                    autopay=autopay,
                    bank_debit=bank_debit,
                ),
            )
        )

    async def _append_outbox_once(self, event: Any) -> None:
        try:
            await self._outbox.append(event)
        except DuplicateKeyError:
            return

    async def _on_subscription_changed(self, event: dict[str, Any]) -> None:
        sub = event["data"]["object"]
        stripe_sub_id = sub["id"]
        if event.get("type") == "customer.subscription.deleted":
            handled = await self._cancel_student_billing_enrollment(stripe_sub_id)
            if handled:
                return
        existing = await self._subscriptions.get_by_stripe_sub(stripe_sub_id)
        if existing is None:
            return
        status = self._normalize_status(sub.get("status", "incomplete"))
        updated = existing.model_copy(update={"status": status, "updated_at": self._now()})
        await self._subscriptions.save(updated)
        if self._enrollment_autopay is not None and updated.enrollment_id:
            # HIGH review-fix #4: only converge autopay status from a legacy
            # Stripe-subscription event when the billing enrollment is still
            # subscription-managed. Once an enrollment converges onto app-owned
            # autopay (its stripe_subscription_id is cleared), a stale/duplicate
            # subscription webhook must NOT flip its status. Route through the
            # guarded set_autopay_state so illegal transitions are dropped+logged.
            if await self._enrollment_is_legacy_subscription_managed(
                updated.enrollment_id, stripe_sub_id
            ):
                await self._enrollment_autopay.set_autopay_state(
                    enrollment_id=updated.enrollment_id,
                    autopay_enrollment_status=(
                        self._autopay_enrollment_status_for_legacy_subscription(status)
                    ),
                )
            else:
                log.info(
                    "subscription.%s ignored for converged app-owned autopay "
                    "enrollment_id=%s stripe_sub=%s",
                    event.get("type"),
                    updated.enrollment_id,
                    stripe_sub_id,
                )
        await self._outbox.append(
            SubscriptionUpdated(
                aggregate_id=updated.subscription_id,
                academy_id=updated.academy_id,
                payload=SubscriptionUpdatedPayload(
                    subscription_id=updated.subscription_id,
                    parent_id=updated.parent_id,
                    status=status,
                ),
            )
        )

    async def _enrollment_is_legacy_subscription_managed(
        self, enrollment_id: str, stripe_sub_id: str
    ) -> bool:
        """True if the billing enrollment is still managed by this legacy Stripe
        subscription (its stored stripe_subscription_id matches). Returns False
        once the enrollment has converged onto app-owned autopay (id cleared) or
        moved to a different subscription — so a stale/duplicate subscription
        webhook cannot clobber a converged enrollment (HIGH review-fix #4).

        If the billing-enrollment repo is unavailable we conservatively allow
        the (guarded) convergence to run, preserving prior behavior.
        """
        if self._billing_enrollments is None:
            return True
        enrollment = await self._billing_enrollments.get(enrollment_id)
        if enrollment is None:
            return True
        return getattr(enrollment, "stripe_subscription_id", None) == stripe_sub_id

    @staticmethod
    def _normalize_status(stripe_status: str) -> str:
        mapping = {
            "active": "active",
            "trialing": "active",
            "past_due": "past_due",
            "canceled": "cancelled",
            "unpaid": "past_due",
            "incomplete": "incomplete",
            "incomplete_expired": "cancelled",
        }
        return mapping.get(stripe_status, "incomplete")

    @staticmethod
    def _autopay_enrollment_status_for_legacy_subscription(
        legacy_subscription_status: str,
    ) -> str:
        """Map the legacy Stripe-subscription `SubscriptionStatus` vocabulary
        onto the split `autopay_enrollment_status` axis (Slice B).

        This convergence path only runs for pre-existing Stripe-subscription
        rows (the recurring-subscription charging path is retired for new
        enrollments — app-owned off-session autopay is current). `past_due`
        is a charge-outcome concept, not an enrollment-lifecycle one, so it
        maps to `active`: the parent is still enrolled in autopay, they just
        have a failing attempt, which `last_attempt_outcome` tracks instead.
        """
        mapping = {
            "active": "active",
            "past_due": "active",
            "cancelled": "disabled",
            "incomplete": "setup_started",
        }
        return mapping.get(legacy_subscription_status, "setup_started")

    async def _cancel_student_billing_enrollment(self, stripe_sub_id: str) -> bool:
        if self._billing_enrollments is None:
            return False
        enrollment = await self._billing_enrollments.get_by_stripe_subscription(stripe_sub_id)
        if enrollment is None:
            return False
        if enrollment.status == "cancelled":
            return True
        await self._billing_enrollments.save(
            enrollment.model_copy(update={"status": "cancelled", "updated_at": self._now()})
        )
        return True

    async def _handle_session_type_invoice(self, invoice: dict[str, Any], *, paid: bool) -> bool:
        if self._billing_enrollments is None or self._billing_ledger is None:
            return False
        stripe_sub_id = self._stripe_subscription_id_from_invoice(invoice)
        if not stripe_sub_id:
            return False
        enrollment = await self._billing_enrollments.get_by_stripe_subscription(stripe_sub_id)
        if enrollment is None:
            return False
        # Tenant guard: the counter/settings repos partition by the tenant_scope
        # ContextVar (self._academy_id), so minting must only proceed when the
        # enrollment belongs to the same academy — otherwise the invoice number
        # would be drawn from a different academy's series. Matches the guards
        # used by the other subscription/invoice handlers in this file.
        if enrollment.academy_id != self._academy_id:
            raise _QuarantineStripeEvent(
                f"academy mismatch: enrollment={enrollment.academy_id} expected={self._academy_id}"
            )

        now = self._now()
        invoice_id = self._ledger_invoice_id(invoice)
        amount_cents = int(
            invoice.get("amount_paid" if paid else "amount_due") or invoice.get("amount_due") or 0
        )
        period_label = self._invoice_period_label(invoice, now)
        invoice_number = await self._mint_invoice_number(
            academy_id=enrollment.academy_id, period=period_label
        )
        ledger_invoice = await self._billing_ledger.create_invoice(
            LedgerInvoice(
                invoice_id=invoice_id,
                academy_id=enrollment.academy_id,
                parent_id=enrollment.parent_id,
                student_id=enrollment.student_id,
                enrollment_id=enrollment.enrollment_id,
                period=period_label,
                status="open",
                subtotal_cents=amount_cents,
                discount_cents=0,
                total_cents=amount_cents,
                balance_due_cents=amount_cents,
                currency=str(invoice.get("currency") or "usd").lower(),
                due_date=self._invoice_due_date(invoice, now),
                invoice_number=invoice_number,
                created_at=now,
                updated_at=now,
            ),
            lines=[
                InvoiceLine(
                    line_id=f"line-{invoice_id}",
                    academy_id=enrollment.academy_id,
                    invoice_id=invoice_id,
                    line_type="tuition",
                    description=f"Session type tuition {period_label}",
                    quantity=1,
                    unit_amount_cents=amount_cents,
                    amount_cents=amount_cents,
                    source_type="session_type",
                    source_id=enrollment.session_type_id,
                    created_at=now,
                )
            ],
            idempotency_key=f"stripe-invoice:{invoice.get('id')}",
        )
        event_cls = InvoicePaid if paid else InvoiceFailed
        if paid and amount_cents > 0:
            stripe_pi = str(invoice.get("payment_intent") or invoice.get("id"))
            payment = await self._billing_ledger.record_payment(
                LedgerPayment(
                    payment_id=f"ledger-pay-{invoice.get('id')}",
                    academy_id=enrollment.academy_id,
                    parent_id=enrollment.parent_id,
                    amount_cents=amount_cents,
                    unapplied_amount_cents=amount_cents,
                    currency=str(invoice.get("currency") or "usd").lower(),
                    status="succeeded",
                    payment_method="stripe",
                    stripe_payment_intent_id=stripe_pi,
                    application_fee_cents=_application_fee_cents(invoice),
                    paid_at=now,
                    created_at=now,
                    updated_at=now,
                ),
                idempotency_key=f"stripe-invoice-payment:{invoice.get('id')}",
            )
            allocation = await self._billing_ledger.allocate_payment(
                payment_id=payment.payment_id,
                invoice_id=ledger_invoice.invoice_id,
                amount_cents=amount_cents,
                idempotency_key=f"stripe-invoice-allocation:{invoice.get('id')}",
            )
            if allocation is not None:
                ledger_invoice = allocation.invoice
        await self._outbox.append(
            event_cls(
                aggregate_id=ledger_invoice.invoice_id,
                academy_id=ledger_invoice.academy_id,
                payload=self._invoice_payload(
                    ledger_invoice,
                    enrollment.student_id,
                    enrollment.session_type_id,
                    invoice,
                ),
            )
        )
        return True

    @staticmethod
    def _stripe_subscription_id_from_invoice(invoice: dict[str, Any]) -> str | None:
        direct = invoice.get("subscription")
        if direct:
            return str(direct)
        parent = invoice.get("parent")
        if isinstance(parent, dict):
            details = parent.get("subscription_details")
            if isinstance(details, dict) and details.get("subscription"):
                return str(details["subscription"])
        return None

    @staticmethod
    def _ledger_invoice_id(invoice: dict[str, Any]) -> str:
        metadata = invoice.get("metadata")
        if isinstance(metadata, dict) and metadata.get("ledger_invoice_id"):
            return str(metadata["ledger_invoice_id"])
        return f"ledger-{invoice.get('id')}"

    @staticmethod
    def _invoice_period_label(invoice: dict[str, Any], now: datetime) -> str:
        period_start = invoice.get("period_start")
        if period_start is not None:
            try:
                return datetime.fromtimestamp(int(period_start), tz=UTC).strftime("%Y-%m")
            except (TypeError, ValueError, OSError):
                pass
        return now.strftime("%Y-%m")

    async def _academy_today(self, academy_id: str) -> date:
        """Today on the academy's wall clock (UTC when no zone is known)."""
        now: datetime = self._now()
        if self._academy_timezone is None:
            return now.date()
        zone = await resolve_reporting_timezone(self._academy_timezone, academy_id)
        return now.astimezone(ZoneInfo(zone)).date()

    @staticmethod
    def _invoice_due_date(invoice: dict[str, Any], now: datetime) -> date:
        due_timestamp = invoice.get("due_date")
        if due_timestamp is not None:
            try:
                return datetime.fromtimestamp(int(due_timestamp), tz=UTC).date()
            except (TypeError, ValueError, OSError):
                pass
        return (now + timedelta(days=30)).date()

    async def _mint_invoice_number(self, *, academy_id: str, period: str) -> str | None:
        """Mint a human-facing invoice number for a brand-new ledger invoice (Slice D).

        Returns ``None`` when ``billing_counters``/``billing_settings`` were not wired
        into this use case — composition roots that predate Slice D keep working
        unchanged. ``period`` is the ``YYYY-MM`` billing-period label already computed
        by ``_invoice_period_label``; the counter scope keys on academy+month so the
        sequence resets every month and never collides across academies (gaps from
        voided/failed invoices are expected and allowed — see LedgerInvoice.invoice_number
        docstring).
        """
        return await mint_invoice_number(
            billing_counters=self._billing_counters,
            billing_settings=self._billing_settings,
            academy_id=academy_id,
            period=period,
        )

    @staticmethod
    def _invoice_payload(
        invoice: LedgerInvoice,
        student_id: str | None,
        session_type_id: str | None,
        stripe_invoice: dict[str, Any],
    ) -> InvoiceLifecyclePayload:
        return InvoiceLifecyclePayload(
            invoice_id=invoice.invoice_id,
            parent_id=invoice.parent_id,
            student_id=student_id,
            session_type_id=session_type_id,
            billing_period_label=invoice.period,
            total_cents=invoice.total_cents,
            stripe_invoice_id=str(stripe_invoice.get("id")) if stripe_invoice.get("id") else None,
        )

    async def _sync_subscription_invoice_ledger(
        self,
        invoice: dict[str, Any],
        *,
        subscription: Any,
        paid: bool,
        event_id: str,
    ) -> LedgerInvoice | None:
        if self._billing_ledger is None:
            return None
        stripe_invoice_id = str(invoice.get("id") or "")
        if not stripe_invoice_id:
            raise _QuarantineStripeEvent("subscription invoice missing id")
        amount_cents = int(
            invoice.get("amount_paid" if paid else "amount_due") or invoice.get("amount_due") or 0
        )

        now = self._now()
        period_label = self._invoice_period_label(invoice, now)
        currency = str(invoice.get("currency") or "usd").lower()
        enrollment_id = subscription.enrollment_id
        identity = await self._subscription_enrollment_identity(subscription)
        student_id = _identity_value(identity, "student_id")
        parent_id = _identity_value(identity, "parent_id") or subscription.parent_id

        ledger_invoice = await self._billing_ledger.get_invoice_by_stripe_invoice_id(
            stripe_invoice_id
        )
        if enrollment_id:
            get_for_enrollment = getattr(
                self._billing_ledger,
                "get_invoice_for_enrollment_period",
                None,
            )
            if get_for_enrollment is not None:
                ledger_invoice = ledger_invoice or await get_for_enrollment(
                    enrollment_id,
                    period_label,
                    statuses={"draft", "open", "partially_paid", "paid"},
                )
            elif ledger_invoice is None:
                ledger_invoice = await self._billing_ledger.get_open_invoice_for_enrollment(
                    enrollment_id,
                    period_label,
                )
        if ledger_invoice is None and student_id:
            ledger_invoice = await self._billing_ledger.get_open_invoice_for_student(
                student_id,
                period_label,
            )

        if ledger_invoice is None:
            raise _QuarantineStripeEvent(
                f"subscription invoice {stripe_invoice_id} has no app-owned LedgerInvoice "
                f"for enrollment={enrollment_id or 'unknown'} period={period_label}"
            )
        await self._record_subscription_invoice_recovery_point(
            invoice,
            subscription=subscription,
            event_id=event_id,
            recovery_point="ledger_invoice_synced",
            ledger_invoice_id=ledger_invoice.invoice_id,
        )

        if ledger_invoice.academy_id != self._academy_id:
            raise _QuarantineStripeEvent(
                f"academy mismatch: invoice={ledger_invoice.academy_id} expected={self._academy_id}"
            )
        if ledger_invoice.parent_id != parent_id:
            raise _QuarantineStripeEvent(
                f"parent mismatch: invoice={ledger_invoice.parent_id} subscription={parent_id}"
            )
        if (
            ledger_invoice.stripe_invoice_id
            and ledger_invoice.stripe_invoice_id != stripe_invoice_id
        ):
            if paid and (ledger_invoice.status == "paid" or ledger_invoice.balance_due_cents <= 0):
                raise _QuarantineStripeEvent(
                    f"subscription invoice {stripe_invoice_id} matched already-paid invoice "
                    f"{ledger_invoice.invoice_id} already linked to "
                    f"{ledger_invoice.stripe_invoice_id}"
                )
            raise _QuarantineStripeEvent(
                f"subscription invoice {stripe_invoice_id} matched invoice "
                f"{ledger_invoice.invoice_id} already linked to {ledger_invoice.stripe_invoice_id}"
            )
        if paid and (ledger_invoice.status == "paid" or ledger_invoice.balance_due_cents <= 0):
            if ledger_invoice.stripe_invoice_id == stripe_invoice_id:
                return ledger_invoice
            raise _QuarantineStripeEvent(
                f"subscription invoice {stripe_invoice_id} matched already-paid invoice "
                f"{ledger_invoice.invoice_id}"
            )
        if ledger_invoice.stripe_invoice_id is None:
            ledger_invoice = await self._billing_ledger.save_invoice(
                ledger_invoice.model_copy(
                    update={
                        "stripe_invoice_id": stripe_invoice_id,
                        "source_type": ledger_invoice.source_type or "stripe_subscription",
                        "source_id": ledger_invoice.source_id or stripe_invoice_id,
                        "updated_at": now,
                    }
                )
            )
        if not paid:
            return ledger_invoice
        if amount_cents <= 0:
            return ledger_invoice

        stripe_payment_id = self._stripe_invoice_payment_identifier(invoice)
        payment = await self._billing_ledger.record_payment(
            LedgerPayment(
                payment_id=f"ledger-pay-{stripe_invoice_id}",
                academy_id=ledger_invoice.academy_id,
                parent_id=ledger_invoice.parent_id,
                amount_cents=amount_cents,
                unapplied_amount_cents=amount_cents,
                currency=currency,
                status="succeeded",
                payment_method="stripe_subscription",
                stripe_payment_intent_id=stripe_payment_id,
                stripe_invoice_id=stripe_invoice_id,
                application_fee_cents=_application_fee_cents(invoice),
                paid_at=now,
                created_at=now,
                updated_at=now,
            ),
            idempotency_key=f"stripe-invoice-payment:{stripe_invoice_id}",
        )
        await self._record_subscription_invoice_recovery_point(
            invoice,
            subscription=subscription,
            event_id=event_id,
            recovery_point="ledger_payment_recorded",
            ledger_invoice_id=ledger_invoice.invoice_id,
            ledger_payment_id=payment.payment_id,
        )
        await self._billing_ledger.allocate_payment(
            payment_id=payment.payment_id,
            invoice_id=ledger_invoice.invoice_id,
            amount_cents=amount_cents,
            idempotency_key=f"stripe-invoice-allocation:{stripe_invoice_id}",
        )
        await self._record_subscription_invoice_recovery_point(
            invoice,
            subscription=subscription,
            event_id=event_id,
            recovery_point="ledger_allocated",
            ledger_invoice_id=ledger_invoice.invoice_id,
            ledger_payment_id=payment.payment_id,
        )
        return await self._billing_ledger.get_invoice(ledger_invoice.invoice_id) or ledger_invoice

    async def _record_subscription_invoice_recovery_point(
        self,
        invoice: dict[str, Any],
        *,
        subscription: Any,
        event_id: str,
        recovery_point: str,
        ledger_invoice_id: str | None = None,
        ledger_payment_id: str | None = None,
        legacy_payment_id: str | None = None,
        last_error: str | None = None,
    ) -> None:
        if self._invoice_processing is None:
            return
        if recovery_point not in SUBSCRIPTION_INVOICE_RECOVERY_POINTS:
            raise ValueError(f"unknown subscription invoice recovery point: {recovery_point}")
        stripe_invoice_id = str(invoice.get("id") or "")
        if not stripe_invoice_id:
            return
        await self._invoice_processing.record_recovery_point(
            academy_id=subscription.academy_id,
            stripe_invoice_id=stripe_invoice_id,
            stripe_subscription_id=self._stripe_subscription_id_from_invoice(invoice)
            or subscription.stripe_subscription_id,
            event_id=event_id,
            recovery_point=recovery_point,
            ledger_invoice_id=ledger_invoice_id,
            ledger_payment_id=ledger_payment_id,
            legacy_payment_id=legacy_payment_id,
            last_error=last_error,
            updated_at=self._now(),
        )

    async def _subscription_enrollment_identity(
        self,
        subscription: Any,
    ) -> EnrollmentBillingIdentity | dict[str, str | None] | None:
        if self._enrollment_identity is None or not subscription.enrollment_id:
            return None
        identity = await self._enrollment_identity.get_billing_identity(subscription.enrollment_id)
        if identity is None:
            return None
        identity_academy = _identity_value(identity, "academy_id")
        if identity_academy and identity_academy != self._academy_id:
            raise _QuarantineStripeEvent(
                f"academy mismatch: enrollment={identity_academy} expected={self._academy_id}"
            )
        identity_parent = _identity_value(identity, "parent_id")
        if identity_parent and identity_parent != subscription.parent_id:
            raise _QuarantineStripeEvent(
                f"parent mismatch: enrollment={identity_parent} subscription={subscription.parent_id}"
            )
        return identity

    async def _subscription_from_invoice(self, invoice: dict[str, Any]) -> Any | None:
        stripe_sub_id = self._stripe_subscription_id_from_invoice(invoice)
        if not stripe_sub_id:
            return None
        subscription = await self._subscriptions.get_by_stripe_sub(str(stripe_sub_id))
        if subscription is None:
            log.warning("invoice webhook for unknown subscription=%s", stripe_sub_id)
            return None
        if subscription.academy_id != self._academy_id:
            raise _QuarantineStripeEvent(
                f"academy mismatch: subscription={subscription.academy_id} expected={self._academy_id}"
            )
        return subscription

    @staticmethod
    def _stripe_invoice_payment_identifier(invoice: dict[str, Any]) -> str:
        return str(invoice.get("payment_intent") or invoice.get("id"))

    async def _payment_from_invoice(
        self,
        invoice: dict[str, Any],
        *,
        status: str,
        subscription: Any | None = None,
    ) -> Payment | None:
        if subscription is None:
            subscription = await self._subscription_from_invoice(invoice)
        if subscription is None:
            return None

        stripe_pi = self._stripe_invoice_payment_identifier(invoice)
        existing = await self._payments.get_by_stripe_pi(stripe_pi)
        if existing is not None:
            if not can_transition_payment_projection(existing.status, status):
                raise _QuarantineStripeEvent(
                    f"invalid payment projection transition {existing.status}->{status}"
                )
            return None

        # Issue #505: the subscription-ledger sync that runs before this
        # projection already records a ledger-native LedgerPayment for the same
        # charge (payment_id "ledger-pay-{stripe_invoice_id}"). The legacy
        # lookup above only sees the `payments` collection and ledger rows
        # tagged payment_origin="legacy_payment", so without this check the
        # projection save inserts a SECOND `succeeded` row into
        # `ledger_payments` for one charge and every ledger-based revenue
        # report double-counts it. Skipping the projection also means
        # charge.refunded for these PIs falls through to the ledger refund
        # path (_on_charge_refunded_ledger) instead of only touching the
        # projection row.
        if self._billing_ledger is not None and stripe_pi:
            ledger_payment = await self._billing_ledger.get_payment_by_stripe_payment_intent_id(
                stripe_pi
            )
            if ledger_payment is not None:
                return None

        now = self._now()
        amount_key = "amount_paid" if status == "succeeded" else "amount_due"
        return Payment(
            payment_id=str(new_ulid()),
            academy_id=subscription.academy_id,
            parent_id=subscription.parent_id,
            enrollment_id=subscription.enrollment_id,
            session_id=subscription.session_id,
            subscription_id=subscription.subscription_id,
            stripe_payment_intent_id=stripe_pi,
            amount_cents=int(invoice.get(amount_key) or invoice.get("amount_due") or 0),
            currency=str(invoice.get("currency") or "usd").lower(),
            status=status,
            created_at=now,
            updated_at=now,
        )


def _checkout_session_id_from_payment_intent(pi: dict[str, Any]) -> str | None:
    payment_details = pi.get("payment_details")
    if not isinstance(payment_details, dict):
        return None
    order_reference = str(payment_details.get("order_reference") or "")
    if order_reference.startswith("cs_"):
        return order_reference
    return None


def _autopay_discount_metadata_from_pi(metadata: dict[str, Any]) -> dict[str, str]:
    allowed_keys = {
        "ach_discount_cents",
        "ach_discount_line_id",
        "ach_discount_percent",
        "disclosure_version",
        "funding_type",
        "funding_type_source",
    }
    return {
        key: str(value)
        for key, value in metadata.items()
        if key in allowed_keys and value is not None and str(value) != ""
    }


def _alloc_field(allocation: Any, key: str) -> Any:
    if isinstance(allocation, dict):
        return allocation.get(key)
    return getattr(allocation, key, None)


#: Days until a reopened invoice (money taken back after it settled) is due again.
#: shortcut: counted from the UTC date, so it can land a day off the academy's clock.
REOPENED_INVOICE_DUE_DAYS = 5

#: Bank dispute reasons that mean the bank sent the money back on its own (a late
#: return filed as a dispute), so the parent is told like any bank return.
_BANK_RETURN_DISPUTE_REASONS = frozenset(
    {"insufficient_funds", "incorrect_account_details", "bank_cannot_process"}
)


def _parent_is_told_of_return(code: str) -> bool:
    """A bank return is the bank's doing, so the parent is told; a dispute the
    parent raised is their own claim, so it is not (owner 2026-11-15)."""
    if not code.startswith("dispute:"):
        return True
    return code.removeprefix("dispute:") in _BANK_RETURN_DISPUTE_REASONS


def _ledger_payment_is_ach(payment: LedgerPayment) -> bool:
    metadata = payment.metadata or {}
    return (
        metadata.get("funding_type") == "us_bank_account"
        and metadata.get("funding_type_source") == "server_payment_method"
    ) or (
        metadata.get("payment_method_type") == "us_bank_account"
        and metadata.get("payment_method_type_source") == "server_payment_method"
    )


def _ach_return_code_from_stripe_payment_intent(pi: dict[str, Any]) -> str | None:
    values: list[object] = [pi.get("failure_code"), pi.get("failure_reason")]
    last_error = pi.get("last_payment_error")
    if isinstance(last_error, dict):
        values.extend([last_error.get("decline_code"), last_error.get("code")])
    return _first_nacha_code(values)


def _ach_return_code_from_stripe_charge(charge: dict[str, Any]) -> str | None:
    values: list[object] = [charge.get("failure_code"), charge.get("failure_reason")]
    refunds = charge.get("refunds")
    if isinstance(refunds, dict):
        data = refunds.get("data")
        if isinstance(data, list):
            for refund in data:
                if isinstance(refund, dict):
                    values.append(refund.get("failure_reason"))
    return _first_nacha_code(values)


def _first_nacha_code(values: list[object]) -> str | None:
    for value in values:
        code = _stripe_failure_to_nacha_return_code(value)
        if code is not None:
            return code
    return None


_STRIPE_FAILURE_TO_NACHA: dict[str, str] = {
    "insufficient_funds": "R01",
    "bank_account_insufficient_funds": "R01",
    "account_closed": "R02",
    "bank_account_closed": "R02",
    "no_account": "R03",
    "bank_account_not_found": "R03",
    "bank_account_unusable": "R03",
    "debit_not_authorized": "R10",
    "bank_account_restricted": "R29",
}


def _stripe_failure_to_nacha_return_code(value: object) -> str | None:
    normalized = normalize_nacha_return_code(value)
    if normalized is not None:
        return normalized
    compact = str(value or "").lower().strip()
    return _STRIPE_FAILURE_TO_NACHA.get(compact)


def _payment_intent_is_ach(pi: dict[str, Any]) -> bool:
    method_types = pi.get("payment_method_types")
    if isinstance(method_types, list) and "us_bank_account" in method_types:
        return True
    details = pi.get("payment_method_details")
    if isinstance(details, dict):
        return details.get("type") == "us_bank_account" or isinstance(
            details.get("us_bank_account"), dict
        )
    return False


def _charge_is_ach(charge: dict[str, Any]) -> bool:
    details = charge.get("payment_method_details")
    if isinstance(details, dict):
        return details.get("type") == "us_bank_account" or isinstance(
            details.get("us_bank_account"), dict
        )
    return False


def _identity_value(
    identity: EnrollmentBillingIdentity | dict[str, str | None] | None,
    key: str,
) -> str | None:
    if identity is None:
        return None
    if isinstance(identity, dict):
        value = identity.get(key)
    else:
        value = getattr(identity, key)
    return str(value) if value else None


def _application_fee_cents(obj: dict[str, Any]) -> int | None:
    """The platform fee Stripe reports on a PaymentIntent, Invoice or (as a
    string we stamped ourselves) checkout-session metadata; None when absent,
    never 0, so month close knows to estimate rather than trust a blank."""
    raw = obj.get("application_fee_amount")
    if raw is None:
        raw = (obj.get("metadata") or {}).get("application_fee_cents")
    try:
        return int(raw) if raw not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _event_account(event: dict[str, Any]) -> str | None:
    """The connected account a Stripe event occurred on (Connect events carry
    a top-level ``account``); None for a platform event."""
    account = event.get("account")
    return str(account) if account else None


def _on_account_kwargs(stripe_account: str | None) -> dict[str, Any]:
    """``stripe_account`` kwarg for a completion on a connected account; empty
    for the platform so a house-academy call is unchanged."""
    return {"stripe_account": stripe_account} if stripe_account else {}


def _require_same_account(
    event: dict[str, Any], recorded_account: str | None, *, what: str
) -> None:
    """Refuse an event whose Connect ``account`` contradicts the account the
    app recorded the payment on. Stripe object ids are global, so this cannot
    happen honestly; if it does, neither side is trusted to project."""
    event_account = _event_account(event)
    if event_account and recorded_account and event_account != recorded_account:
        raise _QuarantineStripeEvent(
            f"stripe account mismatch: event account={event_account} but {what} "
            f"lives on {recorded_account}"
        )
