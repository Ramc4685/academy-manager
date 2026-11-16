"""Monthly billing generation extracted from MongoPaymentRepository.

Pure code motion: `MongoMonthlyBillingGenerator` holds the monthly-generation
machinery (deferral skips, invoice-key idempotency, ledger dual-write, orphan
repair) plus the module-level proration helpers that only the generation path
uses. `MongoPaymentRepository.generate_monthly_payments` delegates here so
the legacy adapter keeps shrinking toward deletion.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any, Literal, TypeGuard
from zoneinfo import ZoneInfo

from bson import ObjectId
from pydantic import ValidationError
from pymongo.errors import DuplicateKeyError

from backend.v2.contexts.billing.application.use_cases.admin_payment_ops import (
    GenerateMonthlyPaymentsResult,
    MonthlyGenerationSkippedDetail,
)
from backend.v2.contexts.billing.application.use_cases.apply_enrollment_move import (
    MoveDiscountReader,
)
from backend.v2.contexts.billing.application.use_cases.family_offers import SIBLING_BOUNDS
from backend.v2.contexts.billing.application.use_cases.invoice_numbering import (
    mint_invoice_number,
)
from backend.v2.contexts.billing.domain.billing_settings import (
    BillingSettings,
    SiblingAppliesTo,
    SiblingDiscount,
    SiblingFullPriceChild,
)
from backend.v2.contexts.billing.domain.ledger import (
    ACCOUNT_CREDIT_SOURCE_TYPE,
    TUITION_DISCOUNT_SOURCE_TYPE,
    InvoiceLine,
    LedgerInvoice,
)
from backend.v2.contexts.billing.domain.models import AppliedCreditState
from backend.v2.contexts.billing.domain.plan_price_change import stored_class_fee_cents
from backend.v2.contexts.billing.domain.proration import (
    BILLABLE_CLASSES_PER_MONTH,
    MOVE_SOURCE_TYPE,
    BillingCalculationSnapshot,
    BillingPeriod,
    ClassOccurrence,
    FirstMonthProrationPolicy,
    billable_classes_per_period,
    schedule_signature,
    snapshot_charge_denominator,
    snapshot_classes_charged,
)
from backend.v2.contexts.billing.domain.sibling_discount import (
    SIBLING_DISCOUNT_ID_PREFIX,
    FamilyEnrollment,
    best_tuition_discount,
    full_price_student,
    is_sibling_discounted,
    sibling_policy,
)
from backend.v2.contexts.billing.domain.tuition_discount import (
    TuitionDiscount,
    display_label,
    monthly_discount_cents,
    policy_applies_to_period,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_counter_repo import (
    MongoBillingCounterRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_settings_repo import (
    MongoBillingSettingsRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_plan_price_changes import (
    class_fee_cents_for_period,
)
from backend.v2.shared.ids import new_ulid
from backend.v2.shared.observability.ops_alerts import capture_message
from backend.v2.shared.tenancy import current_academy_id
from backend.v2.shared.time import (
    LEGACY_FALLBACK_TIMEZONE,
    academy_timezone_lookup,
    resolve_session_doc_timezone,
)

if TYPE_CHECKING:
    from backend.v2.contexts.billing.infrastructure.mongo_payment_repo import (
        MongoPaymentRepository,
    )


# ``billing_invoice_keys.status`` values this module writes and reads back.
# ``reviewed`` (#599) is terminal-until-the-invoice-changes: recovery cannot
# repair some pre-PR-#494 invoices in place (their tuition line is written with
# ``$setOnInsert``), so those keys would report ``repair_failed`` on every run
# forever. Once an operator has judged one and recorded why, the generator
# leaves it alone instead of re-reporting it.
MONTHLY_KEY_STATUS_REPAIR_FAILED = "repair_failed"

#: Enrollment statuses the monthly run reads. ``paused`` rows are read only to
#: be skipped (#651), so ``active`` is the one status that is invoiced.
MONTHLY_RUN_ENROLLMENT_STATUSES: tuple[str, ...] = ("active", "paused")
MONTHLY_INVOICED_ENROLLMENT_STATUS = "active"
#: ``billing_type`` values the monthly run invoices (missing reads "standard").
MONTHLY_INVOICED_BILLING_TYPES: frozenset[str] = frozenset({"", "standard", "monthly", "manual"})
MONTHLY_KEY_STATUS_REVIEWED = "reviewed"


def _as_utc(value: datetime) -> datetime:
    """Compare a stored timestamp against an aware one.

    Mongo hands back naive datetimes; comparing one to ``now`` raises (#706).
    Stored billing timestamps are UTC, so read a naive one as UTC.
    """
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


async def mark_monthly_invoice_key_reviewed(
    db: Any,
    *,
    academy_id: str,
    enrollment_id: str,
    period: str,
    reason: str,
    reviewed_by: str,
    now: datetime,
) -> bool:
    """Record that an operator judged a ``repair_failed`` key and accepted it.

    Writes only ``billing_invoice_keys`` — never the invoice, its lines, or any
    payment — so reviewing is a statement about money, not a change to it. The
    filter pins ``status`` to ``repair_failed`` so a key that has since been
    repaired (or never failed) cannot be silenced by mistake; ``False`` means
    no such key was found. Called by
    ``backend/scripts/monthly_invoice_key_repair_review.py``.
    """
    result = await db["billing_invoice_keys"].update_one(
        {
            "academy_id": academy_id,
            "enrollment_id": enrollment_id,
            "period": period,
            "status": MONTHLY_KEY_STATUS_REPAIR_FAILED,
        },
        {
            "$set": {
                "status": MONTHLY_KEY_STATUS_REVIEWED,
                "updated_at": now,
                "reviewed": {
                    "reason": reason,
                    "reviewed_at": now,
                    "reviewed_by": reviewed_by,
                },
            }
        },
    )
    return int(getattr(result, "matched_count", 0) or 0) == 1


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
        self._autopay_charge_offset_days: int | None = None

    async def _load_academy_timezone(self) -> str | None:
        """The academy's wall clock, resolved once per generation run.

        Issue #675 follow-up: ``pending_cancellation_at`` is the last instant
        of the academy-LOCAL month, so bucketing it into a ``YYYY-MM`` period
        needs that zone — in UTC a Chicago September ends in October and the
        skip below would be off by a month. Unreadable/unset degrades to UTC,
        matching ``self_cancel._end_of_month`` and ``period_of``.
        """
        return await _academy_timezone(self._db)

    async def _load_schedule(self, on: date) -> tuple[int, int | None]:
        """This academy's ``(invoice_due_days, autopay_charge_offset_days)`` as of
        ``on`` (a dated schedule change applies from its day), falling back to
        the model defaults.

        Settings are advisory for generation: a missing or unreadable
        billing_settings doc must never block the monthly run, so any failure
        degrades to the default rather than raising.
        """
        try:
            settings = await MongoBillingSettingsRepository(self._db).get(on=on)
        except Exception:
            logging.getLogger(__name__).warning(
                "monthly_generation_billing_settings_unreadable; using default due days",
                exc_info=True,
            )
            # A silent default on the 1st would date a whole month of invoices
            # on the wrong schedule (L8 review), so page someone.
            capture_message(
                f"Monthly generation could not read billing settings for {on}; "
                "invoices use the default due days and no autopay charge date",
                level="error",
            )
            settings = BillingSettings.default("")
        return settings.invoice_due_days, settings.autopay_charge_offset_days

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

    def _skip_detail(
        self,
        skip: tuple[str, Any],
        *,
        enrollment: dict[str, object],
        student_doc: dict[str, object] | None,
        period: str,
    ) -> MonthlyGenerationSkippedDetail:
        """The run's skip detail for a ``monthly_skip_reason`` result."""
        reason, value = skip
        if reason == "deferral":
            return self._skipped_detail_from_deferral(
                enrollment=enrollment, student_doc=student_doc, period=period, deferral=value
            )
        if reason == "paused":
            # Issue #651: a paused enrollment is never invoiced, deferral row or
            # not. A deferral explains the skip when present; otherwise the
            # status itself is the reason.
            return self._paused_status_detail(
                enrollment=enrollment, student_doc=student_doc, period=period
            )
        if reason == "pending_cancellation":
            return self._pending_cancellation_detail(
                enrollment=enrollment,
                student_doc=student_doc,
                period=period,
                pending_period=value,
            )
        return self._legacy_skip_period_detail(
            enrollment=enrollment, student_doc=student_doc, period=period
        )

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

    def _paused_status_detail(
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
            reason_code="enrollment_paused",
            source="enrollment.status",
            billing_period=period,
            needs_review=False,
            metadata={"policy": "paused enrollments are not invoiced (#651)"},
        )

    def _pending_cancellation_detail(
        self,
        *,
        enrollment: dict[str, object],
        student_doc: dict[str, object] | None,
        period: str,
        pending_period: str,
    ) -> MonthlyGenerationSkippedDetail:
        return MonthlyGenerationSkippedDetail(
            enrollment_id=str(enrollment.get("enrollment_id") or enrollment.get("_id")),
            student_id=str(enrollment.get("student_id") or ""),
            student_name=str((student_doc or {}).get("full_name") or "") or None,
            reason_code="pending_cancellation",
            source="enrollment.pending_cancellation_at",
            billing_period=period,
            needs_review=False,
            metadata={
                "policy": "a scheduled end-of-period cancel is not billed past its month (#675)",
                "pending_cancellation_period": pending_period,
            },
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

    async def _mint_invoice_number(
        self,
        *,
        ledger_repo: Any,
        invoice_id: str,
        academy_id: str,
        period: str,
    ) -> str | None:
        """Allocate this invoice's parent-facing number (issue #659).

        The monthly batch mints the great majority of invoices, so until it
        called this the number parents saw was the internal slug. Two rules
        keep it safe inside an idempotent generation run:

        * **Never renumber.** A re-run (catch-up tick, orphan repair) reuses
          the deterministic ``invoice_id``; if that invoice already carries a
          number we return it instead of burning a second counter value.
        * **Never block the money.** Numbering is presentation. A missing
          ``billing_settings`` doc or an unreachable counter degrades to
          ``None`` — the same state every pre-#659 invoice is already in, and
          one the display path back-fills lazily — rather than failing the
          run and leaving a family unbilled.
        """
        try:
            existing = await ledger_repo.get_invoice(invoice_id)
        except Exception:
            existing = None
        if existing is not None and existing.invoice_number:
            return str(existing.invoice_number)
        try:
            return await mint_invoice_number(
                billing_counters=MongoBillingCounterRepository(self._db),
                billing_settings=MongoBillingSettingsRepository(self._db),
                academy_id=academy_id,
                period=period,
            )
        except Exception:
            logging.getLogger(__name__).warning(
                "monthly_generation_invoice_number_unmintable; invoice left unnumbered",
                extra={"invoice_id": invoice_id, "period": period},
                exc_info=True,
            )
            return None

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
        applied_credit_cents: int = 0,
        discount_policy: TuitionDiscount | None = None,
        tuition_description: str | None = None,
        now: datetime,
    ) -> None:
        """Write a LedgerInvoice for a monthly-generated enrollment charge.

        Uses a deterministic invoice_id for idempotency so re-runs are safe.

        Account credit spent on the charge is recorded as its own negative
        ``account_credit`` line, keyed by ``payment_id`` like the credit
        application itself. A header-only credit was lost by every later
        ``recompute_totals`` (late fee, added line, ACH discount), which billed
        the family the already-spent credit again.
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
        # Stamped only when the academy charges ahead of the due date (L8);
        # unstamped invoices charge on the due date.
        offset = self._autopay_charge_offset_days
        autopay_charge_date = None if offset is None else now.date() + timedelta(days=offset)
        invoice_number = await self._mint_invoice_number(
            ledger_repo=ledger_repo, invoice_id=invoice_id, academy_id=academy_id, period=period
        )

        invoice = LedgerInvoice(
            invoice_id=invoice_id,
            invoice_number=invoice_number,
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
            autopay_charge_date=autopay_charge_date,
            created_at=now,
            updated_at=now,
        )
        line = InvoiceLine(
            line_id=self._monthly_invoice_line_id(enrollment_id, period),
            academy_id=academy_id,
            invoice_id=invoice_id,
            line_type="tuition",
            description=tuition_description or f"Monthly tuition {period}",
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
        if applied_credit_cents > 0:
            lines.append(
                InvoiceLine(
                    line_id=f"{self._monthly_invoice_line_id(enrollment_id, period)}-credit",
                    academy_id=academy_id,
                    invoice_id=invoice_id,
                    line_type="credit",
                    description="Account credit applied",
                    quantity=1,
                    unit_amount_cents=-applied_credit_cents,
                    amount_cents=-applied_credit_cents,
                    source_type=ACCOUNT_CREDIT_SOURCE_TYPE,
                    source_id=payment_id,
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
        # Any status this method writes supersedes an operator's review: the key
        # has moved on from the state that was judged, so the recorded reason no
        # longer describes it and must not silence the next run (#599).
        await self._db["billing_invoice_keys"].update_one(
            {
                "academy_id": current_academy_id(),
                "enrollment_id": enrollment_id,
                "period": period,
            },
            {"$set": update, "$unset": {"reviewed": ""}},
        )

    async def _monthly_invoice_key_review_is_current(
        self,
        *,
        invoice_key: dict[str, object] | None,
        enrollment_id: str,
        period: str,
    ) -> bool:
        """Has an operator reviewed this key, and does that review still hold?

        A review is a judgement about the invoice as it stood when it was made,
        so it lapses the moment that invoice changes: the comparison is against
        the LEDGER invoice's ``updated_at``, never the key's own (the key is
        stamped by the review itself). No invoice, no readable timestamp, or a
        run without a ledger repo means nothing can have changed under the
        review, so it stands.
        """
        if invoice_key is None:
            return False
        if str(invoice_key.get("status") or "") != MONTHLY_KEY_STATUS_REVIEWED:
            return False
        reviewed = invoice_key.get("reviewed")
        reviewed_at = reviewed.get("reviewed_at") if isinstance(reviewed, dict) else None
        if not isinstance(reviewed_at, datetime) or self._ledger_repo is None:
            return True
        invoice = await self._ledger_repo.get_invoice(
            self._monthly_invoice_id(enrollment_id, period)
        )
        updated_at = getattr(invoice, "updated_at", None) if invoice is not None else None
        if not isinstance(updated_at, datetime):
            return True
        return _as_utc(updated_at) <= _as_utc(reviewed_at)

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
        about a header-only credit written before credit became an ``account_credit``
        line. Recovery repairs a
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
            line.amount_cents
            for line in lines
            if line.source_type not in ("tuition_discount", ACCOUNT_CREDIT_SOURCE_TYPE)
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
        """Does this non-canonical invoice already cover its enrollment/period?

        Two header conventions are legitimate and both must be recognised, or the
        monthly run mints a second invoice for a month an admin already billed (#723):

        * the generator's own shape - ``subtotal_cents`` GROSS with the tuition
          discount mirrored in ``discount_cents`` alongside its discount line;
        * every other writer's shape (e.g. ``BillEnrollmentPeriod``) -
          ``subtotal_cents`` NET of the negative discount line, with
          ``discount_cents`` left at 0.

        ``recompute_totals`` keeps whichever of the two it is given.

        A line-less invoice is consistent only when every header amount is 0: that is
        the blank draft ``create_student_invoice`` opens for an admin to fill in.
        Stale non-zero totals with no lines behind them stay inconsistent.
        """
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

        gross_line_cents = 0
        discount_line_cents = 0
        credit_line_cents = 0
        async for line_doc in self._db["invoice_lines"].find(
            {
                "academy_id": academy_id,
                "invoice_id": invoice_id,
            }
        ):
            amount = int(line_doc.get("amount_cents", 0))
            if line_doc.get("source_type") == "tuition_discount":
                discount_line_cents += abs(amount)
            elif line_doc.get("source_type") == ACCOUNT_CREDIT_SOURCE_TYPE:
                credit_line_cents += abs(amount)
            else:
                gross_line_cents += amount

        subtotal_cents = int(invoice_doc.get("subtotal_cents", -1))
        discount_cents = int(invoice_doc.get("discount_cents", 0))
        total_cents = int(invoice_doc.get("total_cents", -1))
        balance_due_cents = int(invoice_doc.get("balance_due_cents", -1))
        gross_shape = subtotal_cents == gross_line_cents and discount_cents == discount_line_cents
        net_shape = subtotal_cents == gross_line_cents - discount_line_cents and discount_cents == 0
        return (
            (amount_cents is None or gross_line_cents == amount_cents)
            and (gross_shape or net_shape)
            and total_cents == max(subtotal_cents - discount_cents - credit_line_cents, 0)
            and 0 <= balance_due_cents <= total_cents
        )

    async def _find_existing_invoice_for_enrollment_period(
        self,
        *,
        enrollment_id: str,
        period: str,
    ) -> str | None:
        return await _existing_period_invoice_id(
            self._db, enrollment_id=enrollment_id, period=period
        )

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
                # The invoice is complete, so an operator's acceptance of an
                # earlier failure no longer describes this key (#599).
                "$unset": {"reviewed": ""},
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
        tuition_description: str | None,
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
            applied_credit_cents=applied_credit_cents,
            discount_policy=discount_policy,
            tuition_description=tuition_description,
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
        (
            self._invoice_due_days,
            self._autopay_charge_offset_days,
        ) = await self._load_schedule(self._clock().date())
        academy_timezone = await self._load_academy_timezone() or "UTC"
        cursor = self._db["enrollments"].find(
            {
                "academy_id": academy_id,
                "status": {"$in": list(MONTHLY_RUN_ENROLLMENT_STATUSES)},
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
        skipped_reviewed = 0
        async for enrollment in cursor:
            enrollment_id = str(enrollment.get("enrollment_id") or enrollment.get("_id"))
            session_id = str(enrollment.get("session_id") or "")
            student_id = str(enrollment.get("student_id") or "")
            student_doc = await self._db["students"].find_one(
                {"academy_id": academy_id, "student_id": student_id}
            )
            skip = await monthly_skip_reason(
                self._db,
                enrollment=enrollment,
                period=period,
                today=now.date(),
                academy_timezone=academy_timezone,
            )
            if skip is not None:
                skipped_paused += 1
                skipped_details.append(
                    self._skip_detail(
                        skip, enrollment=enrollment, student_doc=student_doc, period=period
                    )
                )
                continue
            billing_type = str(enrollment.get("billing_type") or "standard").lower()
            if billing_type not in MONTHLY_INVOICED_BILLING_TYPES:
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
                tuition_description,
            ) = await resolve_monthly_charge(
                repo=self._repo,
                enrollment=enrollment,
                session_doc=session_doc or {},
                period=period,
                now=now,
            )
            if gross_amount_cents <= 0:
                skipped_no_charge += 1
                continue
            parent_id = resolved_parent_id(enrollment, student_doc)
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
                if await self._monthly_invoice_key_review_is_current(
                    invoice_key=invoice_key,
                    enrollment_id=enrollment_id,
                    period=period,
                ):
                    # An operator already looked at this key and wrote down why
                    # it is acceptable. Re-running recovery would re-derive the
                    # same unrepairable outcome and re-report it (#599).
                    skipped_reviewed += 1
                    continue
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
                    tuition_description=tuition_description,
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
                    applied_credit_cents=applied_credit_cents,
                    discount_policy=discount_policy,
                    tuition_description=tuition_description,
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
            skipped_reviewed=skipped_reviewed,
            skipped_details=skipped_details,
        )


def session_amount_cents(doc: dict[str, object]) -> int:
    """The monthly price the generator bills a session at.

    Public because the cancellation reader must price a session EXACTLY as
    the generator does (#671): a bare ``amount_cents`` read is not
    equivalent — legacy/imported session docs carry only
    ``monthly_price_cents`` or ``monthly_price`` and would price at zero,
    crediting nobody for a date the family is still billed for in full
    (see the #609 warning in ``mongo_session_repo``).

    This is the STORED fee. A charge for a billing month reads
    ``class_fee_cents_for_period`` instead, which also applies a plan price
    change the owner scheduled for that month (Settings overhaul PR 26).
    """
    return stored_class_fee_cents(doc)


def _local_period_label(instant: datetime, timezone_name: str) -> str:
    """``YYYY-MM`` label of ``instant`` in the session's own timezone.

    Mirrors ``_period_label`` in
    ``backend.v2.contexts.billing.application.use_cases.quote_enrollment`` —
    the generator and the checkout quote have to bucket an instant into a
    month the same way, or the first-month handshake between them breaks at
    the local month boundary (#541). An unknown zone name falls back to UTC,
    matching ``_coerce_datetime``'s treatment of naive values.
    """
    try:
        tz = ZoneInfo(timezone_name)
    except (KeyError, ValueError):
        tz = ZoneInfo("UTC")
    return instant.astimezone(tz).strftime("%Y-%m")


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


def _tuition_line_description(period: str, snapshot: BillingCalculationSnapshot | None) -> str:
    """The tuition line's copy for one monthly invoice.

    The "N classes; extras free" sentence states the owner's rule — the
    monthly rate buys four classes per weekly meeting — and that rule prices
    the first month and the flat full month alike, so both snapshots get it
    (#730). Two families paying $70 for the same five dates must not read two
    different explanations of what the $70 bought.

    ``snapshot is None`` is only the prior-consumed month, whose tuition was
    charged (and described) in an earlier run and is billed at zero here.
    """
    if snapshot is None:
        return f"Monthly tuition {period}"
    billable = snapshot_classes_charged(snapshot)
    denominator = snapshot_charge_denominator(snapshot)
    if billable >= denominator:
        extra = (
            "5th class free" if denominator == BILLABLE_CLASSES_PER_MONTH else "extra classes free"
        )
        noun = "class" if denominator == 1 else "classes"
        return f"Monthly tuition {period} ({denominator} {noun}; {extra})"
    return (
        f"Monthly tuition {period}: {billable} of {denominator} classes — "
        f"monthly rate covers {denominator} classes; "
        "any additional class in the month is free."
    )


def _coerce_schedule_date(value: object | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            # `2026-06-30T00:00:00` and `2026-06-30 00:00:00` are rejected by
            # ``date.fromisoformat`` but are real stored bounds.
            parsed = _coerce_datetime(value)
            return parsed.date() if parsed is not None else None
    return None


def _schedule_bound(doc: dict[str, object], key: str) -> tuple[bool, date | None]:
    """Return ``(known, value)`` for a schedule bound.

    ``(True, None)`` means the field is genuinely absent (no bound); ``(False,
    None)`` means it holds something we cannot parse, which is NOT the same as
    "unbounded" — an unparseable ``end_date`` must not silently extend a series
    that stopped running.
    """
    raw = doc.get(key)
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return True, None
    value = _coerce_schedule_date(raw)
    return value is not None, value


def _coerce_schedule_time(value: object | None) -> time | None:
    if isinstance(value, time):
        return value
    if isinstance(value, datetime):
        return value.time()
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return time.fromisoformat(text)
    except ValueError:
        return None


_WEEKDAY_LABELS = frozenset({"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"})
_WEEKDAY_BY_INDEX = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _weekday_labels(values: object) -> set[str]:
    """Normalise a stored ``days_of_week`` list to ``%a`` labels.

    ``EditSession`` stores the client's value verbatim, so integer weekday
    indexes and odd casings both reach billing. Anything we cannot recognise is
    dropped, and the caller falls back rather than pricing an empty schedule.
    """
    labels: set[str] = set()
    for value in list(values or []) if isinstance(values, list | tuple) else []:
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            if 0 <= value <= 6:
                labels.add(_WEEKDAY_BY_INDEX[value])
            continue
        label = str(value).strip()[:3].title()
        if label in _WEEKDAY_LABELS:
            labels.add(label)
    return labels


def _recurring_occurrences(
    doc: dict[str, object],
    period: BillingPeriod,
    *,
    session_id: str,
    timezone_name: str,
    tz: ZoneInfo,
) -> list[ClassOccurrence] | None:
    """Expand a weekly template over ``period``.

    Returns ``None`` when the doc cannot be expanded safely (malformed times,
    an unparseable date bound, an unrecognised weekday set, or a weekday set
    that matches no day in the period) so the caller can fall back to the
    one-off ``start_at`` instead of raising or pricing zero classes.
    """
    status = str(doc.get("status") or "scheduled")
    if status == "cancelled":
        # Cancel is a soft delete; a cancelled template has no live dates. This
        # mirrors the catalog/roster synthesis and ``_series_occurrence_candidates``.
        return []
    start_known, start_date = _schedule_bound(doc, "start_date")
    end_known, end_date = _schedule_bound(doc, "end_date")
    if not start_known or not end_known:
        return None
    days = _weekday_labels(doc.get("days_of_week"))
    if not days:
        return None
    raw_start_time = doc.get("start_time")
    raw_end_time = doc.get("end_time")
    start_time = _coerce_schedule_time(raw_start_time)
    if start_time is None:
        if raw_start_time:
            # A non-ISO wall-clock string (e.g. "6:00 PM") used to be harmless
            # because this doc fell through to the one-off fallback; it must not
            # abort the whole monthly generation run.
            return None
        start_time = time(0, 0)
    end_time = _coerce_schedule_time(raw_end_time)
    if end_time is None:
        if raw_end_time:
            return None
        end_time = start_time
    occurrence_status = "scheduled" if status == "active" else status
    is_billable = occurrence_status in {"scheduled", "completed", "makeup"}
    current = period.start_at.date()
    if start_date is not None:
        current = max(start_date, current)
    period_last_day = date.fromordinal(period.end_at.date().toordinal() - 1)
    final = period_last_day
    if end_date is not None:
        final = min(end_date, final)
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
                    status=occurrence_status,
                    is_billable=is_billable,
                    timezone=timezone_name,
                )
            )
        current = date.fromordinal(current.toordinal() + 1)
    if not rows and end_date is None:
        # The weekday set matched nothing in a period the series should still be
        # running in: treat the template as unusable rather than quoting $0.
        return None
    return rows


def _session_occurrences(
    doc: dict[str, object],
    period: BillingPeriod,
) -> list[ClassOccurrence]:
    # ``period`` was built on this session's resolved clock (session ->
    # academy -> legacy), so its zone is the right fallback for a zoneless doc.
    timezone_name = str(doc.get("timezone") or period.timezone or LEGACY_FALLBACK_TIMEZONE)
    tz = ZoneInfo(timezone_name)
    session_id = str(doc.get("session_id") or doc.get("_id") or "")
    if doc.get("days_of_week"):
        rows = _recurring_occurrences(
            doc,
            period,
            session_id=session_id,
            timezone_name=timezone_name,
            tz=tz,
        )
        if rows is not None:
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


async def resolve_monthly_charge(
    *,
    repo: MongoPaymentRepository,
    enrollment: dict[str, object],
    session_doc: dict[str, object],
    period: str,
    now: datetime,
) -> tuple[int, int, int, str | None, TuitionDiscount | None, str]:
    """Return charge tuple for a monthly row, including the applied discount policy.

    This function owns all proration decisions; the repo class is a pure
    storage delegate here. A recurring tuition discount (issue #244), if active and
    effective for the period, is applied at monthly scale and threaded through the
    existing proration policy so discounted invoices stay consistent with proration.

    Public because the admin "Bill this month" path has to charge a month exactly
    what the monthly run would have charged it (#724): its own flat
    ``session_amount_cents`` read skipped first-month proration, the four-classes-
    per-meeting rule, and the ``billing_calculation_snapshots`` row that later
    withdrawal and cancellation credits are measured against. Resolving a period
    STAMPS that snapshot, so call it only for a charge you are about to write.
    """
    # The class fee FOR THIS MONTH: the stored fee, unless the owner scheduled
    # a plan price change that covers this class and month (PR 26). With no
    # change on record this is exactly ``session_amount_cents(session_doc)``.
    amount_cents = await class_fee_cents_for_period(repo._db, session_doc, period)
    billing_start = _coerce_datetime(
        enrollment.get("billing_start_at")
        or enrollment.get("enrolled_at")
        or enrollment.get("created_at")
    )
    enrollment_id = str(enrollment.get("enrollment_id") or enrollment.get("_id"))
    timezone_name = await resolve_session_doc_timezone(
        academy_timezone_lookup(repo._db), session_doc
    )
    billing_period = BillingPeriod.from_label(period, timezone_name=timezone_name)
    occurrences = await repo._occurrences_for_session(session_doc, billing_period)

    sibling = await resolve_sibling_discount(
        repo._db,
        enrollment=enrollment,
        period=period,
        period_start=billing_period.start_at.date(),
        now=now,
    )
    # A single TuitionDiscount keeps the ACH base, proration, snapshots and
    # recompute unchanged.
    policy = await weighed_tuition_discount(
        repo._discounts,
        enrollment_id=enrollment_id,
        billing_period=billing_period,
        sibling=sibling,
        monthly_price_cents=amount_cents,
    )
    mdc = monthly_discount_cents(policy, monthly_price_cents=amount_cents) if policy else 0

    # Not a first-month enrollment → full monthly tuition.
    #
    # The label has to be built in the session's timezone, because that is the
    # clock QuoteEnrollment labelled the checkout quote with and the clock
    # BillingPeriod.from_label built `billing_period` with two lines up. Using
    # the raw UTC instant here reads a month ahead for the several evening
    # hours before local month-end, so an enrollment created at 8:15pm Chicago
    # on Aug 31 (01:15 UTC Sep 1) was misread as a first-month enrollment for
    # September and re-prorated, undercharging a parent who attended the whole
    # month. It also broke the handshake with the checkout quote: the parent's
    # real prorated snapshot is labelled with the local month, so the
    # prior_consumed lookup below could never find it (#541).
    if billing_start is None or _local_period_label(billing_start, timezone_name) != period:
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
        return (
            amount_cents,
            discount,
            net,
            snapshot_id,
            policy if mdc > 0 else None,
            _tuition_line_description(period, snapshot),
        )

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
        return (
            0,
            0,
            0,
            str(prior_consumed.get("snapshot_id")),
            None,
            _tuition_line_description(period, None),
        )

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
    return (
        gross_prorated,
        discount,
        net_prorated,
        snapshot_id,
        policy if mdc > 0 else None,
        _tuition_line_description(period, snapshot),
    )


#: Insert-once record of each enrollment-month's sibling decision (migration 0237).
SIBLING_DECISIONS_COLLECTION = "sibling_discount_decisions"
_STUDENT_PARENT_FIELDS = ("parent_id", "parent_user_id")
#: identity's ``PARENT_REFERENCE_FIELDS`` (billing may not import identity).
_USER_REFERENCE_FIELDS = ("user_id", "firebase_uid", "auth_uid")


async def _academy_timezone(db: Any) -> str | None:
    """The academy's IANA zone, or ``None`` when unset or unreadable."""
    try:
        doc = await db["academies"].find_one({"academy_id": current_academy_id()})
    except Exception:
        logging.getLogger(__name__).warning(
            "monthly_generation_academy_timezone_unreadable; using UTC",
            exc_info=True,
        )
        return None
    return str((doc or {}).get("timezone") or "") or None


async def _active_billing_deferral(
    db: Any, *, academy_id: str, enrollment_id: str, period: str, today: date
) -> dict[str, Any] | None:
    cursor = db["enrollment_billing_deferrals"].find(
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
    date_str = MongoMonthlyBillingGenerator._date_str
    async for doc in cursor:
        resume_on = date_str(doc.get("resume_on"))
        if resume_on is not None and resume_on <= today_text:
            continue
        review_on = date_str(doc.get("review_on"))
        if review_on is not None and review_on <= today_text:
            continue
        expires_on = date_str(doc.get("expires_on"))
        if expires_on is not None and expires_on < today_text:
            continue
        return dict(doc)
    return None


async def monthly_skip_reason(
    db: Any,
    *,
    enrollment: Mapping[str, Any],
    period: str,
    today: date,
    academy_timezone: str,
) -> tuple[str, Any] | None:
    """Why the monthly run does not invoice this enrollment for ``period``, or
    ``None``: ``("deferral", row)``, ``("paused", None)``,
    ``("pending_cancellation", its period)`` or ``("skip_period", None)``.

    The one predicate for the run and the sibling family, so the family is
    built from exactly the enrollments the run bills (L9 C1 review).
    """
    enrollment_id = str(enrollment.get("enrollment_id") or enrollment.get("_id"))
    deferral = await _active_billing_deferral(
        db,
        academy_id=current_academy_id(),
        enrollment_id=enrollment_id,
        period=period,
        today=today,
    )
    if deferral is not None:
        return ("deferral", deferral)
    if str(enrollment.get("status") or "") == "paused":
        return ("paused", None)
    pending_cancellation_at = _coerce_datetime(enrollment.get("pending_cancellation_at"))
    if pending_cancellation_at is not None:
        # Issue #675 follow-up: an ``end_of_period`` self-cancel leaves the row
        # ``active`` until the hourly worker flips it at month end, and the
        # generation cron can run first (03:00 UTC vs a Chicago 04:59:59
        # run_at). Without this the family is minted — and emailed — an invoice
        # for the month they cancelled, which the worker then voids hours later.
        pending_period = _local_period_label(pending_cancellation_at, academy_timezone)
        if period > pending_period:
            return ("pending_cancellation", pending_period)
    if period in set(enrollment.get("skip_periods") or []):
        return ("skip_period", None)
    return None


async def _existing_period_invoice_id(db: Any, *, enrollment_id: str, period: str) -> str | None:
    """The month's tuition invoice under any id (monthly, "Bill this month",
    checkout first month), or ``None``. Void invoices do not count."""
    invoice_doc = await db["invoices"].find_one(
        {
            "academy_id": current_academy_id(),
            "enrollment_id": enrollment_id,
            "period": period,
            "is_deleted": {"$ne": True},
            "status": {"$ne": "void"},
            # A mid-period move adjustment (issue #669) carries the same
            # (enrollment_id, period) but is NOT the month's tuition invoice.
            # It is created later, so newest-first would hand it back here and
            # the recovery pass would mark the period complete with the tuition
            # invoice still missing.
            "source_type": {"$ne": MOVE_SOURCE_TYPE},
        },
        sort=[("created_at", -1), ("invoice_id", -1)],
    )
    if invoice_doc is None:
        return None
    return str(invoice_doc.get("invoice_id") or "")


def resolved_parent_id(enrollment: Mapping[str, Any], student: Mapping[str, Any] | None) -> str:
    """The family key, resolved exactly as the monthly run resolves it."""
    return str(
        enrollment.get("parent_id")
        or enrollment.get("parent_user_id")
        or (student or {}).get("parent_id")
        or (student or {}).get("parent_user_id")
        or ""
    )


async def _parent_aliases(db: Any, parent_id: str) -> frozenset[str]:
    """Every id the parent's ``users`` document answers to, plus ``parent_id``.

    Mirrors identity's ``resolve_parent_aliases``: one equality question per
    field and then ``_id``, never an ``$or`` across fields (#894).
    """
    projection = {"user_id": 1, "firebase_uid": 1, "auth_uid": 1}
    doc = None
    for field_name in _USER_REFERENCE_FIELDS:
        doc = await db["users"].find_one({field_name: parent_id}, projection, sort=[("_id", 1)])
        if doc is not None:
            break
    if doc is None:
        by_id: list[Any] = [parent_id]
        if ObjectId.is_valid(parent_id):
            by_id.append(ObjectId(parent_id))
        doc = await db["users"].find_one({"_id": {"$in": by_id}}, projection, sort=[("_id", 1)])
    values = [parent_id]
    if doc is not None:
        values += [doc.get(name) for name in (*_USER_REFERENCE_FIELDS, "_id")]
    return frozenset(str(value) for value in values if value)


async def resolve_sibling_discount(
    db: Any,
    *,
    enrollment: Mapping[str, Any],
    period: str,
    period_start: date,
    now: datetime,
) -> TuitionDiscount | None:
    """The automatic sibling policy for this enrollment-month, or ``None`` (L9 C1).

    Only this enrollment's row is ever written, the first time its month is
    priced, and every later pricing (retries, orphan recovery, "Bill this
    month") reuses it, even after the setting or the family changes.

    Without a row, the month is decided against the family's fixed points:

    1. Already billed under any non-void tuition invoice (the run's own
       lookup): no row and no discount, so an invoice is never repriced.
    2. A sibling is already decided at full price: billed with no row, or a
       row naming its own child as the full-price child that is billed or
       still in the family (it will reuse that row). That child is the
       full-price child, so this one is discounted.
    3. Otherwise the owner's rule picks the full-price child among the
       children with no decided enrollment, each weighed on all of its
       enrollments in the family.

    So a month keeps exactly one full-price child whatever the run order or a
    mid-run setting change, except when a full-price child with a row but no
    invoice leaves the family after a sibling was decided against it.
    Switched off with no row on record: ``None`` and nothing written.
    """
    enrollment_id = str(enrollment.get("enrollment_id") or enrollment.get("_id"))
    decision, outcome = await decide_sibling_discount(
        db, enrollment=enrollment, period=period, now=now
    )
    if decision is None:
        return None
    if outcome == "new":
        decisions = db[SIBLING_DECISIONS_COLLECTION]
        try:
            await decisions.insert_one(dict(decision))
        except DuplicateKeyError:
            decision = await decisions.find_one(
                {
                    "academy_id": decision["academy_id"],
                    "enrollment_id": enrollment_id,
                    "period": period,
                }
            )
            if decision is None:  # pragma: no cover - the unique key just refused us
                raise
    frozen_bps = _frozen_percent_bps(decision)
    if frozen_bps is None:
        return None
    return sibling_policy(
        enrollment_id=enrollment_id,
        student_id=str(enrollment.get("student_id") or ""),
        period=period,
        percent_bps=frozen_bps,
        period_start=period_start,
    )


SiblingDecisionOutcome = Literal["recorded", "new", "invoiced", "off"]


async def weighed_tuition_discount(
    discounts: MoveDiscountReader,
    *,
    enrollment_id: str,
    billing_period: BillingPeriod,
    sibling: TuitionDiscount | None,
    monthly_price_cents: int,
) -> TuitionDiscount | None:
    """The month's one tuition discount: the manual policy in effect for the
    period or the sibling one, whichever is larger (manual wins a tie). The
    monthly run prices with it and the admin badge previews with it."""
    manual = await discounts.get_active(enrollment_id)
    if manual is not None and not _policy_applies(manual, billing_period):
        manual = None
    return best_tuition_discount(manual, sibling, monthly_price_cents=monthly_price_cents)


async def decide_sibling_discount(
    db: Any, *, enrollment: Mapping[str, Any], period: str, now: datetime, page: bool = True
) -> tuple[dict[str, Any] | None, SiblingDecisionOutcome]:
    """This enrollment-month's sibling decision, read-only: ``(row, outcome)``.

    ``recorded``: the row on file. ``new``: the row the run would record now
    (``resolve_sibling_discount`` inserts it; the admin badge only shows it).
    ``invoiced`` / ``off``: no row and no discount, because the month is
    already billed or the setting is off. Rules: ``resolve_sibling_discount``.
    ``page=False`` keeps an unreadable setting out of Sentry (badge reads).
    """
    academy_id = current_academy_id()
    enrollment_id = str(enrollment.get("enrollment_id") or enrollment.get("_id"))
    student_id = str(enrollment.get("student_id") or "")
    key = {"academy_id": academy_id, "enrollment_id": enrollment_id, "period": period}
    decisions = db[SIBLING_DECISIONS_COLLECTION]
    decision = await decisions.find_one(key)
    if decision is not None:
        return dict(decision), "recorded"
    if await _existing_period_invoice_id(db, enrollment_id=enrollment_id, period=period):
        return None, "invoiced"
    offer = await _sibling_offer(db, academy_id, page=page)
    if offer is None:
        return None, "off"
    percent_bps, full_price_child, applies_to = offer
    parent_id, family, relatives = await _sibling_family(
        db, enrollment=enrollment, period=period, today=now.date()
    )
    in_family = {row.enrollment_id for row in family}
    decided: set[str] = set()  # children (student ids), not enrollments
    paid_full: set[str] = set()
    for member_id, member_student in relatives:
        if member_id == enrollment_id:
            continue
        row = await decisions.find_one({**key, "enrollment_id": member_id})
        invoiced = await _existing_period_invoice_id(db, enrollment_id=member_id, period=period)
        # A row with no invoice still binds while its enrollment stays in the
        # family: it will reuse that row when billed. Once it leaves, ignore it.
        if not invoiced and (row is None or member_id not in in_family):
            continue
        decided.add(member_student)
        if row is None or (
            not row.get("discounted") and row.get("full_price_student_id") == member_student
        ):
            paid_full.add(member_student)
    own = next((row for row in family if row.enrollment_id == enrollment_id), None)
    full_price = ""
    if own is not None and paid_full:
        full_price = own.student_id if own.student_id in paid_full else min(paid_full)
    elif own is not None:
        # Whole children only: excluding one of a child's enrollments would
        # change that child's tuition total or first start under the rule.
        undecided = [row for row in family if row.student_id not in decided]
        full_price = full_price_student(undecided, full_price_child=full_price_child) or ""
    discounted = own is not None and is_sibling_discounted(
        family, own, full_price=full_price, applies_to=applies_to
    )
    decision = {
        **key,
        "student_id": student_id,
        "parent_id": parent_id,
        "discounted": discounted,
        "percent_bps": percent_bps if discounted else None,
        "full_price_student_id": full_price,
        "full_price_child": full_price_child,
        "applies_to": applies_to,
        "family_enrollment_ids": sorted(row.enrollment_id for row in family),
        "decided_at": now,
    }
    return decision, "new"


async def preview_family_sibling_discount(
    db: Any,
    *,
    parent_id: str,
    now: datetime,
    discounts: MoveDiscountReader,
) -> dict[str, Any]:
    """Who gets the sibling discount on this family's invoices for the
    academy's current month. Read-only: it runs the same
    ``decide_sibling_discount`` and ``best_tuition_discount`` the monthly run
    prices with and writes nothing, so the admin badge cannot disagree with
    the invoice.

    Per active or paused enrollment: ``status`` is ``discounted``,
    ``full_price``, ``not_eligible`` or ``off``, with ``reason`` and the
    sibling ``percent_bps`` when one was decided.
    """
    academy_id = current_academy_id()
    period = _local_period_label(now, await _academy_timezone(db) or "UTC")
    offer = await _sibling_offer(db, academy_id, page=False)
    aliases = await _parent_aliases(db, parent_id)
    students = await _family_students(db, academy_id=academy_id, aliases=aliases)
    enrollments: list[Mapping[str, Any]] = []
    cursor = db["enrollments"].find(
        {
            "academy_id": academy_id,
            "student_id": {"$in": sorted(sid for sid in students if sid)},
            "status": {"$in": list(MONTHLY_RUN_ENROLLMENT_STATUSES)},
        },
        sort=[("student_id", 1), ("enrollment_id", 1)],
    )
    async for row in cursor:
        if resolved_parent_id(row, students.get(str(row.get("student_id") or ""))) in aliases:
            enrollments.append(row)
    student_of = {
        str(row.get("enrollment_id") or row.get("_id")): str(row.get("student_id") or "")
        for row in enrollments
    }
    rows = []
    for enrollment in enrollments:
        status, reason, percent_bps = await _sibling_preview_status(
            db,
            enrollment=enrollment,
            period=period,
            now=now,
            discounts=discounts,
            student_of=student_of,
            enabled=offer is not None,
        )
        rows.append(
            {
                "enrollment_id": str(enrollment.get("enrollment_id") or enrollment.get("_id")),
                "student_id": str(enrollment.get("student_id") or ""),
                "session_id": str(enrollment.get("session_id") or ""),
                "status": status,
                "reason": reason,
                "percent_bps": percent_bps,
            }
        )
    return {
        "period": period,
        "enabled": offer is not None,
        "percent_bps": offer[0] if offer else None,
        "enrollments": rows,
    }


async def _sibling_preview_status(
    db: Any,
    *,
    enrollment: Mapping[str, Any],
    period: str,
    now: datetime,
    discounts: MoveDiscountReader,
    student_of: Mapping[str, str],
    enabled: bool,
) -> tuple[str, str, int | None]:
    enrollment_id = str(enrollment.get("enrollment_id") or enrollment.get("_id"))
    student_id = str(enrollment.get("student_id") or "")
    decision, _ = await decide_sibling_discount(
        db, enrollment=enrollment, period=period, now=now, page=False
    )
    if decision is None:
        # Invoiced with no row and the setting off reads "off": it was never on.
        if not enabled:
            return "off", "setting_off", None
        return "not_eligible", "already_invoiced", None
    percent_bps = decision.get("percent_bps")
    if decision.get("discounted") and _valid_percent_bps(percent_bps):
        invoice_id = await _existing_period_invoice_id(
            db, enrollment_id=enrollment_id, period=period
        )
        session_doc = (
            await db["sessions"].find_one(
                {
                    "academy_id": current_academy_id(),
                    "session_id": str(enrollment.get("session_id") or ""),
                }
            )
            or {}
        )
        amount_cents = await class_fee_cents_for_period(db, session_doc, period)
        billing_period = BillingPeriod.from_label(
            period,
            timezone_name=await resolve_session_doc_timezone(
                academy_timezone_lookup(db), session_doc
            ),
        )
        sibling = sibling_policy(
            enrollment_id=enrollment_id,
            student_id=student_id,
            period=period,
            percent_bps=percent_bps,
            period_start=billing_period.start_at.date(),
        )
        if invoice_id:
            # Billed: the invoice's tuition_discount line names the policy it
            # was priced with (the rule apply_enrollment_move follows).
            line = await db["invoice_lines"].find_one(
                {
                    "academy_id": current_academy_id(),
                    "invoice_id": invoice_id,
                    "source_type": TUITION_DISCOUNT_SOURCE_TYPE,
                }
            )
            if line is None:
                return "not_eligible", "already_invoiced", None
            source_id = str(line.get("source_id") or "")
            if source_id.startswith(SIBLING_DISCOUNT_ID_PREFIX):
                return "discounted", "sibling_discount", percent_bps
            if source_id:
                return "not_eligible", "manual_discount_larger", percent_bps
        # Not billed yet, or a line with no source_id: weigh as the run does.
        best = await weighed_tuition_discount(
            discounts,
            enrollment_id=enrollment_id,
            billing_period=billing_period,
            sibling=sibling,
            monthly_price_cents=amount_cents,
        )
        if best is sibling:
            return "discounted", "sibling_discount", percent_bps
        return "not_eligible", "manual_discount_larger", percent_bps
    family = [str(eid) for eid in decision.get("family_enrollment_ids") or []]
    if enrollment_id not in family:
        return "not_eligible", "not_billed_this_month", None
    # Children with an enrollment still active or paused; an ended one is not a sibling.
    if len({student_of[eid] for eid in family if eid in student_of}) < 2:
        return "not_eligible", "only_one_child", None
    if decision.get("full_price_student_id") == student_id:
        return "full_price", "full_price_child", None
    return "not_eligible", "one_class_per_child", None


async def sibling_decision_percent_bps(db: Any, *, enrollment_id: str, period: str) -> int | None:
    """The recorded sibling percentage for an enrollment-month, if it was discounted."""
    decision = await db[SIBLING_DECISIONS_COLLECTION].find_one(
        {"academy_id": current_academy_id(), "enrollment_id": enrollment_id, "period": period}
    )
    return None if decision is None else _frozen_percent_bps(decision)


def _valid_percent_bps(value: Any) -> TypeGuard[int]:
    low, high = SIBLING_BOUNDS["percent_bps"]
    return isinstance(value, int) and not isinstance(value, bool) and low <= value <= high


def _frozen_percent_bps(decision: Mapping[str, Any]) -> int | None:
    """A discounted row's percentage, or ``None``. A hand-edited percentage out
    of range is paged and prices the month undiscounted rather than failing it."""
    if not decision.get("discounted"):
        return None
    value = decision.get("percent_bps")
    if _valid_percent_bps(value):
        return value
    logging.getLogger(__name__).warning("sibling_decision_invalid_percent")
    capture_message(
        "A sibling discount decision has an invalid percentage; "
        "that month was priced without the sibling discount",
        level="error",
    )
    return None


async def _sibling_offer(
    db: Any, academy_id: str, *, page: bool = True
) -> tuple[int, SiblingFullPriceChild, SiblingAppliesTo] | None:
    """``(percent_bps, full_price_child, applies_to)`` when the sibling block is
    switched on and valid, else ``None``.

    Reads the block alone, so a bad value elsewhere in the settings document
    cannot block the monthly run. A block switched on but unreadable, missing a
    value or with a percentage out of range (only a hand edit can store one;
    the API refuses it) is paged and applies no discount.
    """
    doc = await db["billing_settings"].find_one({"academy_id": academy_id}, {"sibling_discount": 1})
    try:
        offer = SiblingDiscount.model_validate((doc or {}).get("sibling_discount") or {})
        if not offer.enabled:
            return None
        percent_bps, full_price_child, applies_to = (
            offer.percent_bps,
            offer.full_price_child,
            offer.applies_to,
        )
        if (
            _valid_percent_bps(percent_bps)
            and full_price_child is not None
            and applies_to is not None
        ):
            return percent_bps, full_price_child, applies_to
        logging.getLogger(__name__).warning("sibling_discount_incomplete")
    except ValidationError:
        logging.getLogger(__name__).warning("sibling_discount_unreadable", exc_info=True)
    if not page:
        return None
    # Generating without it would overcharge every sibling family, so page.
    capture_message(
        "Monthly generation could not read the sibling discount setting; "
        "no sibling discount was applied and no decision recorded",
        level="error",
    )
    return None


async def _family_students(db: Any, *, academy_id: str, aliases: frozenset[str]) -> dict[str, Any]:
    """The parent's students by ``student_id``, found through either parent field."""
    students: dict[str, Any] = {}
    for field_name in _STUDENT_PARENT_FIELDS:
        cursor = db["students"].find(
            {"academy_id": academy_id, field_name: {"$in": sorted(aliases)}}
        )
        async for doc in cursor:
            students[str(doc.get("student_id") or "")] = doc
    return students


async def _sibling_family(
    db: Any, *, enrollment: Mapping[str, Any], period: str, today: date
) -> tuple[str, list[FamilyEnrollment], list[tuple[str, str]]]:
    """``(parent_id, family, relatives)`` for this enrollment's parent, under
    any of the parent's ids.

    ``family`` is the enrollments the run bills this period, with the run's
    filters: active, a monthly-invoiced billing type, not skipped by
    ``monthly_skip_reason``, and a class fee for the period. ``relatives`` is
    every enrollment of the same children whatever its status, as
    ``(enrollment_id, student_id)``: a month already billed counts even if the
    enrollment is paused or ended since.

    shortcut: children are found through the students' ``parent_id`` /
    ``parent_user_id`` (both indexed, 0010 and 0237) plus this enrollment's own
    student, so a child linked to the parent only by ``enrollment.parent_id``
    or ``parent_user_id`` is missed (no index there). Index and widen the
    lookup if such rows ever appear.
    """
    academy_id = current_academy_id()
    own_student_id = str(enrollment.get("student_id") or "")
    own_student = await db["students"].find_one(
        {"academy_id": academy_id, "student_id": own_student_id}
    )
    parent_id = resolved_parent_id(enrollment, own_student)
    if not parent_id:
        return "", [], []
    aliases = await _parent_aliases(db, parent_id)
    students = {
        own_student_id: own_student,
        **await _family_students(db, academy_id=academy_id, aliases=aliases),
    }
    academy_timezone = await _academy_timezone(db) or "UTC"
    family: list[FamilyEnrollment] = []
    relatives: list[tuple[str, str]] = []
    cursor = db["enrollments"].find(
        {"academy_id": academy_id, "student_id": {"$in": sorted(sid for sid in students if sid)}}
    )
    async for row in cursor:
        student_id = str(row.get("student_id") or "")
        if resolved_parent_id(row, students.get(student_id)) not in aliases:
            continue
        relatives.append((str(row.get("enrollment_id") or row.get("_id")), student_id))
        if str(row.get("status") or "") != MONTHLY_INVOICED_ENROLLMENT_STATUS:
            continue
        if str(row.get("billing_type") or "standard").lower() not in MONTHLY_INVOICED_BILLING_TYPES:
            continue
        if await monthly_skip_reason(
            db, enrollment=row, period=period, today=today, academy_timezone=academy_timezone
        ):
            continue
        session = await db["sessions"].find_one(
            {"academy_id": academy_id, "session_id": str(row.get("session_id") or "")}
        )
        fee = await class_fee_cents_for_period(db, session or {}, period)
        if fee <= 0:
            continue
        family.append(
            FamilyEnrollment(
                enrollment_id=str(row.get("enrollment_id") or row.get("_id")),
                student_id=student_id,
                list_fee_cents=fee,
                enrolled_at=_coerce_datetime(
                    row.get("billing_start_at") or row.get("enrolled_at") or row.get("created_at")
                ),
            )
        )
    return parent_id, family, relatives


def _policy_applies(policy: TuitionDiscount, billing_period: BillingPeriod) -> bool:
    """True when the policy's effective window overlaps the billing period."""
    return policy_applies_to_period(
        policy,
        period_start=billing_period.start_at.date(),
        period_end=billing_period.end_at.date(),
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
    """Build a CONSUMED monthly-tuition snapshot (no proration, full amount).

    ``final_amount_cents`` is the flat monthly price: a continuing family is
    charged exactly what they were charged before. What the snapshot now
    records is WHAT that price bought — four classes per weekly meeting, the
    same denominator the first-month quote uses — so a cancellation credit, a
    withdrawal refund and the invoice line all speak the owner's rule to both
    families in a five-date month (#730).

    The denominator never exceeds the month's own class list: a month that
    lays out three dates sold three, and ``billable_classes_per_period``'s
    floor (which keeps a degraded one-date synthesis from charging a joiner a
    whole month) would otherwise describe a full-price month as "3 of 4".
    """
    eligible = [
        occ
        for occ in sorted(occurrences, key=lambda o: o.occurrence_id)
        if FirstMonthProrationPolicy._is_eligible(occ, billing_period)
    ]
    snapshot_id = str(new_ulid())
    included = [occ.occurrence_id for occ in eligible]
    denominator = (
        min(
            billable_classes_per_period(eligible, timezone_name=billing_period.timezone),
            len(eligible),
        )
        if eligible
        else 0
    )
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
        billable_classes_denominator=denominator,
        proration_ratio=f"{denominator}/{denominator}" if eligible else "0/0",
        final_amount_cents=max(monthly_price_cents - discount_cents, 0),
        included_occurrence_ids=included,
        excluded_occurrences={},
        schedule_signature=schedule_signature(eligible, timezone_name=billing_period.timezone),
        calculated_at=now,
        calculated_by="SYSTEM",
    )
