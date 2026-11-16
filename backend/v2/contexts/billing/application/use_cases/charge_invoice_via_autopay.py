"""ChargeInvoiceViaAutopay — off-session PaymentIntent against saved card for invoice balance.

Financial status invariant: this use case ONLY changes financial status when the PI
succeeds immediately. On decline the invoice stays open/partially_paid. The delivery
axis (sent_at, delivery_status) is never touched here.

PI idempotency is scoped to invoice, billing period, and attempted balance so true
replays dedupe without replaying stale amounts after the invoice balance changes.

Where the charge runs follows the academy's ChargeRoute:

* House academy (platform): the saved card is found by the platform-wide
  Customer search (``get_default_payment_method``), skipping a method Stripe
  has blocked, and the PaymentIntent is created on the platform.
* Any other academy: a DIRECT charge on its connected account. The customer
  and payment method are the ones the app STORED for that account
  (``SavedPaymentMethodReader``); the PaymentIntent is created on that account
  (``stripe_account``), carries the academy's ``application_fee_amount`` when
  non-zero, and its idempotency key names the account.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import BaseModel

from backend.v2.contexts.billing.application.autopay_eligibility import (
    AUTOPAY_ACTIVE_STATUS,
    CHARGEABLE_INVOICE_STATUSES,
    invoice_is_chargeable,
)
from backend.v2.contexts.billing.application.charge_route import (
    ChargeRoute,
    resolve_charge_route,
)
from backend.v2.contexts.billing.application.ports import (
    BillingSettingsRepository,
    ConnectedAccountRepository,
    LedgerRepository,
    SavedPaymentMethodReader,
)
from backend.v2.contexts.billing.application.use_cases.application_fee import (
    application_fee_kwargs,
    idempotency_key_with_fee,
)
from backend.v2.contexts.billing.application.use_cases.checkout_allocation import (
    allocate_checkout_payment_across_invoices,
)
from backend.v2.contexts.billing.domain.billing_settings import BillingSettings
from backend.v2.contexts.billing.domain.checkout_hold import (
    CHECKOUT_HOLD_DECLINE_CODE,
    active_checkout_hold,
)
from backend.v2.contexts.billing.domain.dunning import NO_SAVED_PAYMENT_METHOD, STRIPE_UNAVAILABLE
from backend.v2.contexts.billing.domain.errors import StripeUnavailable
from backend.v2.contexts.billing.domain.fees import compute_ach_discount
from backend.v2.contexts.billing.domain.ledger import (
    InvoiceLine,
    LedgerInvoice,
    LedgerPayment,
    recompute_totals,
)

log = logging.getLogger(__name__)

# ``InvoiceLine.source_type`` of a recurring tuition discount line (#244).
_TUITION_DISCOUNT_SOURCE_TYPE = "tuition_discount"

# Maps this use case's internal `payment_attempts` status vocabulary onto the
# per-enrollment `AutopayAttemptOutcome` projection axis
# (Slice B — see `contexts.billing.domain.autopay_status`).
_ATTEMPT_STATUS_TO_OUTCOME = {
    "succeeded": "succeeded",
    "failed": "declined",
    "requires_action": "requires_action",
}

# Only an actively-autopaying enrollment may be auto-charged (see
# ``autopay_eligibility.AUTOPAY_ACTIVE_STATUS``).


class EnrollmentAutopayGateway(Protocol):
    """Narrow per-enrollment port for the autopay charge path (Slice B).

    Resolves and mutates the single per-enrollment autopay store keyed by
    ``enrollment_id`` (``student_billing_enrollments``). Used for the
    charge-eligibility gate (``get_autopay_enrollment_status``) and to project
    the latest attempt outcome (``record_attempt_outcome``). The outcome
    projection is deliberately independent of ``autopay_enrollment_status``:
    a bounced charge does not change whether the enrollment is enrolled.
    """

    async def get_autopay_enrollment_status(self, *, enrollment_id: str) -> str | None: ...

    async def record_attempt_outcome(
        self,
        *,
        enrollment_id: str,
        outcome: str,
        occurred_at: datetime,
        failure_code: str | None,
    ) -> None: ...


# ---------------------------------------------------------------------------
# Narrow port — only what this use case needs from Stripe
# ---------------------------------------------------------------------------


class AutopayStripeGateway(Protocol):
    """Narrow port for off-session autopay charge.

    Implementors must:
    1. Retrieve the Stripe Customer for the parent and its default PM.
    2. Create a PaymentIntent with off_session=True, confirm=True.
    3. Return (pi_id, pi_status, decline_code_or_None).

    ``pi_status`` is the raw Stripe PI status string:
    "succeeded", "requires_action", "requires_payment_method", etc.
    ``decline_code`` is set on hard declines (card_declined, etc.).
    """

    async def get_default_payment_method(
        self, *, academy_id: str, parent_id: str
    ) -> tuple[str, str] | None:
        """Return (stripe_customer_id, payment_method_id) or None if no saved card."""
        ...

    async def retrieve_payment_method(
        self, stripe_payment_method_id: str, *, stripe_account: str | None = None
    ) -> dict[str, Any]:
        """Fetch the saved PaymentMethod so funding type is known at charge time."""
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
        application_fee_cents: int = 0,
        stripe_account: str | None = None,
    ) -> tuple[str, str, str | None]:
        """Return (pi_id, pi_status, decline_code_or_None)."""
        ...


# ---------------------------------------------------------------------------
# Result DTO
# ---------------------------------------------------------------------------


class ChargeResult(BaseModel):
    model_config = {"frozen": True}

    success: bool
    invoice_id: str
    status: str  # invoice status after the attempt
    balance_due_cents: int
    attempted_amount_cents: int = 0
    requires_action: bool = False
    processing: bool = False
    decline_code: str | None = None


class FamilyChargeResult(BaseModel):
    """One family charge (L8): the invoices it covered and the one result that
    applies to every one of them. ``dropped_invoice_ids`` go the single path."""

    model_config = {"frozen": True}

    charged_invoice_ids: tuple[str, ...] = ()
    dropped_invoice_ids: tuple[str, ...] = ()
    result: ChargeResult | None = None


_ATTEMPT_MESSAGES: dict[str, str | None] = {
    "processing": "ACH debit submitted; awaiting settlement.",
    "requires_action": None,
    "succeeded": None,
}


def _attempt_status(pi_status: str, decline_code: str | None) -> str:
    """The attempt row status for a PaymentIntent answer."""
    if decline_code is not None:
        return "failed"
    if pi_status in ("processing", "succeeded"):
        return pi_status
    return "requires_action"


def _refused(invoice: LedgerInvoice, decline_code: str) -> ChargeResult:
    """Not charged: no Stripe call or no answer, nothing recorded."""
    return ChargeResult(
        success=False,
        invoice_id=invoice.invoice_id,
        status=invoice.status,
        balance_due_cents=invoice.balance_due_cents,
        decline_code=decline_code,
    )


def _attempt_result(
    invoice: LedgerInvoice, attempt_status: str, decline_code: str | None
) -> ChargeResult:
    """The unsettled outcome of a PaymentIntent Stripe answered."""
    return ChargeResult(
        success=attempt_status == "succeeded",
        invoice_id=invoice.invoice_id,
        status="paid" if attempt_status == "succeeded" else invoice.status,
        balance_due_cents=0 if attempt_status == "succeeded" else invoice.balance_due_cents,
        attempted_amount_cents=invoice.balance_due_cents,
        processing=attempt_status == "processing",
        requires_action=attempt_status == "requires_action",
        decline_code=decline_code,
    )


# ---------------------------------------------------------------------------
# Use case
# ---------------------------------------------------------------------------


class ChargeInvoiceViaAutopay:
    """Charge an invoice balance via an off-session Stripe PaymentIntent.

    Inject ``stripe=None`` to run in environments without Stripe configured
    (the use case raises ValueError for un-chargeable invariants before the
    gateway call, so unit tests still exercise all guard logic).
    """

    def __init__(
        self,
        *,
        ledger: LedgerRepository,
        stripe: AutopayStripeGateway | None = None,
        enrollment_autopay: EnrollmentAutopayGateway | None = None,
        settings: BillingSettingsRepository | None = None,
        connected_accounts: ConnectedAccountRepository | None = None,
        parent_customers: SavedPaymentMethodReader | None = None,
        clock=lambda: datetime.now(UTC),
    ) -> None:
        self._ledger = ledger
        self._stripe = stripe
        self._enrollment_autopay = enrollment_autopay
        self._settings = settings
        self._connected_accounts = connected_accounts
        self._parent_customers = parent_customers
        self._now = clock

    async def execute(
        self,
        invoice_id: str,
        *,
        retry_scope: str | None = None,
        source: str = "autopay",
        actor_id: str | None = None,
    ) -> ChargeResult:
        now = self._now()

        # 1. Load invoice
        invoice = await self._ledger.get_invoice(invoice_id)
        if invoice is None:
            raise ValueError(f"invoice {invoice_id!r} not found")

        # 2. Guard: invoice must be chargeable
        if invoice.status not in CHARGEABLE_INVOICE_STATUSES:
            raise ValueError(
                f"invoice {invoice_id!r} is not chargeable (status={invoice.status!r}); "
                f"only {sorted(CHARGEABLE_INVOICE_STATUSES)} are allowed"
            )
        if invoice.balance_due_cents <= 0:
            raise ValueError(f"invoice {invoice_id!r} has no balance due (balance_due_cents=0)")

        fresh = await self._ledger.get_invoice(invoice_id)
        if fresh is None:
            raise ValueError(f"invoice {invoice_id!r} not found")
        if not invoice_is_chargeable(fresh.status, fresh.balance_due_cents):
            raise ValueError(f"invoice {invoice_id!r} no longer chargeable")
        invoice = fresh

        refusal = await self._member_refusal(invoice, now=now)
        if refusal is not None:
            return refusal
        resolved = await self._resolve_saved_method(invoice)
        if isinstance(resolved, ChargeResult):
            return resolved
        route, customer_id, pm_id = resolved
        on_account = route.on_account_kwargs()
        connected_account_id = route.connected_account_id
        settings, funding_type = await self._resolve_discount_inputs(pm_id, on_account)
        invoice, discount_metadata = await self._apply_ach_discount_if_needed(
            invoice=invoice,
            settings=settings,
            funding_type=funding_type,
        )

        # 4. Create off-session PaymentIntent (idempotency key prevents stale amount replay)
        base_idempotency_key = (
            f"autopay:{invoice.invoice_id}:{invoice.period}:{invoice.balance_due_cents}"
        )
        idempotency_key = (
            f"{base_idempotency_key}:{retry_scope}" if retry_scope else base_idempotency_key
        )
        fee_cents = route.application_fee_cents(invoice.balance_due_cents)
        idempotency_key = idempotency_key_with_fee(idempotency_key, fee_cents)
        idempotency_key = route.idempotency_key(idempotency_key)
        pi_metadata = {
            "invoice_id": invoice.invoice_id,
            "academy_id": invoice.academy_id,
            "parent_id": invoice.parent_id,
            "source": source,
        }
        if actor_id:
            pi_metadata["actor_id"] = actor_id
        pi_metadata.update(discount_metadata)
        try:
            pi_id, pi_status, decline_code = await self._stripe.create_off_session_payment_intent(  # type: ignore[union-attr]
                amount_cents=invoice.balance_due_cents,
                currency=invoice.currency,
                customer_id=customer_id,
                payment_method_id=pm_id,
                idempotency_key=idempotency_key,
                metadata=pi_metadata,
                **on_account,
                **application_fee_kwargs(fee_cents),
            )
        except StripeUnavailable as exc:
            # Stripe could not be asked. Not a decline: no failed attempt row, no
            # outcome projection; the worker parks and retries (L1 A4-3). Any other
            # exception is a bug and propagates to the worker's technical-failure park.
            log.warning("charge_autopay: stripe unavailable invoice=%s err=%s", invoice_id, exc)
            return _refused(invoice, STRIPE_UNAVAILABLE)

        attempt_status = _attempt_status(pi_status, decline_code)
        await self._record_attempt(
            invoice=invoice,
            amount_cents=invoice.balance_due_cents,
            status=attempt_status,
            stripe_payment_intent_id=pi_id,
            failure_code=decline_code,
            failure_message=_ATTEMPT_MESSAGES.get(attempt_status, decline_code),
            retry_scope=retry_scope,
        )
        log.info(
            "charge_autopay: invoice=%s pi=%s status=%s code=%s",
            invoice_id,
            pi_id,
            attempt_status,
            decline_code,
        )
        if attempt_status != "succeeded":
            return _attempt_result(invoice, attempt_status, decline_code)

        # 6. PI succeeded — record LedgerPayment + allocate
        payment_id = f"ledger-pay-autopay:{pi_id}"
        payment = await self._ledger.record_payment(
            LedgerPayment(
                payment_id=payment_id,
                academy_id=invoice.academy_id,
                parent_id=invoice.parent_id,
                amount_cents=invoice.balance_due_cents,
                unapplied_amount_cents=invoice.balance_due_cents,
                currency=invoice.currency,
                status="succeeded",
                payment_method="stripe_autopay",
                stripe_payment_intent_id=pi_id,
                # A direct charge lives on the academy's connected account;
                # a refund of it must be issued there. None = platform.
                stripe_account_id=connected_account_id,
                # The fee the PaymentIntent was created with; the webhook's
                # replay of the same idempotency key must not have to fill it.
                application_fee_cents=fee_cents,
                paid_at=now,
                metadata=discount_metadata or None,
                created_at=now,
                updated_at=now,
            ),
            idempotency_key=f"autopay-pi:{pi_id}",
        )

        allocation_result = await self._ledger.allocate_payment(
            payment_id=payment.payment_id,
            invoice_id=invoice.invoice_id,
            amount_cents=invoice.balance_due_cents,
            idempotency_key=f"autopay-alloc:{pi_id}",
        )

        updated_invoice = allocation_result.invoice
        log.info(
            "charge_autopay: succeeded invoice=%s pi=%s new_status=%s balance=%d",
            invoice_id,
            pi_id,
            updated_invoice.status,
            updated_invoice.balance_due_cents,
        )
        return ChargeResult(
            success=True,
            invoice_id=invoice_id,
            status=updated_invoice.status,
            balance_due_cents=updated_invoice.balance_due_cents,
            attempted_amount_cents=invoice.balance_due_cents,
        )

    async def execute_family(
        self,
        invoice_ids: Sequence[str],
        *,
        charge_group_id: str,
        retry_scopes: Mapping[str, str | None],
    ) -> FamilyChargeResult:
        """One PaymentIntent for one family's invoices due now (L8).

        If any member is paid, voided, held by an open checkout or not
        autopaying, there is no family charge at all: every id comes back
        dropped for the worker to decide. A family charge is only ever the
        whole set that was claimed, so a later retry of that set cannot grow
        or shrink it and re-charge members under a new key.

        The key is derived from the members and their retry rungs, never from the
        per-tick ``charge_group_id``: a retry after a timeout, a crash or a
        technical park re-sends the same members, rungs and total under the same
        key, and Stripe replays the first PaymentIntent.
        """
        now = self._now()
        members: list[LedgerInvoice] = []
        dropped: list[str] = []
        for invoice_id in sorted(invoice_ids):
            invoice = await self._ledger.get_invoice(invoice_id)
            if (
                invoice is None
                or not invoice_is_chargeable(invoice.status, invoice.balance_due_cents)
                or await self._member_refusal(invoice, now=now) is not None
            ):
                dropped.append(invoice_id)
                continue
            members.append(invoice)
        if (
            len(members) < 2
            or dropped
            or len({m.parent_id for m in members}) != 1
            or len({m.currency.lower() for m in members}) != 1
        ):
            return FamilyChargeResult(dropped_invoice_ids=tuple(sorted(invoice_ids)))
        charged = tuple(m.invoice_id for m in members)
        lead = members[0]
        resolved = await self._resolve_saved_method(lead)
        if isinstance(resolved, ChargeResult):
            return FamilyChargeResult(
                charged_invoice_ids=charged, dropped_invoice_ids=tuple(dropped), result=resolved
            )
        route, customer_id, pm_id = resolved
        on_account = route.on_account_kwargs()
        settings, funding_type = await self._resolve_discount_inputs(pm_id, on_account)
        discounted: list[LedgerInvoice] = []
        member_metadata: list[dict[str, str]] = []
        for invoice in members:
            updated, metadata = await self._apply_ach_discount_if_needed(
                invoice=invoice, settings=settings, funding_type=funding_type
            )
            discounted.append(updated)
            member_metadata.append(metadata)
        members = discounted
        total = sum(m.balance_due_cents for m in members)
        discount_metadata = _family_discount_metadata(member_metadata)

        rungs = "|".join(
            sorted(f"{m.invoice_id}:{retry_scopes.get(m.invoice_id) or ''}" for m in members)
        )
        digest = hashlib.sha256(rungs.encode()).hexdigest()[:32]
        idempotency_key = f"autopay-family:{digest}:{total}"
        fee_cents = route.application_fee_cents(total)
        idempotency_key = route.idempotency_key(
            idempotency_key_with_fee(idempotency_key, fee_cents)
        )
        joined_ids = ",".join(charged)
        pi_metadata = {
            "invoice_ids": joined_ids,
            "academy_id": lead.academy_id,
            "parent_id": lead.parent_id,
            "source": "autopay",
            "charge_group_id": charge_group_id,
            **discount_metadata,
        }
        family = lead.model_copy(update={"balance_due_cents": total})
        try:
            pi_id, pi_status, decline_code = await self._stripe.create_off_session_payment_intent(  # type: ignore[union-attr]
                amount_cents=total,
                currency=lead.currency,
                customer_id=customer_id,
                payment_method_id=pm_id,
                idempotency_key=idempotency_key,
                metadata=pi_metadata,
                **on_account,
                **application_fee_kwargs(fee_cents),
            )
        except StripeUnavailable as exc:
            log.warning("charge_autopay: stripe unavailable group=%s err=%s", charge_group_id, exc)
            return FamilyChargeResult(
                charged_invoice_ids=charged,
                dropped_invoice_ids=tuple(dropped),
                result=_refused(family, STRIPE_UNAVAILABLE),
            )

        attempt_status = _attempt_status(pi_status, decline_code)
        for invoice in members:
            await self._record_attempt(
                invoice=invoice,
                amount_cents=invoice.balance_due_cents,
                status=attempt_status,
                stripe_payment_intent_id=pi_id,
                failure_code=decline_code,
                failure_message=_ATTEMPT_MESSAGES.get(attempt_status, decline_code),
                retry_scope=retry_scopes.get(invoice.invoice_id),
            )
        log.info(
            "charge_autopay: family group=%s invoices=%s pi=%s status=%s code=%s",
            charge_group_id,
            joined_ids,
            pi_id,
            attempt_status,
            decline_code,
        )
        if attempt_status == "succeeded":
            payment = await self._ledger.record_payment(
                LedgerPayment(
                    payment_id=f"ledger-pay-autopay:{pi_id}",
                    academy_id=lead.academy_id,
                    parent_id=lead.parent_id,
                    amount_cents=total,
                    unapplied_amount_cents=total,
                    currency=lead.currency,
                    status="succeeded",
                    payment_method="stripe_autopay",
                    stripe_payment_intent_id=pi_id,
                    stripe_account_id=route.connected_account_id,
                    application_fee_cents=fee_cents,
                    paid_at=now,
                    metadata={**discount_metadata, "invoice_ids": joined_ids},
                    created_at=now,
                    updated_at=now,
                ),
                idempotency_key=f"autopay-pi:{pi_id}",
            )
            await allocate_checkout_payment_across_invoices(
                ledger=self._ledger,
                payment=payment,
                invoices=members,
                amount_cents=total,
                allocation_key_prefix=f"autopay-alloc:{pi_id}",
            )
        return FamilyChargeResult(
            charged_invoice_ids=charged,
            dropped_invoice_ids=tuple(dropped),
            result=_attempt_result(family, attempt_status, decline_code),
        )

    async def _member_refusal(
        self, invoice: LedgerInvoice, *, now: datetime
    ) -> ChargeResult | None:
        """Why this chargeable invoice must not be charged now, or None."""
        # 2a. Checkout hold (issue #434): a Stripe Checkout Session is open for this
        # invoice, so a parent may be paying it manually right now. Invoice status is
        # not proof of the contrary — it only moves when the success webhook drains,
        # and that drain can lag by up to an hour. Charging here bills the parent twice
        # (the dunning ladder's per-rung retry_scope defeats Stripe's idempotency).
        # Park instead: no Stripe call, and deliberately no payment_attempt row — this
        # is our lock, not a decline the parent caused, so it must not read as one on
        # the attempt history or consume a rung of their retry budget.
        held_session_id = active_checkout_hold(invoice, now=now)
        if held_session_id is not None:
            log.info(
                "charge_autopay: parking invoice=%s — checkout session %s still open",
                invoice.invoice_id,
                held_session_id or "<unknown>",
            )
            return _refused(invoice, CHECKOUT_HOLD_DECLINE_CODE)

        # 2b. Charge-eligibility gate (Security P2): the invoice's enrollment
        # must be actively autopaying. Refuse to auto-charge a paused / disabled
        # / not-yet-set-up enrollment — the per-enrollment autopay status is the
        # single charge-eligibility signal. FAIL CLOSED: if the invoice carries
        # no enrollment_id we cannot resolve an autopay status to authorize the
        # charge, so we decline rather than bypass the check. No Stripe call, no
        # attempt recorded in either case.
        if self._enrollment_autopay is not None:
            if not invoice.enrollment_id:
                log.warning(
                    "charge_autopay: refusing to charge invoice=%s — no enrollment_id to "
                    "resolve autopay eligibility (fail-closed)",
                    invoice.invoice_id,
                )
                return _refused(invoice, "autopay_not_active")
            autopay_status = await self._enrollment_autopay.get_autopay_enrollment_status(
                enrollment_id=invoice.enrollment_id
            )
            if autopay_status != AUTOPAY_ACTIVE_STATUS:
                log.warning(
                    "charge_autopay: refusing to charge invoice=%s enrollment=%s — "
                    "autopay_enrollment_status=%s (must be %s)",
                    invoice.invoice_id,
                    invoice.enrollment_id,
                    autopay_status,
                    AUTOPAY_ACTIVE_STATUS,
                )
                return _refused(invoice, "autopay_not_active")
        return None

    async def _resolve_saved_method(
        self, invoice: LedgerInvoice
    ) -> tuple[ChargeRoute, str, str] | ChargeResult:
        """The route and the saved (customer, payment method) to charge, or the
        refusal to return instead."""
        # 3. Look up parent's saved Stripe card
        if self._stripe is None:
            log.info(
                "charge_autopay: stripe gateway not configured — skipping PI creation invoice=%s",
                invoice.invoice_id,
            )
            return _refused(invoice, "stripe_not_configured")

        route = await resolve_charge_route(
            connected_accounts=self._connected_accounts,
            settings=self._settings,
            context=f"charge_autopay invoice={invoice.invoice_id}",
        )
        if route.refused:
            log.warning(
                "charge_autopay: refusing to charge invoice=%s — connected account not ready",
                invoice.invoice_id,
            )
            return _refused(invoice, "connected_account_not_ready")
        # House academy (and an unwired connected-accounts store) -> platform;
        # otherwise a direct charge on the ready connected account.
        connected_account_id = route.connected_account_id

        if connected_account_id is None:
            # Platform: the Stripe customer's CURRENT default method (a parent can
            # change it in the Billing Portal, which nothing syncs back), so never
            # a stored id. Only a method Stripe has blocked is skipped (A4-8).
            try:
                saved = await self._stripe.get_default_payment_method(
                    academy_id=invoice.academy_id,
                    parent_id=invoice.parent_id,
                )
            except StripeUnavailable as exc:
                log.warning(
                    "charge_autopay: stripe unavailable invoice=%s err=%s", invoice.invoice_id, exc
                )
                return _refused(invoice, STRIPE_UNAVAILABLE)
            if (
                saved is not None
                and self._parent_customers is not None
                and await self._parent_customers.payment_method_blocked(
                    parent_id=invoice.parent_id, payment_method_id=saved[1]
                )
            ):
                saved = None
        elif self._parent_customers is None:
            # Fail closed: a platform-wide search cannot see the connected
            # account's customers, so there is nothing safe to charge.
            log.error(
                "charge_autopay: no stored-card reader wired for a direct charge invoice=%s",
                invoice.invoice_id,
            )
            saved = None
        else:
            saved = await self._parent_customers.get_saved_payment_method(
                parent_id=invoice.parent_id,
                stripe_account_id=connected_account_id,
            )
        if saved is None:
            # The parent's to fix, not a fault on our side: a normal failed result so the
            # worker can ask them to add a card or bank (L1 A4-1). No attempt row.
            log.info("charge_autopay: no saved payment method invoice=%s", invoice.invoice_id)
            return _refused(invoice, NO_SAVED_PAYMENT_METHOD)
        customer_id, pm_id = saved
        return route, customer_id, pm_id

    async def _record_attempt(
        self,
        *,
        invoice: LedgerInvoice,
        amount_cents: int,
        status: str,
        stripe_payment_intent_id: str | None,
        failure_code: str | None,
        failure_message: str | None,
        retry_scope: str | None = None,
    ) -> None:
        attempt_key_suffix = stripe_payment_intent_id or "stripe-error"
        retry_part = f"{retry_scope}:" if retry_scope else ""
        await self._ledger.record_payment_attempt(
            invoice_id=invoice.invoice_id,
            parent_id=invoice.parent_id,
            amount_cents=amount_cents,
            currency=invoice.currency,
            status=status,
            stripe_payment_intent_id=stripe_payment_intent_id,
            stripe_checkout_session_id=None,
            failure_code=failure_code,
            failure_message=failure_message,
            idempotency_key=(
                f"autopay-attempt:{invoice.invoice_id}:{invoice.period}:"
                f"{amount_cents}:{retry_part}{status}:{attempt_key_suffix}"
            ),
            created_by_event_id=None,
        )
        if self._enrollment_autopay is not None and invoice.enrollment_id:
            outcome = _ATTEMPT_STATUS_TO_OUTCOME.get(status)
            if outcome is not None:
                # Deliberately does NOT touch autopay_enrollment_status: a
                # bounced/declined charge leaves THIS enrollment's autopay
                # enrollment untouched (still enrolled — only the last-attempt
                # projection changes). Per-enrollment (Slice B).
                await self._enrollment_autopay.record_attempt_outcome(
                    enrollment_id=invoice.enrollment_id,
                    outcome=outcome,
                    occurred_at=self._now(),
                    failure_code=failure_code,
                )

    async def _resolve_discount_inputs(
        self,
        payment_method_id: str,
        on_account: dict[str, Any],
    ) -> tuple[BillingSettings | None, str | None]:
        if self._settings is None or self._stripe is None:
            return None, None
        try:
            settings = await self._settings.get()
        except Exception as exc:
            log.warning("charge_autopay: billing settings lookup failed; no discount err=%s", exc)
            return None, None
        try:
            payment_method = await self._stripe.retrieve_payment_method(
                payment_method_id, **on_account
            )
        except Exception as exc:
            log.warning(
                "charge_autopay: payment method lookup failed pm=%s; no discount err=%s",
                payment_method_id,
                exc,
            )
            return settings, None
        return settings, _funding_type_from_payment_method(payment_method)

    async def _apply_ach_discount_if_needed(
        self,
        *,
        invoice: LedgerInvoice,
        settings: BillingSettings | None,
        funding_type: str | None,
    ) -> tuple[LedgerInvoice, dict[str, str]]:
        lines = await self._ledger.get_lines_for_invoice(invoice.invoice_id)
        existing_discount = next(
            (line for line in lines if line.line_type == "ach_discount"),
            None,
        )
        discount_base_cents = _discount_base_subtotal_cents(invoice, lines, existing_discount)
        discount_cents = compute_ach_discount(discount_base_cents, settings, funding_type)
        if existing_discount is not None:
            if discount_cents <= 0:
                remaining_lines = [
                    line for line in lines if line.line_id != existing_discount.line_id
                ]
                await self._ledger.delete_invoice_line(
                    invoice_id=invoice.invoice_id,
                    line_id=existing_discount.line_id,
                )
                restored = _remove_discount_from_invoice_projection(
                    invoice,
                    existing_discount,
                    remaining_lines,
                    now=self._now(),
                )
                try:
                    return (
                        await self._ledger.save_invoice(restored),
                        _server_payment_method_metadata(funding_type),
                    )
                except Exception:
                    await self._ledger.save_line(existing_discount)
                    raise
            now = self._now()
            current_line = InvoiceLine(
                line_id=existing_discount.line_id,
                academy_id=invoice.academy_id,
                invoice_id=invoice.invoice_id,
                line_type="ach_discount",
                description=settings.ach_discount_label,
                quantity=1,
                unit_amount_cents=-discount_cents,
                amount_cents=-discount_cents,
                source_type="autopay_cash_discount",
                source_id=settings.disclosure_version,
                created_at=existing_discount.created_at,
            )
            if current_line != existing_discount:
                await self._ledger.save_line(current_line)
                lines = [
                    current_line if line.line_id == existing_discount.line_id else line
                    for line in lines
                ]
                recomputed = _replace_discount_in_invoice_projection(
                    invoice,
                    old_discount_line=existing_discount,
                    updated_lines=lines,
                    now=now,
                )
                if recomputed != invoice:
                    try:
                        invoice = await self._ledger.save_invoice(recomputed)
                    except Exception:
                        await self._ledger.save_line(existing_discount)
                        raise
                existing_discount = current_line
            elif any(line.line_type != "ach_discount" for line in lines):
                recomputed = _recompute_invoice_projection(invoice, lines, now=self._now())
                if recomputed != invoice:
                    invoice = await self._ledger.save_invoice(recomputed)
            return invoice, _discount_metadata(
                discount_cents=discount_cents,
                discount_percent=settings.ach_discount_percent,
                line_id=existing_discount.line_id,
                funding_type=funding_type,
                disclosure_version=settings.disclosure_version,
            )

        if discount_cents <= 0:
            return invoice, _server_payment_method_metadata(funding_type)

        now = self._now()
        line = InvoiceLine(
            line_id=f"ach-discount:{invoice.invoice_id}",
            academy_id=invoice.academy_id,
            invoice_id=invoice.invoice_id,
            line_type="ach_discount",
            description=settings.ach_discount_label,
            quantity=1,
            unit_amount_cents=-discount_cents,
            amount_cents=-discount_cents,
            source_type="autopay_cash_discount",
            source_id=settings.disclosure_version,
            created_at=now,
        )
        await self._ledger.save_line(line)
        updated_invoice = _recompute_invoice_projection(
            invoice.model_copy(update={"updated_at": now}),
            [*lines, line],
            now=now,
        )
        try:
            invoice = await self._ledger.save_invoice(updated_invoice)
        except Exception:
            await self._ledger.delete_invoice_line(
                invoice_id=invoice.invoice_id,
                line_id=line.line_id,
            )
            raise
        return invoice, _discount_metadata(
            discount_cents=discount_cents,
            discount_percent=settings.ach_discount_percent,
            line_id=line.line_id,
            funding_type=funding_type,
            disclosure_version=settings.disclosure_version,
        )


def _funding_type_from_payment_method(payment_method: dict[str, Any]) -> str | None:
    payment_method_type = str(payment_method.get("type") or "").lower()
    if payment_method_type == "card":
        card = payment_method.get("card")
        if isinstance(card, dict):
            return str(card.get("funding") or "card").lower()
        return "card"
    return payment_method_type or None


def _recompute_invoice_projection(
    invoice: LedgerInvoice,
    lines: list[InvoiceLine],
    *,
    now: datetime,
) -> LedgerInvoice:
    non_discount_lines = [line for line in lines if line.line_type != "ach_discount"]
    discount_lines = [line for line in lines if line.line_type == "ach_discount"]
    if non_discount_lines:
        return recompute_totals(invoice.model_copy(update={"updated_at": now}), lines)

    discount_delta = sum(line.amount_cents for line in discount_lines)
    allocated = max(0, invoice.total_cents - invoice.balance_due_cents)
    total = max(0, invoice.total_cents + discount_delta)
    balance = max(0, total - allocated)
    status = invoice.status
    if status not in ("draft", "void"):
        if balance == 0:
            status = "paid"
        elif balance < total:
            status = "partially_paid"
        else:
            status = "open"
    return invoice.model_copy(
        update={
            "subtotal_cents": max(0, invoice.subtotal_cents + discount_delta),
            "total_cents": total,
            "balance_due_cents": balance,
            "status": status,
            "updated_at": now,
        }
    )


def _replace_discount_in_invoice_projection(
    invoice: LedgerInvoice,
    *,
    old_discount_line: InvoiceLine,
    updated_lines: list[InvoiceLine],
    now: datetime,
) -> LedgerInvoice:
    restored = _remove_discount_from_invoice_projection(
        invoice,
        old_discount_line,
        [line for line in updated_lines if line.line_id != old_discount_line.line_id],
        now=now,
    )
    return _recompute_invoice_projection(restored, updated_lines, now=now)


def _discount_base_subtotal_cents(
    invoice: LedgerInvoice,
    lines: list[InvoiceLine],
    existing_discount: InvoiceLine | None,
) -> int:
    """The amount the ACH cash discount is a percentage of.

    It is the price AFTER every tuition discount (owner decision 2026-09-25), and
    it is the same on the first attempt and on every retry. It comes from the
    lines, never the header subtotal, because the monthly generator writes that
    subtotal GROSS with the tuition discount mirrored in ``discount_cents``.
    Summing the lines already takes a ``tuition_discount`` line off, so only the
    part of ``discount_cents`` no such line carries is subtracted too.
    """
    non_discount_lines = [line for line in lines if line.line_type != "ach_discount"]
    if non_discount_lines:
        line_discount_cents = sum(
            -line.amount_cents
            for line in non_discount_lines
            if line.source_type == _TUITION_DISCOUNT_SOURCE_TYPE and line.amount_cents < 0
        )
        header_only_discount_cents = max(0, invoice.discount_cents - line_discount_cents)
        return sum(line.amount_cents for line in non_discount_lines) - header_only_discount_cents

    subtotal = invoice.subtotal_cents
    if existing_discount is not None:
        subtotal += abs(existing_discount.amount_cents)
    return subtotal - max(0, invoice.discount_cents)


def _remove_discount_from_invoice_projection(
    invoice: LedgerInvoice,
    discount_line: InvoiceLine,
    remaining_lines: list[InvoiceLine],
    *,
    now: datetime,
) -> LedgerInvoice:
    if any(line.line_type != "ach_discount" for line in remaining_lines):
        return recompute_totals(invoice.model_copy(update={"updated_at": now}), remaining_lines)

    discount_cents = abs(discount_line.amount_cents)
    allocated = max(0, invoice.total_cents - invoice.balance_due_cents)
    total = invoice.total_cents + discount_cents
    balance = max(0, total - allocated)
    status = invoice.status
    if status not in ("draft", "void"):
        if balance == 0:
            status = "paid"
        elif balance < total:
            status = "partially_paid"
        else:
            status = "open"
    return invoice.model_copy(
        update={
            "subtotal_cents": invoice.subtotal_cents + discount_cents,
            "total_cents": total,
            "balance_due_cents": balance,
            "status": status,
            "updated_at": now,
        }
    )


def _discount_metadata(
    *,
    discount_cents: int,
    discount_percent: float,
    line_id: str,
    funding_type: str | None,
    disclosure_version: str | None,
) -> dict[str, str]:
    metadata = {
        "ach_discount_cents": str(discount_cents),
        "ach_discount_line_id": line_id,
        "ach_discount_percent": str(discount_percent),
        "funding_type": str(funding_type or "unknown"),
    }
    if funding_type == "us_bank_account":
        metadata["funding_type_source"] = "server_payment_method"
    if disclosure_version:
        metadata["disclosure_version"] = disclosure_version
    return metadata


def _family_discount_metadata(member_metadata: list[dict[str, str]]) -> dict[str, str]:
    """One family charge's discount metadata: the members' shared fields with the
    cents summed. No single ``ach_discount_line_id``: each invoice keeps its own line."""
    merged: dict[str, str] = {}
    for metadata in member_metadata:
        merged.update({k: v for k, v in metadata.items() if k != "ach_discount_line_id"})
    if any("ach_discount_cents" in metadata for metadata in member_metadata):
        merged["ach_discount_cents"] = str(
            sum(int(metadata.get("ach_discount_cents") or 0) for metadata in member_metadata)
        )
    return merged


def _server_payment_method_metadata(funding_type: str | None) -> dict[str, str]:
    if funding_type != "us_bank_account":
        return {}
    return {
        "funding_type": "us_bank_account",
        "funding_type_source": "server_payment_method",
    }
