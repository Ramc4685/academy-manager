"""Monthly billing generation extracted from MongoPaymentRepository.

Pure code motion: `MongoMonthlyBillingGenerator` holds the monthly-generation
machinery (deferral skips, invoice-key idempotency, ledger dual-write, orphan
repair) plus the module-level proration helpers that only the generation path
uses. `MongoPaymentRepository.generate_monthly_payments` delegates here so
the legacy adapter keeps shrinking toward deletion.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from pymongo.errors import DuplicateKeyError

from backend.v2.contexts.billing.application.use_cases.admin_payment_ops import (
    GenerateMonthlyPaymentsResult,
    MonthlyGenerationSkippedDetail,
)
from backend.v2.contexts.billing.domain.billing_settings import BillingSettings
from backend.v2.contexts.billing.domain.ledger import InvoiceLine, LedgerInvoice
from backend.v2.contexts.billing.domain.models import AppliedCreditState
from backend.v2.contexts.billing.domain.proration import (
    BillingCalculationSnapshot,
    BillingPeriod,
    ClassOccurrence,
    FirstMonthProrationPolicy,
    schedule_signature,
)
from backend.v2.contexts.billing.domain.tuition_discount import (
    TuitionDiscount,
    display_label,
    monthly_discount_cents,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_settings_repo import (
    MongoBillingSettingsRepository,
)
from backend.v2.shared.ids import new_ulid
from backend.v2.shared.observability.ops_alerts import capture_message
from backend.v2.shared.tenancy import current_academy_id

if TYPE_CHECKING:
    from backend.v2.contexts.billing.infrastructure.mongo_payment_repo import (
        MongoPaymentRepository,
    )


class MongoMonthlyBillingGenerator:
    """Monthly payment/invoice generation over the legacy payment repository.

    Constructed per-call by MongoPaymentRepository.generate_monthly_payments;
    borrows the repo's db handle, clock, credit ledger, ledger repo, and
    tenant-scoped payment lookups so behavior is identical to the pre-move code.
    """

    def __init__(self, repo: MongoPaymentRepository) -> None:
        self._repo = repo
        self._db = repo._db
        self._clock = repo._clock
        self._credit_ledger = repo._credit_ledger
        self._ledger_repo = repo._ledger_repo
        # Resolved once per generation run (see generate_monthly_payments) so
        # every invoice in a run shares one grace window even if the run
        # straddles midnight or an admin edits the setting mid-run.
        self._invoice_due_days = BillingSettings.default("").invoice_due_days

    async def _load_invoice_due_days(self) -> int:
        """Read this academy's grace window, falling back to the model default.

        Settings are advisory for generation: a missing or unreadable
        billing_settings doc must never block the monthly run, so any failure
        degrades to the default rather than raising.
        """
        try:
            settings = await MongoBillingSettingsRepository(self._db).get()
        except Exception:
            logging.getLogger(__name__).warning(
                "monthly_generation_billing_settings_unreadable; using default due days",
                exc_info=True,
            )
            return BillingSettings.default("").invoice_due_days
        return settings.invoice_due_days

    @staticmethod
    def _monthly_invoice_id(enrollment_id: str, period: str) -> str:
        return f"inv-monthly-{enrollment_id}-{period}"

    @staticmethod
    def _monthly_invoice_line_id(enrollment_id: str, period: str) -> str:
        return f"line-monthly-{enrollment_id}-{period}"

    @staticmethod
    def _date_str(value: object) -> str | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.date().isoformat()
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, str) and value:
            return value[:10]
        return None

    async def _active_billing_deferral_detail(
        self,
        *,
        academy_id: str,
        enrollment: dict[str, object],
        student_doc: dict[str, object] | None,
        period: str,
        today: date,
    ) -> MonthlyGenerationSkippedDetail | None:
        enrollment_id = str(enrollment.get("enrollment_id") or enrollment.get("_id"))
        cursor = self._db["enrollment_billing_deferrals"].find(
            {
                "academy_id": academy_id,
                "enrollment_id": enrollment_id,
                "status": "active",
                "billing_period": period,
            },
            sort=[("created_at", -1)],
            limit=10,
        )
        today_text = today.isoformat()
        async for doc in cursor:
            resume_on = self._date_str(doc.get("resume_on"))
            if resume_on is not None and resume_on <= today_text:
                continue
            review_on = self._date_str(doc.get("review_on"))
            if review_on is not None and review_on <= today_text:
                continue
            expires_on = self._date_str(doc.get("expires_on"))
            if expires_on is not None and expires_on < today_text:
                continue
            return self._skipped_detail_from_deferral(
                enrollment=enrollment,
                student_doc=student_doc,
                period=period,
                deferral=doc,
            )
        return None

    def _skipped_detail_from_deferral(
        self,
        *,
        enrollment: dict[str, object],
        student_doc: dict[str, object] | None,
        period: str,
        deferral: dict[str, object],
    ) -> MonthlyGenerationSkippedDetail:
        review_on = self._date_str(deferral.get("review_on"))
        today = self._clock().date()
        return MonthlyGenerationSkippedDetail(
            enrollment_id=str(enrollment.get("enrollment_id") or enrollment.get("_id")),
            student_id=str(enrollment.get("student_id") or deferral.get("student_id") or ""),
            student_name=str((student_doc or {}).get("full_name") or "") or None,
            reason_code=str(deferral.get("deferral_type") or "manual_skip"),
            source=str(deferral.get("source") or "enrollment_billing_deferrals"),
            billing_period=period,
            resume_on=self._date_str(deferral.get("resume_on")),
            review_on=review_on,
            expires_on=self._date_str(deferral.get("expires_on")),
            needs_review=bool(review_on is not None and review_on <= today.isoformat()),
            metadata={
                str(k): str(v)
                for k, v in (deferral.get("metadata") or {}).items()
                if k is not None and v is not None
            }
            | (
                {"deferral_id": str(deferral.get("deferral_id"))}
                if deferral.get("deferral_id") is not None
                else {}
            ),
        )

    def _legacy_skip_period_detail(
        self,
        *,
        enrollment: dict[str, object],
        student_doc: dict[str, object] | None,
        period: str,
    ) -> MonthlyGenerationSkippedDetail:
        return MonthlyGenerationSkippedDetail(
            enrollment_id=str(enrollment.get("enrollment_id") or enrollment.get("_id")),
            student_id=str(enrollment.get("student_id") or ""),
            student_name=str((student_doc or {}).get("full_name") or "") or None,
            reason_code="legacy_skip_period",
            source="enrollment.skip_periods",
            billing_period=period,
            needs_review=True,
            metadata={"compatibility": "missing deferral metadata"},
        )

    async def _dual_write_ledger_invoice(
        self,
        *,
        ledger_repo: Any,
        payment_id: str,
        enrollment_id: str,
        parent_id: str,
        student_id: str,
        period: str,
        gross_cents: int,
        discount_cents: int = 0,
        total_cents: int | None = None,
        discount_policy: TuitionDiscount | None = None,
        now: datetime,
    ) -> None:
        """Write a LedgerInvoice for a monthly-generated enrollment charge.

        Uses a deterministic invoice_id for idempotency so re-runs are safe.
        """
        _log = logging.getLogger(__name__)
        invoice_id = self._monthly_invoice_id(enrollment_id, period)
        idempotency_key = f"monthly-ledger-{enrollment_id}-{period}"
        academy_id = current_academy_id()

        # due_date = generation date + the academy's grace window (issue #288
        # R4). Anchoring to the generation date rather than the period's last
        # day guarantees every invoice gets the full grace window before the
        # dunning ladder's first autopay attempt fires on the due date, even
        # when a period is generated late or backfilled by an admin.
        due_date = now.date() + timedelta(days=self._invoice_due_days)

        invoice = LedgerInvoice(
            invoice_id=invoice_id,
            academy_id=academy_id,
            parent_id=parent_id,
            student_id=student_id or None,
            enrollment_id=enrollment_id,
            period=period,
            status="open",
            subtotal_cents=gross_cents,
            discount_cents=discount_cents,
            total_cents=total_cents
            if total_cents is not None
            else max(gross_cents - discount_cents, 0),
            balance_due_cents=total_cents
            if total_cents is not None
            else max(gross_cents - discount_cents, 0),
            currency="usd",
            due_date=due_date,
            created_at=now,
            updated_at=now,
        )
        line = InvoiceLine(
            line_id=self._monthly_invoice_line_id(enrollment_id, period),
            academy_id=academy_id,
            invoice_id=invoice_id,
            line_type="tuition",
            description=f"Monthly tuition {period}",
            quantity=1,
            unit_amount_cents=gross_cents,
            amount_cents=gross_cents,
            source_type="payment",
            source_id=payment_id,
            created_at=now,
        )
        lines = [line]
        if discount_policy is not None and discount_cents > 0:
            label = display_label(discount_policy)
            description = label if label.lower().endswith("discount") else f"{label} discount"
            lines.append(
                InvoiceLine(
                    line_id=f"{self._monthly_invoice_line_id(enrollment_id, period)}-discount",
                    academy_id=academy_id,
                    invoice_id=invoice_id,
                    line_type="discount",
                    description=description,
                    quantity=1,
                    unit_amount_cents=-discount_cents,
                    amount_cents=-discount_cents,
                    source_type="tuition_discount",
                    source_id=discount_policy.discount_id,
                    category=discount_policy.category,
                    category_label=discount_policy.category_label,
                    discount_kind=discount_policy.kind,
                    gross_cents=gross_cents,
                    net_cents=max(gross_cents - discount_cents, 0),
                    created_at=now,
                )
            )
        await ledger_repo.create_invoice(invoice, lines=lines, idempotency_key=idempotency_key)

    async def _mark_monthly_invoice_key(
        self,
        *,
        enrollment_id: str,
        period: str,
        status: str,
        now: datetime,
        repair_error: str | None = None,
    ) -> None:
        update: dict[str, object] = {
            "status": status,
            "updated_at": now,
        }
        if repair_error is not None:
            update["repair_error"] = repair_error
        elif status == "complete":
            update["repair_error"] = None
        await self._db["billing_invoice_keys"].update_one(
            {
                "academy_id": current_academy_id(),
                "enrollment_id": enrollment_id,
                "period": period,
            },
            {"$set": update},
        )

    async def _monthly_invoice_is_complete(
        self,
        *,
        enrollment_id: str,
        period: str,
        gross_cents: int,
        applied_credit_cents: int = 0,
    ) -> bool:
        """Does the monthly invoice for this enrollment/period have the canonical shape?

        The canonical shape (written by both the normal generation path and orphan
        recovery) records the tuition line and the subtotal GROSS, the tuition discount
        in ``discount_cents`` plus its own discount line, and the amount actually owed
        (net of discount AND of any account credit applied to the charge) in
        ``total_cents``. ``applied_credit_cents`` must therefore be supplied by the
        caller: it is not recoverable from the invoice document itself.
        """
        academy_id = current_academy_id()
        invoice_id = self._monthly_invoice_id(enrollment_id, period)
        line_id = self._monthly_invoice_line_id(enrollment_id, period)
        invoice_doc = await self._db["invoices"].find_one(
            {"academy_id": academy_id, "invoice_id": invoice_id}
        )
        if invoice_doc is None:
            return False
        line_doc = await self._db["invoice_lines"].find_one(
            {"academy_id": academy_id, "invoice_id": invoice_id, "line_id": line_id}
        )
        if line_doc is None or int(line_doc.get("amount_cents", -1)) != gross_cents:
            return False
        total_cents = int(invoice_doc.get("total_cents", -1))
        balance_due_cents = int(invoice_doc.get("balance_due_cents", -1))
        discount_cents = int(invoice_doc.get("discount_cents", 0))
        return (
            int(invoice_doc.get("subtotal_cents", -1)) == gross_cents
            and total_cents == max(gross_cents - discount_cents - applied_credit_cents, 0)
            and 0 <= balance_due_cents <= total_cents
        )

    async def _monthly_invoice_applied_credit_cents(
        self,
        *,
        enrollment_id: str,
        period: str,
    ) -> int:
        """Credit applied to the charge behind an already-generated monthly invoice.

        The tuition line carries the originating payment id in ``source_id``, which is
        the key credit applications are recorded under. Reads through
        ``_applied_credit_state`` so the pre-check sees the same source of truth the
        recovery path prices from (#233).
        """
        line_doc = await self._db["invoice_lines"].find_one(
            {
                "academy_id": current_academy_id(),
                "invoice_id": self._monthly_invoice_id(enrollment_id, period),
                "line_id": self._monthly_invoice_line_id(enrollment_id, period),
            }
        )
        payment_id = str((line_doc or {}).get("source_id") or "")
        if not payment_id:
            return 0
        return (await self._applied_credit_state(payment_id)).applied_cents

    async def _reconcile_monthly_invoice_header(
        self,
        *,
        enrollment_id: str,
        period: str,
        gross_cents: int,
        discount_cents: int,
        total_cents: int,
        now: datetime,
    ) -> None:
        """Force a pre-existing monthly invoice header onto the canonical shape.

        ``create_invoice`` never updates an existing header, and when it back-fills a
        missing line it recomputes totals from the lines alone - which knows nothing
        about applied credit and double-subtracts a discount line. Recovery repairs a
        header that predates it, so it restates the header itself. Only the header is
        touched, and only when the lines already match what we expect; a conflicting
        line is left for the caller to report as a failed repair. Allocations already
        recorded against the invoice are preserved.
        """
        if self._ledger_repo is None:
            return
        invoice_id = self._monthly_invoice_id(enrollment_id, period)
        invoice = await self._ledger_repo.get_invoice(invoice_id)
        if invoice is None:
            return
        if (
            invoice.subtotal_cents == gross_cents
            and invoice.discount_cents == discount_cents
            and invoice.total_cents == total_cents
        ):
            return
        lines = await self._ledger_repo.get_lines_for_invoice(invoice_id)
        tuition_cents = sum(
            line.amount_cents for line in lines if line.source_type != "tuition_discount"
        )
        discount_line_cents = sum(
            abs(line.amount_cents) for line in lines if line.source_type == "tuition_discount"
        )
        if tuition_cents != gross_cents or discount_line_cents != discount_cents:
            return
        allocated = max(invoice.total_cents - invoice.balance_due_cents, 0)
        await self._ledger_repo.save_invoice(
            invoice.model_copy(
                update={
                    "subtotal_cents": gross_cents,
                    "discount_cents": discount_cents,
                    "total_cents": total_cents,
                    "balance_due_cents": max(total_cents - allocated, 0),
                    "updated_at": now,
                }
            )
        )

    async def _invoice_has_consistent_lines(
        self,
        *,
        invoice_id: str,
        amount_cents: int | None = None,
    ) -> bool:
        academy_id = current_academy_id()
        invoice_doc = await self._db["invoices"].find_one(
            {
                "academy_id": academy_id,
                "invoice_id": invoice_id,
                "is_deleted": {"$ne": True},
                "status": {"$ne": "void"},
            }
        )
        if invoice_doc is None:
            return False

        subtotal_line_cents = 0
        discount_line_cents = 0
        line_count = 0
        async for line_doc in self._db["invoice_lines"].find(
            {
                "academy_id": academy_id,
                "invoice_id": invoice_id,
            }
        ):
            line_count += 1
            amount = int(line_doc.get("amount_cents", 0))
            if line_doc.get("source_type") == "tuition_discount":
                discount_line_cents += abs(amount)
            else:
                subtotal_line_cents += amount
        if line_count == 0:
            return False

        subtotal_cents = int(invoice_doc.get("subtotal_cents", -1))
        discount_cents = int(invoice_doc.get("discount_cents", 0))
        total_cents = int(invoice_doc.get("total_cents", -1))
        balance_due_cents = int(invoice_doc.get("balance_due_cents", -1))
        return (
            (amount_cents is None or subtotal_line_cents == amount_cents)
            and subtotal_cents == subtotal_line_cents
            and discount_cents == discount_line_cents
            and total_cents == max(subtotal_cents - discount_cents, 0)
            and 0 <= balance_due_cents <= total_cents
        )

    async def _find_existing_invoice_for_enrollment_period(
        self,
        *,
        enrollment_id: str,
        period: str,
    ) -> str | None:
        invoice_doc = await self._db["invoices"].find_one(
            {
                "academy_id": current_academy_id(),
                "enrollment_id": enrollment_id,
                "period": period,
                "is_deleted": {"$ne": True},
                "status": {"$ne": "void"},
            },
            sort=[("created_at", -1), ("invoice_id", -1)],
        )
        if invoice_doc is None:
            return None
        return str(invoice_doc.get("invoice_id") or "")

    async def _upsert_complete_monthly_invoice_key(
        self,
        *,
        enrollment_id: str,
        period: str,
        now: datetime,
    ) -> None:
        await self._db["billing_invoice_keys"].update_one(
            {
                "academy_id": current_academy_id(),
                "enrollment_id": enrollment_id,
                "period": period,
            },
            {
                "$set": {
                    "status": "complete",
                    "updated_at": now,
                    "repair_error": None,
                },
                "$setOnInsert": {
                    "invoice_key_id": str(new_ulid()),
                    "created_at": now,
                },
            },
            upsert=True,
        )

    async def _recover_orphan_monthly_invoice(
        self,
        *,
        enrollment_id: str,
        parent_id: str,
        student_id: str,
        period: str,
        gross_amount_cents: int,
        discount_cents: int,
        net_amount_cents: int,
        discount_policy: TuitionDiscount | None,
        invoice_key: dict[str, object] | None,
        now: datetime,
    ) -> str:
        """Rebuild the monthly invoice behind an already-claimed invoice key.

        ``net_amount_cents`` is the post-discount charge, matching what the
        normal path bills: pricing from gross here would overcharge a
        discounted family and let their credit be spent on tuition they never
        owed. The gross charge and the discount are still needed to record the
        invoice in the canonical shape the normal path writes - line and
        subtotal gross, discount broken out - so reporting cannot tell a
        recovered invoice from a generated one.
        """
        if self._ledger_repo is None or invoice_key is None:
            return "failed"
        invoice_id = self._monthly_invoice_id(enrollment_id, period)
        existing_invoice = await self._ledger_repo.get_invoice(invoice_id)
        existing_invoice_id = invoice_id if existing_invoice is not None else None

        payment_id = str(invoice_key.get("payment_id") or "")
        credit_state = (
            await self._applied_credit_state(payment_id)
            if payment_id
            else AppliedCreditState(applied_cents=0)
        )
        applied_credit_cents = credit_state.applied_cents
        amount_cents = max(net_amount_cents - applied_credit_cents, 0)
        if existing_invoice_id is None:
            existing_invoice_id = await self._find_existing_invoice_for_enrollment_period(
                enrollment_id=enrollment_id,
                period=period,
            )
        if (
            existing_invoice_id == invoice_id
            and await self._monthly_invoice_is_complete(
                enrollment_id=enrollment_id,
                period=period,
                gross_cents=gross_amount_cents,
                applied_credit_cents=applied_credit_cents,
            )
        ) or (
            existing_invoice_id is not None
            and existing_invoice_id != invoice_id
            and await self._invoice_has_consistent_lines(invoice_id=existing_invoice_id)
        ):
            await self._mark_monthly_invoice_key(
                enrollment_id=enrollment_id,
                period=period,
                status="complete",
                now=now,
            )
            return "already_complete"

        if not payment_id:
            return "failed"
        if credit_state.has_unresolved_drift:
            # Credit was demonstrably spent on this invoice but no source
            # records how much. Billing gross here would overcharge the family,
            # so stop and make the drift visible instead (#233).
            return await self._fail_unresolved_credit_drift(
                enrollment_id=enrollment_id,
                period=period,
                payment_id=payment_id,
                credit_state=credit_state,
                now=now,
            )
        if self._credit_ledger is not None:
            # Idempotent + resumable: returns what this invoice already
            # consumed, and tops it up if an earlier run only applied part of
            # the available credit before dying.
            applied_credit_cents = await self._credit_ledger.apply_available_credits(
                parent_id=parent_id,
                invoice_id=payment_id,
                amount_due_cents=net_amount_cents,
            )
            amount_cents = max(net_amount_cents - applied_credit_cents, 0)
            # Rebuild any audit rows the crash lost, so admin credit views and
            # the launch-readiness audit agree with the balance we just billed.
            await self._credit_ledger.repair_credit_projections(payment_id)
        if existing_invoice_id and existing_invoice_id != invoice_id:
            await self._mark_monthly_invoice_key(
                enrollment_id=enrollment_id,
                period=period,
                status="repair_failed",
                now=now,
                repair_error="existing period invoice is not complete and cannot be repaired by monthly generator",
            )
            return "failed"

        # A tuition line that disagrees with the gross charge cannot be repaired: the
        # line write is $setOnInsert, so it would survive untouched while a back-filled
        # discount line dragged the recomputed header away from both shapes. Bail before
        # writing anything. This also covers invoices recovered under the old net-of-
        # credit shape, which are left exactly as they are for an operator to inspect.
        conflicting_line = await self._db["invoice_lines"].find_one(
            {
                "academy_id": current_academy_id(),
                "invoice_id": invoice_id,
                "line_id": self._monthly_invoice_line_id(enrollment_id, period),
                "amount_cents": {"$ne": gross_amount_cents},
            }
        )
        if conflicting_line is not None:
            await self._mark_monthly_invoice_key(
                enrollment_id=enrollment_id,
                period=period,
                status="repair_failed",
                now=now,
                repair_error="existing monthly tuition line does not match the expected gross charge",
            )
            return "failed"

        # Recovery writes the same invoice shape as the normal generation path: the
        # tuition line and subtotal gross, the discount broken out on its own line, and
        # only total_cents/balance_due_cents net of discount and applied credit.
        await self._dual_write_ledger_invoice(
            ledger_repo=self._ledger_repo,
            payment_id=payment_id,
            enrollment_id=enrollment_id,
            parent_id=parent_id,
            student_id=student_id,
            period=period,
            gross_cents=gross_amount_cents,
            discount_cents=discount_cents,
            total_cents=amount_cents,
            discount_policy=discount_policy,
            now=now,
        )
        await self._reconcile_monthly_invoice_header(
            enrollment_id=enrollment_id,
            period=period,
            gross_cents=gross_amount_cents,
            discount_cents=discount_cents,
            total_cents=amount_cents,
            now=now,
        )
        if await self._monthly_invoice_is_complete(
            enrollment_id=enrollment_id,
            period=period,
            gross_cents=gross_amount_cents,
            applied_credit_cents=applied_credit_cents,
        ):
            await self._mark_monthly_invoice_key(
                enrollment_id=enrollment_id,
                period=period,
                status="complete",
                now=now,
            )
            return "repaired_partial" if existing_invoice is not None else "repaired_orphan"
        await self._mark_monthly_invoice_key(
            enrollment_id=enrollment_id,
            period=period,
            status="repair_failed",
            now=now,
            repair_error="monthly invoice did not contain expected header and line after repair",
        )
        return "failed"

    async def _applied_credit_state(self, invoice_id: str) -> AppliedCreditState:
        """How much credit ``invoice_id`` already consumed, source of truth first.

        Delegates to the credit ledger, which reads the per-invoice application
        record written in the same atomic update as the balance decrement. Falls
        back to the audit projections only when no credit ledger is wired in.
        """
        if self._credit_ledger is None:
            return AppliedCreditState(applied_cents=await self._applied_credit_cents(invoice_id))
        state: AppliedCreditState = await self._credit_ledger.applied_credit_state(invoice_id)
        projected = await self._applied_credit_cents(invoice_id)
        if projected <= state.applied_cents:
            return state
        return AppliedCreditState(
            applied_cents=projected,
            unresolved_credit_ids=state.unresolved_credit_ids,
        )

    async def _fail_unresolved_credit_drift(
        self,
        *,
        enrollment_id: str,
        period: str,
        payment_id: str,
        credit_state: AppliedCreditState,
        now: datetime,
    ) -> str:
        credit_ids = ", ".join(credit_state.unresolved_credit_ids)
        detail = (
            f"account credit was applied to payment {payment_id} but the amount is not "
            f"recoverable from any source; unresolved credits: {credit_ids}"
        )
        logging.getLogger(__name__).error(
            "monthly billing: unresolved credit application drift",
            extra={
                "enrollment_id": enrollment_id,
                "period": period,
                "payment_id": payment_id,
                "unresolved_credit_ids": list(credit_state.unresolved_credit_ids),
            },
        )
        capture_message(
            f"Unresolved account credit drift for enrollment {enrollment_id} period {period}",
            level="error",
        )
        await self._mark_monthly_invoice_key(
            enrollment_id=enrollment_id,
            period=period,
            status="repair_failed",
            now=now,
            repair_error=detail,
        )
        return "failed"

    async def _applied_credit_cents(self, invoice_id: str) -> int:
        total = 0
        async for doc in self._db["credit_applications"].find(
            {"academy_id": current_academy_id(), "invoice_id": invoice_id}
        ):
            total += int(doc.get("amount_cents", 0))
        source_total = 0
        async for doc in self._db["account_credit_ledger"].find(
            {
                "academy_id": current_academy_id(),
                "invoice_id": invoice_id,
                "type": "CREDIT_APPLIED",
                "status": "APPLIED",
            }
        ):
            source_total += int(doc.get("amount_cents", 0))
        return max(total, source_total)

    async def generate_monthly_payments(self, period: str) -> GenerateMonthlyPaymentsResult:
        academy_id = current_academy_id()
        self._invoice_due_days = await self._load_invoice_due_days()
        cursor = self._db["enrollments"].find(
            {
                "academy_id": academy_id,
                "status": {"$in": ["active", "paused"]},
            },
            sort=[("created_at", 1), ("enrollment_id", 1)],
        )
        now = self._clock()
        created = 0
        skipped_existing = 0
        skipped_no_charge = 0
        skipped_autopay = 0
        skipped_paused = 0
        skipped_details: list[MonthlyGenerationSkippedDetail] = []
        repaired_orphan_keys = 0
        repaired_partial_invoices = 0
        failed_repair = 0
        async for enrollment in cursor:
            enrollment_id = str(enrollment.get("enrollment_id") or enrollment.get("_id"))
            session_id = str(enrollment.get("session_id") or "")
            student_id = str(enrollment.get("student_id") or "")
            student_doc = await self._db["students"].find_one(
                {"academy_id": academy_id, "student_id": student_id}
            )
            deferral_detail = await self._active_billing_deferral_detail(
                academy_id=academy_id,
                enrollment=enrollment,
                student_doc=student_doc,
                period=period,
                today=now.date(),
            )
            if deferral_detail is not None:
                skipped_paused += 1
                skipped_details.append(deferral_detail)
                continue
            if period in set(enrollment.get("skip_periods") or []):
                skipped_paused += 1
                skipped_details.append(
                    self._legacy_skip_period_detail(
                        enrollment=enrollment,
                        student_doc=student_doc,
                        period=period,
                    )
                )
                continue
            billing_type = str(enrollment.get("billing_type") or "standard").lower()
            if billing_type not in {"", "standard", "monthly", "manual"}:
                skipped_no_charge += 1
                continue
            existing = await self._repo._find_one(
                {
                    "enrollment_id": enrollment_id,
                    "period": period,
                    "is_deleted": {"$ne": True},
                }
            )
            if existing is not None:
                skipped_existing += 1
                continue
            session_doc = await self._db["sessions"].find_one(
                {"academy_id": academy_id, "session_id": session_id}
            )
            (
                gross_amount_cents,
                discount_cents,
                net_amount_cents,
                _snapshot_id,
                discount_policy,
            ) = await _resolve_charge_for_enrollment(
                repo=self._repo,
                enrollment=enrollment,
                session_doc=session_doc or {},
                period=period,
                now=now,
            )
            if gross_amount_cents <= 0:
                skipped_no_charge += 1
                continue
            parent_id = str(
                enrollment.get("parent_id")
                or enrollment.get("parent_user_id")
                or (student_doc or {}).get("parent_id")
                or (student_doc or {}).get("parent_user_id")
                or ""
            )
            if not parent_id:
                skipped_no_charge += 1
                continue
            existing_invoice_id = await self._find_existing_invoice_for_enrollment_period(
                enrollment_id=enrollment_id,
                period=period,
            )
            monthly_invoice_id = self._monthly_invoice_id(enrollment_id, period)
            existing_invoice_complete = (
                existing_invoice_id == monthly_invoice_id
                and await self._monthly_invoice_is_complete(
                    enrollment_id=enrollment_id,
                    period=period,
                    gross_cents=gross_amount_cents,
                    applied_credit_cents=await self._monthly_invoice_applied_credit_cents(
                        enrollment_id=enrollment_id,
                        period=period,
                    ),
                )
            ) or (
                existing_invoice_id is not None
                and existing_invoice_id != monthly_invoice_id
                and await self._invoice_has_consistent_lines(invoice_id=existing_invoice_id)
            )
            if existing_invoice_complete:
                await self._upsert_complete_monthly_invoice_key(
                    enrollment_id=enrollment_id,
                    period=period,
                    now=now,
                )
                skipped_existing += 1
                continue
            payment_id = str(new_ulid())
            invoice_key_id = str(new_ulid())
            try:
                await self._db["billing_invoice_keys"].insert_one(
                    {
                        "academy_id": academy_id,
                        "invoice_key_id": invoice_key_id,
                        "payment_id": payment_id,
                        "enrollment_id": enrollment_id,
                        "period": period,
                        "status": "claimed",
                        "created_at": now,
                        "updated_at": now,
                    }
                )
            except DuplicateKeyError:
                invoice_key = await self._db["billing_invoice_keys"].find_one(
                    {
                        "academy_id": academy_id,
                        "enrollment_id": enrollment_id,
                        "period": period,
                    }
                )
                recovered = await self._recover_orphan_monthly_invoice(
                    enrollment_id=enrollment_id,
                    parent_id=parent_id,
                    student_id=student_id,
                    period=period,
                    gross_amount_cents=gross_amount_cents,
                    discount_cents=discount_cents,
                    net_amount_cents=net_amount_cents,
                    discount_policy=discount_policy,
                    invoice_key=invoice_key,
                    now=now,
                )
                if recovered == "repaired_orphan":
                    created += 1
                    repaired_orphan_keys += 1
                elif recovered == "repaired_partial":
                    repaired_partial_invoices += 1
                elif recovered == "already_complete":
                    skipped_existing += 1
                else:
                    failed_repair += 1
                continue
            applied_credit_cents = 0
            if self._credit_ledger is not None:
                applied_credit_cents = await self._credit_ledger.apply_available_credits(
                    parent_id=parent_id,
                    invoice_id=payment_id,
                    amount_due_cents=net_amount_cents,
                )
            # Recurring tuition discount (#244) is applied to the net charge before
            # the ledger write, so the generated invoice reflects the discounted amount.
            # Phase 2A complete: write only to the ledger (legacy Payment write removed).
            # Phase 5 will delete MongoPaymentRepository once the prod backfill is confirmed.
            amount_cents = max(net_amount_cents - applied_credit_cents, 0)
            if self._ledger_repo is not None:
                await self._dual_write_ledger_invoice(
                    ledger_repo=self._ledger_repo,
                    payment_id=payment_id,
                    enrollment_id=enrollment_id,
                    parent_id=parent_id,
                    student_id=student_id,
                    period=period,
                    gross_cents=gross_amount_cents,
                    discount_cents=discount_cents,
                    total_cents=amount_cents,
                    discount_policy=discount_policy,
                    now=now,
                )
                await self._mark_monthly_invoice_key(
                    enrollment_id=enrollment_id,
                    period=period,
                    status="complete",
                    now=now,
                )
            created += 1
        return GenerateMonthlyPaymentsResult(
            created=created,
            skipped_existing=skipped_existing,
            skipped_no_charge=skipped_no_charge,
            skipped_autopay=skipped_autopay,
            skipped_paused=skipped_paused,
            repaired_orphan_keys=repaired_orphan_keys,
            repaired_partial_invoices=repaired_partial_invoices,
            failed_repair=failed_repair,
            skipped_details=skipped_details,
        )


def _session_amount_cents(doc: dict[str, object]) -> int:
    if doc.get("amount_cents") is not None:
        return int(doc["amount_cents"])
    if doc.get("monthly_price_cents") is not None:
        return int(doc["monthly_price_cents"])
    if doc.get("monthly_price") is not None:
        return round(float(doc["monthly_price"]) * 100)  # type: ignore[arg-type]
    return 0


def _coerce_datetime(value: object | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


def _session_occurrences(
    doc: dict[str, object],
    period: BillingPeriod,
) -> list[ClassOccurrence]:
    timezone_name = str(doc.get("timezone") or period.timezone or "America/Chicago")
    tz = ZoneInfo(timezone_name)
    session_id = str(doc.get("session_id") or doc.get("_id") or "")
    if doc.get("start_date") and doc.get("end_date") and doc.get("days_of_week"):
        start_date = date.fromisoformat(str(doc["start_date"]))
        end_date = date.fromisoformat(str(doc["end_date"]))
        days = {str(day)[:3].title() for day in (doc.get("days_of_week") or [])}
        start_time = time.fromisoformat(str(doc.get("start_time") or "00:00"))
        end_time = time.fromisoformat(str(doc.get("end_time") or doc.get("start_time") or "00:00"))
        current = max(start_date, period.start_at.date())
        period_last_day = date.fromordinal(period.end_at.date().toordinal() - 1)
        final = min(end_date, period_last_day)
        rows: list[ClassOccurrence] = []
        while current <= final:
            if current.strftime("%a") in days:
                local_start = datetime.combine(current, start_time, tzinfo=tz)
                local_end = datetime.combine(current, end_time, tzinfo=tz)
                rows.append(
                    ClassOccurrence(
                        occurrence_id=f"{session_id}:{current.isoformat()}:{start_time.strftime('%H:%M')}",
                        session_id=session_id,
                        start_at=local_start.astimezone(UTC),
                        end_at=local_end.astimezone(UTC),
                        status="scheduled",
                        is_billable=True,
                        timezone=timezone_name,
                    )
                )
            current = date.fromordinal(current.toordinal() + 1)
        return rows

    start_at = _coerce_datetime(doc.get("start_at"))
    end_at = _coerce_datetime(doc.get("end_at"))
    if start_at is None or end_at is None:
        return []
    local_start = start_at.astimezone(tz)
    if not (period.start_at <= local_start < period.end_at):
        return []
    return [
        ClassOccurrence(
            occurrence_id=f"{session_id}:{local_start.date().isoformat()}:{local_start.strftime('%H:%M')}",
            session_id=session_id,
            start_at=start_at,
            end_at=end_at,
            status="scheduled"
            if str(doc.get("status") or "scheduled") == "active"
            else str(doc.get("status") or "scheduled"),
            is_billable=True,
            timezone=timezone_name,
        )
    ]


# ---------------------------------------------------------------------------
# Module-level proration helpers for generate_monthly_payments.
#
# These are free functions (NOT repo class methods) that apply
# FirstMonthProrationPolicy.  The MongoPaymentRepository class itself no
# longer performs any tuition calculation; it delegates to these functions.
# Future work can extract generate_monthly_payments into a proper application
# use case and delete these from the infra layer.
# ---------------------------------------------------------------------------


async def _resolve_charge_for_enrollment(
    *,
    repo: MongoPaymentRepository,
    enrollment: dict[str, object],
    session_doc: dict[str, object],
    period: str,
    now: datetime,
) -> tuple[int, int, int, str | None, TuitionDiscount | None]:
    """Return charge tuple for a monthly row, including the applied discount policy.

    This function owns all proration decisions; the repo class is a pure
    storage delegate here. A recurring tuition discount (issue #244), if active and
    effective for the period, is applied at monthly scale and threaded through the
    existing proration policy so discounted invoices stay consistent with proration.
    """
    amount_cents = _session_amount_cents(session_doc)
    billing_start = _coerce_datetime(
        enrollment.get("billing_start_at")
        or enrollment.get("enrolled_at")
        or enrollment.get("created_at")
    )
    enrollment_id = str(enrollment.get("enrollment_id") or enrollment.get("_id"))
    timezone_name = str(session_doc.get("timezone") or "America/Chicago")
    billing_period = BillingPeriod.from_label(period, timezone_name=timezone_name)
    occurrences = await repo._occurrences_for_session(session_doc, billing_period)

    policy = await repo._discounts.get_active(enrollment_id)
    mdc = (
        monthly_discount_cents(policy, monthly_price_cents=amount_cents)
        if policy is not None and _policy_applies(policy, billing_period)
        else 0
    )

    # Not a first-month enrollment → full monthly tuition
    if billing_start is None or billing_start.strftime("%Y-%m") != period:
        net = max(amount_cents - mdc, 0)
        discount = amount_cents - net
        snapshot = _build_monthly_tuition_snapshot(
            occurrences=occurrences,
            billing_period=billing_period,
            monthly_price_cents=amount_cents,
            discount_cents=discount,
            now=now,
        )
        snapshot_id = await repo.persist_monthly_tuition(
            snapshot=snapshot,
            enrollment_id=enrollment_id,
            session_id=str(enrollment.get("session_id") or session_doc.get("session_id") or ""),
            student_id=str(enrollment.get("student_id") or ""),
        )
        return amount_cents, discount, net, snapshot_id, policy if mdc > 0 else None

    # Check if already prorated in a prior run
    academy_id = current_academy_id()
    prior_consumed = await repo._db["billing_calculation_snapshots"].find_one(
        {
            "academy_id": academy_id,
            "enrollment_id": enrollment_id,
            "billing_period_label": period,
            "status": "CONSUMED",
            "calculation_type": "FIRST_MONTH_PRORATION",
        }
    )
    if prior_consumed is not None:
        return 0, 0, 0, str(prior_consumed.get("snapshot_id")), None

    # First-month proration. Net is prorated AFTER the discount (the proration
    # policy already subtracts discount_cents before prorating); gross is the same
    # proration with no discount, so discount = gross_prorated - net_prorated exactly.
    snapshot = _build_proration_snapshot_for_first_month(
        occurrences=occurrences,
        billing_period=billing_period,
        billing_start=billing_start,
        amount_cents=amount_cents,
        discount_cents=mdc,
        now=now,
        enrollment_id=enrollment_id,
    )
    net_prorated = snapshot.final_amount_cents
    gross_prorated = _prorated_gross(
        occurrences=occurrences,
        billing_period=billing_period,
        billing_start=billing_start,
        amount_cents=amount_cents,
        now=now,
    )
    discount = max(gross_prorated - net_prorated, 0)
    snapshot_id = await repo.persist_consumed_first_month(
        snapshot=snapshot,
        enrollment_id=enrollment_id,
        session_id=str(enrollment.get("session_id") or ""),
        student_id=str(enrollment.get("student_id") or ""),
        now=now,
    )
    return gross_prorated, discount, net_prorated, snapshot_id, policy if mdc > 0 else None


def _policy_applies(policy: TuitionDiscount, billing_period: BillingPeriod) -> bool:
    """True when the policy's effective window overlaps the billing period."""
    p_start = billing_period.start_at.date()
    p_end = billing_period.end_at.date()
    return policy.effective_start <= p_end and (
        policy.effective_end is None or policy.effective_end >= p_start
    )


def _prorated_gross(
    *,
    occurrences: list[ClassOccurrence],
    billing_period: BillingPeriod,
    billing_start: datetime,
    amount_cents: int,
    now: datetime,
) -> int:
    """Prorated tuition with NO discount (the gross side of a discounted month)."""
    raw = FirstMonthProrationPolicy().quote(
        monthly_price_cents=amount_cents,
        discount_cents=0,
        period=billing_period,
        occurrences=occurrences,
        billing_start_at=billing_start,
        calculated_at=now,
        calculated_by="SYSTEM",
    )
    return raw.final_amount_cents


def _build_proration_snapshot_for_first_month(
    *,
    occurrences: list[ClassOccurrence],
    billing_period: BillingPeriod,
    billing_start: datetime,
    amount_cents: int,
    discount_cents: int,
    now: datetime,
    enrollment_id: str,
) -> BillingCalculationSnapshot:
    """Compute a CONSUMED first-month proration snapshot (no I/O)."""
    snapshot_id = str(new_ulid())
    raw = FirstMonthProrationPolicy().quote(
        monthly_price_cents=amount_cents,
        discount_cents=discount_cents,
        period=billing_period,
        occurrences=occurrences,
        billing_start_at=billing_start,
        calculated_at=now,
        calculated_by="SYSTEM",
    )
    return raw.model_copy(update={"snapshot_id": snapshot_id, "status": "CONSUMED"})


def _build_monthly_tuition_snapshot(
    *,
    occurrences: list[ClassOccurrence],
    billing_period: BillingPeriod,
    monthly_price_cents: int,
    discount_cents: int,
    now: datetime,
) -> BillingCalculationSnapshot:
    """Build a CONSUMED monthly-tuition snapshot (no proration, full amount)."""
    eligible = [
        occ
        for occ in sorted(occurrences, key=lambda o: o.occurrence_id)
        if FirstMonthProrationPolicy._is_eligible(occ, billing_period)
    ]
    snapshot_id = str(new_ulid())
    included = [occ.occurrence_id for occ in eligible]
    return BillingCalculationSnapshot(
        snapshot_id=snapshot_id,
        status="CONSUMED",
        calculation_type="MONTHLY_TUITION",
        monthly_price_cents=monthly_price_cents,
        discount_cents=discount_cents,
        billing_period_start=billing_period.start_at,
        billing_period_end=billing_period.end_at,
        billing_period_label=billing_period.label,
        timezone=billing_period.timezone,
        total_eligible_classes=len(eligible),
        billable_remaining_classes=len(eligible),
        proration_ratio=f"{len(eligible)}/{len(eligible)}" if eligible else "0/0",
        final_amount_cents=max(monthly_price_cents - discount_cents, 0),
        included_occurrence_ids=included,
        excluded_occurrences={},
        schedule_signature=schedule_signature(eligible, timezone_name=billing_period.timezone),
        calculated_at=now,
        calculated_by="SYSTEM",
    )
