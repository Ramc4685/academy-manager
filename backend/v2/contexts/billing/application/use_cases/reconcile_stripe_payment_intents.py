"""Scheduled reconciliation for app-owned invoices paid through Stripe."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from backend.v2.contexts.billing.application.ports import LedgerRepository, StripeGateway
from backend.v2.contexts.billing.application.use_cases.checkout_allocation import (
    allocate_checkout_payment_across_invoices,
)
from backend.v2.contexts.billing.domain.ledger import LedgerInvoice, LedgerPayment
from backend.v2.shared.ids import new_ulid
from backend.v2.shared.tenancy import tenant_scope

# ACH debits typically settle within Stripe's standard ~4 business day window.
# A PI still `processing` past this window is not yet a hard error — Stripe
# hasn't told us it failed — but it is worth a human glancing at, so it is
# surfaced in `stale_ach_processing` rather than silently rolled into the
# healthy in-flight count forever.
ACH_PROCESSING_STALE_AFTER = timedelta(days=5)


class BillingReconciliationRunRepository(Protocol):
    async def record_run(self, **kwargs: Any) -> None: ...


class ConnectedAccountRepositoryPort(Protocol):
    """Structural subset of billing's ConnectedAccountRepository this use case needs."""

    async def get_for_academy(self) -> Any: ...


