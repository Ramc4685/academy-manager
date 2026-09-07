"""Composition for the admin Billing Health page (``/admin/billing-health``).

Spec: ``docs/superpowers/specs/2026-09-07-billing-health-trim-design.md`` §5.

Lives outside ``composition/admin.py`` because that module sits at its wiring
line budget. Pure wiring: every repository resolves the tenant from
``current_academy_id()`` at request time, so nothing tenant-specific is
captured here.

The one piece of judgement on this surface — the single health verdict — lives
in ``contexts/billing/application/billing_health.py``; this module only feeds
it the facts and hands the result to the route.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from backend.v2.contexts.billing.application.billing_health import (
    LastReconciliationRun,
    evaluate_billing_health,
)
from backend.v2.contexts.billing.application.ports import StripeGateway
from backend.v2.contexts.billing.application.use_cases.match_legacy_invoices import (
    ConfirmLegacyMatch,
    ConfirmLegacyMatchCommand,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_ledger_repo import (
    MongoBillingLedgerRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_settings_repo import (
    MongoBillingSettingsRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_connected_account_repo import (
    MongoConnectedAccountRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_dunning_state_repo import (
    MongoDunningStateRepository,
)
from backend.v2.contexts.identity.application.get_academy_gateway_use_case import (
    mask_stripe_account_id,
)

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class AdminBillingHealth:
    """Everything the Billing Health page and its actions need."""

    get_connect_readiness: Callable[[], Awaitable[dict[str, Any]]]
    list_reconciliation_runs: Callable[[], Awaitable[list[dict[str, Any]]]]
    run_reconciliation: Callable[[], Awaitable[dict[str, Any]]]
    list_billing_webhook_events: Callable[..., Awaitable[list[dict[str, Any]]]]
    replay_webhook_event: Callable[[str], Awaitable[bool]]
    get_billing_reconciliation_report: Callable[..., Awaitable[dict[str, Any]]]
    confirm_legacy_match: Callable[..., Awaitable[dict[str, Any]]]


def compose_admin_billing_health(db: Any, stripe: StripeGateway) -> AdminBillingHealth:
    billing_ledger_repo = MongoBillingLedgerRepository(db)
    billing_settings_repo = MongoBillingSettingsRepository(db)
    connected_accounts_repo = MongoConnectedAccountRepository(db)
    dunning_state_repo = MongoDunningStateRepository(db)

    async def get_connect_readiness() -> dict[str, Any]:
        """Can a parent payment physically succeed right now, and is Stripe well?

        Every parent payment is gated on one condition — an `active` connected
        account with `charges_enabled` — or on the platform-charge fallback
        being switched on (issue #432).

        The health verdict (spec 2026-09-07 §4.2) is computed here rather than
        on the page: the page used to derive "System healthy" from backlog
        counts alone and could render a green pill above a red "Parents cannot
        pay right now" card. Counts come from aggregates, never from the
        50-capped list route, so the pill and the tile beside it cannot
        disagree. Every check but the Connect read degrades on its own: a
        failing one contributes no reason code and instead makes the headline
        say what could not be checked.
        """
        from backend.v2.contexts.billing.infrastructure.mongo_billing_reconciliation_run_repo import (
            MongoBillingReconciliationRunRepository,
        )
        from backend.v2.contexts.billing.infrastructure.mongo_stripe_dedup import (
            MongoStripeEventDedup,
        )
        from backend.v2.shared.tenancy import current_academy_id

        request_academy_id = current_academy_id()

        account = await connected_accounts_repo.get_for_academy()
        try:
            settings_doc = await billing_settings_repo.get()
            fallback_allowed = bool(settings_doc.allow_platform_charge_fallback)
        except Exception:
            # Match the charge path, which fails closed on a settings read
            # error. Reporting "fallback is on" when we do not know would
            # tell the owner payments are fine when they may not be.
            log.warning("connect_readiness_settings_read_failed", exc_info=True)
            fallback_allowed = False

        unavailable: list[str] = []

        try:
            stuck = await MongoStripeEventDedup(db).count_stuck_by_status(
                academy_id=request_academy_id
            )
        except Exception:
            log.warning("connect_readiness_webhook_counts_failed", exc_info=True)
            stuck = {"quarantined": 0, "failed": 0}
            unavailable.append("the webhook backlog")

        last_run: LastReconciliationRun | None = None
        try:
            runs = await MongoBillingReconciliationRunRepository(db).list_runs(
                request_academy_id, limit=1
            )
            if runs:
                last_run = LastReconciliationRun(
                    finished_at=_as_utc(runs[0].get("finished_at")),
                    failed=int(runs[0].get("failed") or 0),
                    quarantined=int(runs[0].get("quarantined") or 0),
                )
        except Exception:
            log.warning("connect_readiness_reconciliation_runs_failed", exc_info=True)
            unavailable.append("the reconciliation history")

        try:
            disable_failures = await dunning_state_repo.list_autopay_disable_failures()
        except Exception:
            log.warning("connect_readiness_autopay_disable_failures_failed", exc_info=True)
            disable_failures = {"count": 0, "rows": [], "truncated": False}
            unavailable.append("the autopay switch-off backlog")

        ready = bool(account and account.is_ready_for_charges())
        payments_possible = ready or fallback_allowed

        verdict = evaluate_billing_health(
            payments_possible=payments_possible,
            connected_account_ready=ready,
            quarantined_webhooks=int(stuck.get("quarantined") or 0),
            last_run=last_run,
            autopay_disable_failures=int(disable_failures.get("count") or 0),
            now=datetime.now(UTC),
            unavailable_checks=unavailable,
        )

        return {
            "connected_account": {
                "configured": account is not None,
                "status": account.status if account else None,
                "charges_enabled": bool(account and account.charges_enabled),
                "payouts_enabled": bool(account and account.payouts_enabled),
                "ready_for_charges": ready,
                # Same masking as GET /admin/academy/gateway — the account id
                # is a Stripe identifier, not a secret, but there is no reason
                # for two admin surfaces to disagree about showing it.
                "account_id_masked": mask_stripe_account_id(
                    account.stripe_account_id if account else None
                ),
            },
            "allow_platform_charge_fallback": fallback_allowed,
            # The headline the card leads with: charges route to the academy's
            # account when ready, and otherwise only succeed at all if the
            # platform fallback is on — in which case the money lands on the
            # platform account instead of theirs.
            "payments_possible": payments_possible,
            "funds_route_to_academy": ready,
            "webhook_events": stuck,
            "autopay_disable_failures": disable_failures,
            "health": verdict.as_dict(),
        }

    async def list_reconciliation_runs() -> list[dict[str, Any]]:
        from backend.v2.contexts.billing.infrastructure.mongo_billing_reconciliation_run_repo import (
            MongoBillingReconciliationRunRepository,
        )
        from backend.v2.shared.tenancy import current_academy_id

        repo = MongoBillingReconciliationRunRepository(db)
        return await repo.list_runs(current_academy_id(), limit=10)

    async def run_reconciliation() -> dict[str, Any]:
        from backend.v2.contexts.billing.application.use_cases.reconcile_stripe_payment_intents import (
            ReconcileStripePaymentIntents,
        )
        from backend.v2.contexts.billing.infrastructure.mongo_billing_reconciliation_run_repo import (
            MongoBillingReconciliationRunRepository,
        )
        from backend.v2.shared.tenancy import current_academy_id

        if not hasattr(stripe, "search_app_owned_payment_intents"):
            raise RuntimeError("Stripe reconciliation not configured")
        return await ReconcileStripePaymentIntents(
            stripe=stripe,
            ledger=billing_ledger_repo,
            run_recorder=MongoBillingReconciliationRunRepository(db),
            academy_id=current_academy_id(),
            connected_accounts=connected_accounts_repo,
        ).execute(limit=100)

    async def replay_webhook_event(event_id: str) -> bool:
        from backend.v2.contexts.billing.infrastructure.mongo_stripe_dedup import (
            MongoStripeEventDedup,
        )
        from backend.v2.shared.tenancy import current_academy_id

        dedup = MongoStripeEventDedup(db)
        replayed = await dedup.replay(event_id, academy_id=current_academy_id())
        if not replayed:
            raise ValueError("quarantined event not found")
        return True

    async def confirm_legacy_match(
        *,
        invoice_id: str,
        stripe_charge_id: str,
        amount_cents: int,
        stripe_payment_intent_id: str | None,
        paid_at: datetime | None,
        recorded_by: str | None,
    ) -> dict[str, Any]:
        result = await ConfirmLegacyMatch(ledger=billing_ledger_repo).execute(
            ConfirmLegacyMatchCommand(
                invoice_id=invoice_id,
                stripe_charge_id=stripe_charge_id,
                amount_cents=amount_cents,
                stripe_payment_intent_id=stripe_payment_intent_id,
                paid_at=paid_at,
                recorded_by=recorded_by,
            )
        )
        return result.model_dump(mode="python")

    async def list_billing_webhook_events(
        *, status: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        from backend.v2.shared.tenancy import current_academy_id

        request_academy_id = current_academy_id()
        query: dict[str, Any] = {"academy_id": request_academy_id}
        if status:
            query["status"] = status
        else:
            query["status"] = {"$in": ["failed", "quarantined"]}
        rows = []
        cursor = db["stripe_webhook_events"].find(
            query,
            sort=[("last_attempt_at", -1), ("received_at", -1), ("event_id", 1)],
            limit=max(1, min(int(limit), 100)),
        )
        async for doc in cursor:
            rows.append(
                {
                    "event_id": str(doc.get("event_id") or ""),
                    "event_type": str(doc.get("event_type") or ""),
                    "status": str(doc.get("status") or ""),
                    "object_id": doc.get("object_id"),
                    "object_type": doc.get("object_type"),
                    "received_at": doc.get("received_at"),
                    "last_attempt_at": doc.get("last_attempt_at"),
                    "retry_count": int(doc.get("retry_count") or 0),
                    "error_message": doc.get("error_message") or doc.get("error"),
                }
            )
        return rows

    async def get_billing_reconciliation_report(
        *,
        stripe_invoice_id: str | None = None,
        payment_intent_id: str | None = None,
    ) -> dict[str, Any]:
        from backend.v2.shared.tenancy import current_academy_id

        request_academy_id = current_academy_id()
        checked_at = datetime.now(UTC)
        stripe_invoice: dict[str, Any] = {}
        stripe_payment_intent: dict[str, Any] = {}
        stripe_customer_id: str | None = None

        retrieve_invoice = getattr(stripe, "retrieve_invoice", None)
        if stripe_invoice_id and retrieve_invoice is not None:
            stripe_invoice = await retrieve_invoice(stripe_invoice_id)
            payment_intent_id = (
                payment_intent_id or str(stripe_invoice.get("payment_intent") or "") or None
            )
            stripe_customer_id = str(stripe_invoice.get("customer") or "") or None

        retrieve_payment_intent = getattr(stripe, "retrieve_payment_intent", None)
        if payment_intent_id and retrieve_payment_intent is not None:
            stripe_payment_intent = await retrieve_payment_intent(payment_intent_id)
            stripe_customer_id = (
                stripe_customer_id or str(stripe_payment_intent.get("customer") or "") or None
            )

        local_invoice = None
        if stripe_invoice_id:
            local_invoice = await db["invoices"].find_one(
                {"academy_id": request_academy_id, "stripe_invoice_id": stripe_invoice_id}
            )
        stripe_invoice_metadata = (
            stripe_invoice.get("metadata")
            if isinstance(stripe_invoice.get("metadata"), dict)
            else {}
        ) or {}
        duplicate_obligation_invoice = None
        if stripe_invoice_id:
            matching_invoices = (
                await db["invoices"]
                .find(
                    {
                        "academy_id": request_academy_id,
                        "stripe_invoice_id": stripe_invoice_id,
                    },
                    {"invoice_id": 1, "stripe_invoice_id": 1},
                )
                .to_list(length=2)
            )
            if len(matching_invoices) > 1:
                duplicate_obligation_invoice = matching_invoices[0]
            elif local_invoice is None:
                obligation_query: dict[str, Any] = {"academy_id": request_academy_id}
                for field in ("enrollment_id", "period", "parent_id", "student_id"):
                    value = stripe_invoice_metadata.get(field)
                    if value:
                        obligation_query[field] = str(value)
                if len(obligation_query) > 1:
                    obligation_query["status"] = {"$in": ["open", "partially_paid", "paid"]}
                    obligation_query["stripe_invoice_id"] = {"$ne": stripe_invoice_id}
                    duplicate_obligation_invoice = await db["invoices"].find_one(
                        obligation_query,
                        sort=[("created_at", -1), ("invoice_id", 1)],
                    )
                    if duplicate_obligation_invoice is not None:
                        local_invoice = duplicate_obligation_invoice

        ledger_payment_query: dict[str, Any] = {"academy_id": request_academy_id}
        if stripe_invoice_id and payment_intent_id:
            ledger_payment_query["$or"] = [
                {"stripe_invoice_id": stripe_invoice_id},
                {"stripe_payment_intent_id": payment_intent_id},
            ]
        elif stripe_invoice_id:
            ledger_payment_query["stripe_invoice_id"] = stripe_invoice_id
        elif payment_intent_id:
            ledger_payment_query["stripe_payment_intent_id"] = payment_intent_id
        ledger_payment = await db["ledger_payments"].find_one(ledger_payment_query)

        allocation = None
        if ledger_payment is not None:
            allocation = await db["payment_allocations"].find_one(
                {
                    "academy_id": request_academy_id,
                    "payment_id": ledger_payment.get("payment_id"),
                }
            )
            if local_invoice is None and allocation is not None:
                local_invoice = await db["invoices"].find_one(
                    {
                        "academy_id": request_academy_id,
                        "invoice_id": allocation.get("invoice_id"),
                    }
                )

        mismatches: list[dict[str, Any]] = []
        if duplicate_obligation_invoice is not None:
            mismatches.append(
                {
                    "code": "DUPLICATE_OBLIGATION",
                    "message": "Stripe invoice maps to an already-existing local obligation",
                    "stripe_value": stripe_invoice_id,
                    "local_value": duplicate_obligation_invoice.get("stripe_invoice_id"),
                }
            )
        elif stripe_invoice_id and local_invoice is None:
            mismatches.append(
                {
                    "code": "MISSING_LOCAL_INVOICE",
                    "message": "Stripe invoice has no matching LedgerInvoice",
                    "stripe_value": stripe_invoice_id,
                    "local_value": None,
                }
            )
        if local_invoice is not None and ledger_payment is None:
            mismatches.append(
                {
                    "code": "MISSING_LEDGER_PAYMENT",
                    "message": "LedgerInvoice has no matching LedgerPayment",
                    "stripe_value": stripe_invoice_id or payment_intent_id,
                    "local_value": None,
                }
            )
        if ledger_payment is not None and allocation is None:
            mismatches.append(
                {
                    "code": "MISSING_ALLOCATION",
                    "message": "LedgerPayment has no PaymentAllocation",
                    "stripe_value": stripe_invoice_id or payment_intent_id,
                    "local_value": ledger_payment.get("payment_id"),
                }
            )

        stripe_payment_succeeded = (
            str(stripe_payment_intent.get("status") or "").lower() == "succeeded"
        )
        stripe_amount = int(
            stripe_invoice.get("amount_paid")
            or stripe_invoice.get("amount_due")
            or stripe_payment_intent.get("amount")
            or 0
        )
        stripe_currency = str(
            stripe_invoice.get("currency") or stripe_payment_intent.get("currency") or "usd"
        ).lower()
        manual_review_candidates: list[dict[str, Any]] = []
        if (
            payment_intent_id
            and stripe_payment_succeeded
            and local_invoice is None
            and ledger_payment is None
            and allocation is None
        ):
            mismatches.append(
                {
                    "code": "ORPHAN_STRIPE_PAYMENT",
                    "message": "Stripe PaymentIntent succeeded without local ledger records",
                    "stripe_value": payment_intent_id,
                    "local_value": None,
                }
            )
            customer_parent = None
            if stripe_customer_id:
                customer_parent = await db["parent_billing_customers"].find_one(
                    {
                        "academy_id": request_academy_id,
                        "stripe_customer_id": stripe_customer_id,
                    },
                    {"parent_id": 1},
                )
            parent_id = str(customer_parent.get("parent_id") or "") if customer_parent else ""
            if parent_id and stripe_amount > 0:
                candidate_cursor = db["invoices"].find(
                    {
                        "academy_id": request_academy_id,
                        "parent_id": parent_id,
                        "status": {"$in": ["open", "partially_paid"]},
                        "balance_due_cents": stripe_amount,
                        "currency": stripe_currency,
                    },
                    sort=[("created_at", -1), ("invoice_id", 1)],
                    limit=10,
                )
                async for candidate in candidate_cursor:
                    manual_review_candidates.append(
                        {
                            "invoice_id": str(candidate.get("invoice_id") or ""),
                            "parent_id": parent_id,
                            "student_id": candidate.get("student_id"),
                            "enrollment_id": candidate.get("enrollment_id"),
                            "period": candidate.get("period"),
                            "amount_cents": int(candidate.get("balance_due_cents") or 0),
                            "currency": str(candidate.get("currency") or stripe_currency),
                            "status": str(candidate.get("status") or ""),
                            "reason": (
                                "same Stripe customer, open invoice balance, currency, "
                                "and amount; requires admin confirmation"
                            ),
                        }
                    )
        if local_invoice is not None and stripe_amount:
            local_total = int(local_invoice.get("total_cents") or 0)
            if local_total and local_total != stripe_amount:
                mismatches.append(
                    {
                        "code": "AMOUNT_MISMATCH",
                        "message": "Stripe amount differs from ledger invoice total",
                        "stripe_value": stripe_amount,
                        "local_value": local_total,
                    }
                )

        stripe_paid = (
            str(stripe_invoice.get("status") or "").lower() == "paid"
            or str(stripe_invoice.get("paid") or "").lower() == "true"
            or str(stripe_payment_intent.get("status") or "").lower() == "succeeded"
        )
        if local_invoice is not None and stripe_paid and local_invoice.get("status") != "paid":
            mismatches.append(
                {
                    "code": "STATUS_MISMATCH",
                    "message": "Stripe is paid but LedgerInvoice is not paid",
                    "stripe_value": "paid",
                    "local_value": local_invoice.get("status"),
                }
            )

        result = "MATCH" if not mismatches else str(mismatches[0]["code"])
        return {
            "result": result,
            "stripe_invoice_id": stripe_invoice_id,
            "payment_intent_id": payment_intent_id,
            "stripe_customer_id": stripe_customer_id,
            "local_invoice_id": str(local_invoice.get("invoice_id"))
            if local_invoice is not None
            else None,
            "ledger_payment_id": str(ledger_payment.get("payment_id"))
            if ledger_payment is not None
            else None,
            "payment_allocation_id": str(allocation.get("allocation_id"))
            if allocation is not None
            else None,
            "mismatches": mismatches,
            "manual_review_candidates": manual_review_candidates,
            "checked_at": checked_at,
        }

    return AdminBillingHealth(
        get_connect_readiness=get_connect_readiness,
        list_reconciliation_runs=list_reconciliation_runs,
        run_reconciliation=run_reconciliation,
        list_billing_webhook_events=list_billing_webhook_events,
        replay_webhook_event=replay_webhook_event,
        get_billing_reconciliation_report=get_billing_reconciliation_report,
        confirm_legacy_match=confirm_legacy_match,
    )


def _as_utc(value: Any) -> datetime | None:
    """Mongo hands timestamps back naive; the verdict compares them to ``now``."""
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