class ReconcileStripePaymentIntents:
    """Repair missed Stripe webhooks for app-owned invoice PaymentIntents."""

    def __init__(
        self,
        *,
        stripe: StripeGateway,
        ledger: LedgerRepository,
        run_recorder: BillingReconciliationRunRepository | None,
        academy_id: str,
        connected_accounts: ConnectedAccountRepositoryPort | None = None,
        clock=lambda: datetime.now(UTC),
    ) -> None:
        self._stripe = stripe
        self._ledger = ledger
        self._run_recorder = run_recorder
        self._academy_id = academy_id
        self._connected_accounts = connected_accounts
        self._now = clock

    async def execute(self, *, limit: int = 100) -> dict[str, Any]:
        run_id = str(new_ulid())
        started_at = self._now()
        counts: dict[str, Any] = {
            "run_id": run_id,
            "academy_id": self._academy_id,
            "scanned": 0,
            "repaired": 0,
            "skipped": 0,
            "quarantined": 0,
            "failed": 0,
            # ACH is asynchronous (§7.2): a PI seen `processing` shortly after
            # charge is a known, non-erroring, pending-settlement state. It is
            # counted here — never in `failed`/`quarantined`/`skipped` — so a
            # healthy reconciliation run doesn't look like it's ignoring ACH.
            "ach_processing_count": 0,
            "stale_ach_processing": [],
            "errors": [],
            "notes": [],
            "started_at": started_at,
            "finished_at": None,
        }
        with tenant_scope(self._academy_id):
            try:
                payment_intents = await self._search_all_payment_intents(limit=limit)
            except Exception as exc:
                counts["failed"] += 1
                counts["errors"].append(f"PaymentIntent search failed: {exc}")
                counts["finished_at"] = self._now()
                if self._run_recorder is not None:
                    await self._run_recorder.record_run(**counts)
                return counts
            for payment_intent in payment_intents:
                counts["scanned"] += 1
                try:
                    status = await self._reconcile_one(payment_intent)
                    if status == "ach_processing":
                        counts["ach_processing_count"] += 1
                        stale = self._stale_ach_processing_entry(payment_intent)
                        if stale is not None:
                            counts["stale_ach_processing"].append(stale)
                    else:
                        counts[status] += 1
                except _QuarantineReconciliation as exc:
                    counts["quarantined"] += 1
                    counts["errors"].append(str(exc))
                except Exception as exc:
                    counts["failed"] += 1
                    counts["errors"].append(str(exc))
        if counts["scanned"] == 0:
            counts["notes"].append(
                "Stripe returned no app-owned PaymentIntents. Checkout payments created before "
                "PaymentIntent metadata was deployed require manual review by Stripe id."
            )
        counts["finished_at"] = self._now()
        if self._run_recorder is not None:
            await self._run_recorder.record_run(**counts)
        return counts

    async def _search_all_payment_intents(self, *, limit: int) -> list[dict[str, Any]]:
        """Search platform-level PIs plus, if onboarded, the academy's own
        Stripe Connect account (Slice I) so connected-account money isn't
        invisible to reconciliation."""
        payment_intents = list(
            await self._stripe.search_app_owned_payment_intents(
                academy_id=self._academy_id,
                limit=limit,
            )
        )
        seen_ids = {str(pi.get("id") or "") for pi in payment_intents}

        if self._connected_accounts is not None:
            connected_account = await self._connected_accounts.get_for_academy()
            stripe_account_id = getattr(connected_account, "stripe_account_id", None)
            if stripe_account_id:
                connected_pis = await self._stripe.search_app_owned_payment_intents(
                    academy_id=self._academy_id,
                    limit=limit,
                    stripe_account=stripe_account_id,
                )
                for pi in connected_pis:
                    pi_id = str(pi.get("id") or "")
                    if pi_id and pi_id in seen_ids:
                        continue
                    seen_ids.add(pi_id)
                    payment_intents.append(pi)

        return payment_intents

    def _stale_ach_processing_entry(self, payment_intent: dict[str, Any]) -> dict[str, Any] | None:
        created_ts = payment_intent.get("created")
        if created_ts is None:
            return None
        try:
            created_at = datetime.fromtimestamp(int(created_ts), tz=UTC)
        except (TypeError, ValueError, OSError):
            return None
        age = self._now() - created_at
        if age < ACH_PROCESSING_STALE_AFTER:
            return None
        return {
            "payment_intent_id": str(payment_intent.get("id") or ""),
            "created_at": created_at,
            "age_days": age.days,
        }

    async def _reconcile_one(self, payment_intent: dict[str, Any]) -> str:
        pi_id = str(payment_intent.get("id") or "")
        if not pi_id:
            raise _QuarantineReconciliation("PaymentIntent missing id")
        status = str(payment_intent.get("status") or "").lower()
        if status == "processing":
            if not _payment_intent_is_ach(payment_intent):
                # A non-ACH PI stuck in `processing` is unusual (card intents
                # resolve near-instantly); leave it for the next run rather
                # than guessing at its final state.
                return "skipped"
            metadata = payment_intent.get("metadata") or {}
            if not isinstance(metadata, dict):
                metadata = {}
            metadata_academy_id = str(metadata.get("academy_id") or "")
            if metadata_academy_id and metadata_academy_id != self._academy_id:
                raise _QuarantineReconciliation(
                    f"academy mismatch: payment_intent={metadata_academy_id} "
                    f"expected={self._academy_id}"
                )
            # ACH-in-flight: do NOT create a LedgerPayment or expect the
            # invoice to be paid yet — settlement hasn't happened. Slice G's
            # webhook handler (`_handle_autopay_pi_processing`) already
            # records the attempt; reconciliation only needs to classify this
            # PI as known-pending, not repair anything.
            return "ach_processing"
        if status != "succeeded":
            return "skipped"

        metadata = payment_intent.get("metadata") or {}
        if not isinstance(metadata, dict):
            metadata = {}
        metadata_academy_id = str(metadata.get("academy_id") or "")
        if metadata_academy_id and metadata_academy_id != self._academy_id:
            raise _QuarantineReconciliation(
                f"academy mismatch: payment_intent={metadata_academy_id} expected={self._academy_id}"
            )

        invoice_ids = self._invoice_ids_from_metadata(metadata)
        if invoice_ids:
            return await self._reconcile_balance_payment_intent(payment_intent, invoice_ids)

        invoice = await self._resolve_invoice(metadata)
        if invoice is None:
            raise _QuarantineReconciliation(f"app invoice not found for PaymentIntent {pi_id}")
        if invoice.academy_id != self._academy_id:
            raise _QuarantineReconciliation(
                f"academy mismatch: invoice={invoice.academy_id} expected={self._academy_id}"
            )
        metadata_parent_id = str(metadata.get("parent_id") or "")
        if metadata_parent_id and metadata_parent_id != invoice.parent_id:
            raise _QuarantineReconciliation(
                f"parent mismatch: invoice={invoice.parent_id} payment_intent={metadata_parent_id}"
            )

        amount_cents = int(payment_intent.get("amount") or 0)
        if amount_cents <= 0:
            raise _QuarantineReconciliation(f"PaymentIntent {pi_id} has no positive amount")
        currency = str(payment_intent.get("currency") or invoice.currency).lower()
        if currency != invoice.currency.lower():
            raise _QuarantineReconciliation(
                f"currency mismatch: invoice={invoice.currency} payment_intent={currency}"
            )

        allocation_key = f"stripe-reconcile-alloc:{pi_id}"
        existing_allocation = await self._ledger.get_payment_allocation_by_idempotency_key(
            allocation_key
        )
        if existing_allocation is not None:
            if existing_allocation.invoice_id != invoice.invoice_id:
                raise _QuarantineReconciliation(
                    "duplicate Stripe obligation: PaymentIntent already allocated "
                    f"to {existing_allocation.invoice_id}"
                )
            return "skipped"

        existing_payment = await self._ledger.get_payment_by_stripe_payment_intent_id(pi_id)
        if existing_payment is not None:
            if existing_payment.parent_id != invoice.parent_id:
                raise _QuarantineReconciliation(
                    "duplicate Stripe obligation: PaymentIntent belongs to another parent"
                )
            # A webhook (or a prior reconciliation run) already recorded this
            # PaymentIntent as a ledger payment. Skip to avoid inserting a
            # duplicate, unapplied ledger payment (phantom credit).
            return "skipped"

        now = self._now()
        payment = await self._ledger.record_payment(
            LedgerPayment(
                payment_id=f"ledger-pay-reconcile:{pi_id}",
                academy_id=invoice.academy_id,
                parent_id=invoice.parent_id,
                amount_cents=amount_cents,
                unapplied_amount_cents=amount_cents,
                currency=currency,
                status="succeeded",
                payment_method="stripe_autopay",
                stripe_payment_intent_id=pi_id,
                stripe_invoice_id=str(metadata.get("stripe_invoice_id") or "") or None,
                paid_at=now,
                recorded_by="stripe_reconciliation",
                created_at=now,
                updated_at=now,
            ),
            idempotency_key=f"stripe-reconcile-pi:{pi_id}",
        )
        await self._ledger.allocate_payment(
            payment_id=payment.payment_id,
            invoice_id=invoice.invoice_id,
            amount_cents=amount_cents,
            idempotency_key=allocation_key,
        )
        return "repaired"

    async def _reconcile_balance_payment_intent(
        self, payment_intent: dict[str, Any], invoice_ids: list[str]
    ) -> str:
        pi_id = str(payment_intent.get("id") or "")
        metadata = payment_intent.get("metadata") or {}
        if not isinstance(metadata, dict):
            metadata = {}
        metadata_parent_id = str(metadata.get("parent_id") or "")

        amount_cents = int(payment_intent.get("amount") or 0)
        if amount_cents <= 0:
            raise _QuarantineReconciliation(f"PaymentIntent {pi_id} has no positive amount")
        currency = str(payment_intent.get("currency") or "usd").lower()

        invoices: list[LedgerInvoice] = []
        for invoice_id in sorted(invoice_ids):
            invoice = await self._ledger.get_invoice(invoice_id)
            if invoice is None:
                raise _QuarantineReconciliation(f"app invoice {invoice_id} not found")
            if invoice.academy_id != self._academy_id:
                raise _QuarantineReconciliation(
                    f"academy mismatch: invoice={invoice.academy_id} expected={self._academy_id}"
                )
            if metadata_parent_id and metadata_parent_id != invoice.parent_id:
                raise _QuarantineReconciliation(
                    f"parent mismatch: invoice={invoice.parent_id} payment_intent={metadata_parent_id}"
                )
            if currency != invoice.currency.lower():
                raise _QuarantineReconciliation(
                    f"currency mismatch: invoice={invoice.currency} payment_intent={currency}"
                )
            invoices.append(invoice)

        existing_payment = await self._ledger.get_payment_by_stripe_payment_intent_id(pi_id)
        if existing_payment is not None:
            if metadata_parent_id and existing_payment.parent_id != metadata_parent_id:
                raise _QuarantineReconciliation(
                    "duplicate Stripe obligation: PaymentIntent belongs to another parent"
                )
            # A webhook (or a prior reconciliation run) already recorded this
            # PaymentIntent as a ledger payment. Skip to avoid inserting a
            # duplicate, unapplied ledger payment (phantom credit).
            return "skipped"

        now = self._now()
        payment = await self._ledger.record_payment(
            LedgerPayment(
                payment_id=f"ledger-pay-reconcile:{pi_id}",
                academy_id=self._academy_id,
                parent_id=metadata_parent_id or invoices[0].parent_id,
                amount_cents=amount_cents,
                unapplied_amount_cents=amount_cents,
                currency=currency,
                status="succeeded",
                payment_method="stripe_checkout",
                stripe_payment_intent_id=pi_id,
                stripe_invoice_id=str(metadata.get("stripe_invoice_id") or "") or None,
                paid_at=now,
                recorded_by="stripe_reconciliation",
                created_at=now,
                updated_at=now,
            ),
            idempotency_key=f"stripe-reconcile-pi:{pi_id}",
        )

        repaired = await allocate_checkout_payment_across_invoices(
            ledger=self._ledger,
            payment=payment,
            invoices=invoices,
            amount_cents=amount_cents,
            allocation_key_prefix=f"stripe-reconcile-alloc:{pi_id}",
            conflict_error=_QuarantineReconciliation,
        )
        return "repaired" if repaired > 0 else "skipped"

    async def _resolve_invoice(self, metadata: dict[Any, Any]) -> LedgerInvoice | None:
        invoice_id = str(metadata.get("invoice_id") or "")
        if invoice_id:
            return await self._ledger.get_invoice(invoice_id)

        enrollment_id = str(metadata.get("enrollment_id") or "")
        period = str(metadata.get("period") or metadata.get("billing_period") or "")
        if enrollment_id and period:
            return await self._ledger.get_invoice_for_enrollment_period(
                enrollment_id,
                period,
                statuses={"open", "partially_paid", "paid"},
            )
        return None

    @staticmethod
    def _invoice_ids_from_metadata(metadata: dict[Any, Any]) -> list[str]:
        raw_invoice_ids = str(metadata.get("invoice_ids") or "")
        if not raw_invoice_ids:
            return []
        invoice_ids = [item.strip() for item in raw_invoice_ids.split(",") if item.strip()]
        return sorted(dict.fromkeys(invoice_ids))


class _QuarantineReconciliation(Exception):
    pass


def _payment_intent_is_ach(payment_intent: dict[str, Any]) -> bool:
    """Mirror `handle_webhook_event._payment_intent_is_ach` — a `processing`
    PaymentIntent is only the expected ACH in-flight state when it is
    actually funded by `us_bank_account`. Any other funding type left
    `processing` is unusual and should not be silently reclassified."""
    method_types = payment_intent.get("payment_method_types")
    if isinstance(method_types, list) and "us_bank_account" in method_types:
        return True
    details = payment_intent.get("payment_method_details")
    if isinstance(details, dict):
        return details.get("type") == "us_bank_account" or isinstance(
            details.get("us_bank_account"), dict
        )
    return False
