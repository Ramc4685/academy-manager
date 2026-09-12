"""Apply a single cancelled class date to billing (issue #671).

INVARIANT — a family must never pay for a class the academy called off.
``CancelSessionOccurrence`` (enrollment context) reaches this use case through
the ``OccurrenceBillingSync`` port; composition wires it, do not simplify that
wiring away.

Policy (owner assumption, stated in the release note):

1. The date is written to ``session_occurrence_overrides`` as
   ``status="cancelled", is_billable=False``. That collection is the overlay
   the monthly generator already reads (``MongoPaymentRepository
   ._occurrences_for_session``). A family whose FIRST month is priced after
   this point is NOT charged for the date — but the date stays in the
   proration DENOMINATOR (``CANCELLED_AFTER_PRICING_STATUS``), so calling a
   class off can never make the remaining classes more expensive for the
   next family through the door.
2. Every family already enrolled is credited the date's share of the month
   through the account credit ledger: ``period charge / the classes that
   charge bought``. The charge is the period invoice's TUITION lines net of
   the tuition discount when an invoice exists; the CONSUMED first-month
   proration snapshot's amount when the month was paid at registration
   checkout (no invoice is ever keyed to that enrollment+period); else the
   monthly price net of discount, and the credit auto-applies when the
   generator mints the invoice. The divisor comes from the same snapshot —
   the classes the charge BOUGHT (``min(billable_remaining_classes, 4 per
   weekly meeting)``) for a prorated month, ``total_eligible_classes`` for a
   full one — because dividing a prorated charge by the month's whole class
   list under-credits by the proration ratio, and dividing it by more classes
   than it paid for over-credits every cancelled date. The generator's
   full-month amount is deliberately NOT changed: its completeness check
   compares the tuition line to the recomputed gross, and a gross that moved
   after the invoice existed would flag every later run as ``repair_failed``.
3. Skipped, with a reason recorded: a void period invoice (the family already
   left), a paused family with no invoice for the period (never charged), an
   enrollment whose first month is this period and is not priced yet (rule
   1 prorates it instead — crediting too would pay the date back twice), a
   date before the family's billing start, a date the family's charge never
   covered (``date_not_billed``), and a date absorbed by the month's free
   extra classes (``covered_by_free_classes``): while enough dates still run
   to deliver every class the charge bought, the family loses nothing.

Idempotent per ``(occurrence_id, enrollment_id)``: the credit carries
``source_type="occurrence_cancellation"`` and ``source_id=
"<occurrence>:<enrollment>"``, unique per academy (migration 0168). The
override write is an upsert. Re-running returns the credits already issued.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from backend.v2.contexts.billing.application.use_cases.apply_enrollment_lifecycle import (
    period_of,
)
from backend.v2.contexts.billing.domain.credits import (
    CLASS_CANCELLATION_SOURCE_TYPE,
    class_cancellation_credit_cents,
    class_cancellation_source_id,
)
from backend.v2.contexts.billing.domain.ledger import InvoiceLine, LedgerInvoice
from backend.v2.contexts.billing.domain.models import CreditLedgerEntry
from backend.v2.contexts.billing.domain.proration import (
    CANCELLED_AFTER_PRICING_STATUS,
    ClassOccurrence,
)
from backend.v2.shared.ids import new_ulid

log = logging.getLogger(__name__)

#: States that were never part of what the month cost. A date cancelled by an
#: EARLIER run of this use case is deliberately NOT here: the family paid one
#: monthly price for the schedule as it stood when the month was priced, so
#: every cancelled date is worth the same 1/N of it. Shrinking the divisor
#: after each cancellation would refund 1/4 + 1/3 of a four-class month.
_NEVER_SCHEDULED_STATUSES: frozenset[str] = frozenset({"holiday"})


@dataclass(frozen=True)
class SessionPricing:
    session_id: str
    timezone: str
    monthly_price_cents: int


@dataclass(frozen=True)
class BillableEnrollment:
    enrollment_id: str
    parent_id: str
    student_id: str
    status: str
    billing_start_at: datetime | None
    #: Recurring tuition discount at monthly scale, already bounded to the price.
    monthly_discount_cents: int = 0


@dataclass(frozen=True)
class PeriodChargeBasis:
    """The billing snapshot behind what a family was charged for one period.

    The credit divisor must be *the classes the charge actually bought*, not
    the period's whole occurrence list: a first-month invoice is
    ``base * remaining / total``, so its per-class value is
    ``charge / remaining``. Recomputing the divisor from the current schedule
    under-credits a late-generated first month by the proration ratio (#671).
    """

    calculation_type: str  # FIRST_MONTH_PRORATION | MONTHLY_TUITION
    final_amount_cents: int
    total_eligible_classes: int
    billable_remaining_classes: int
    #: The classes the charge bought. ``None`` on snapshots written before the
    #: four-classes-per-weekly-meeting rule, which were priced against
    #: ``billable_remaining_classes``.
    billable_classes_denominator: int | None = None
    included_occurrence_ids: tuple[str, ...] = ()


class OccurrenceCancellationReader(Protocol):
    async def session_pricing(self, session_id: str) -> SessionPricing | None: ...

    async def occurrences_for_period(
        self, *, session_id: str, period: str
    ) -> list[ClassOccurrence]:
        """The generator's own synthesis for the period, overrides applied."""
        ...

    async def period_charge_basis(
        self, *, enrollment_id: str, student_id: str, session_id: str, period: str
    ) -> PeriodChargeBasis | None:
        """What was priced for this family for this period, if anything."""
        ...

    async def enrollments_for_session(self, session_id: str) -> list[BillableEnrollment]: ...


class OccurrenceOverrideWriter(Protocol):
    async def mark_cancelled(
        self,
        *,
        session_id: str,
        occurrence_id: str,
        source_occurrence_id: str,
        reason: str,
        now: datetime,
    ) -> None: ...


class CancellationInvoiceLedger(Protocol):
    async def get_invoice_for_enrollment_period(
        self,
        enrollment_id: str,
        period: str,
        *,
        statuses: set[str] | None = None,
    ) -> LedgerInvoice | None: ...

    async def get_lines_for_invoice(self, invoice_id: str) -> list[InvoiceLine]: ...


class CancellationCreditLedger(Protocol):
    async def create_if_absent(self, entry: CreditLedgerEntry) -> bool: ...

    async def find_by_source(
        self, *, source_type: str, source_id: str
    ) -> CreditLedgerEntry | None: ...


class ApplyOccurrenceCancellationCommand(BaseModel):
    model_config = {"frozen": True}

    occurrence_id: str
    session_id: str
    start_at: datetime
    reason: str = Field(default="", max_length=500)
    actor_id: str | None = None


@dataclass(frozen=True)
class OccurrenceCreditDecision:
    enrollment_id: str
    credit_id: str | None
    amount_cents: int
    outcome: str  # credited | already_credited | skipped:<reason>


@dataclass(frozen=True)
class ApplyOccurrenceCancellationResult:
    period: str
    billing_occurrence_id: str | None
    override_written: bool
    decisions: tuple[OccurrenceCreditDecision, ...] = field(default_factory=tuple)

    @property
    def credits(self) -> dict[str, str]:
        """enrollment_id → credit_id for every family holding a credit for this date."""
        return {d.enrollment_id: d.credit_id for d in self.decisions if d.credit_id}

    @property
    def billing_result(self) -> str:
        issued = sum(1 for d in self.decisions if d.outcome == "credited")
        existing = sum(1 for d in self.decisions if d.outcome == "already_credited")
        skipped = sum(1 for d in self.decisions if d.outcome.startswith("skipped"))
        parts = [f"credited={issued}"]
        if existing:
            parts.append(f"existing={existing}")
        if skipped:
            parts.append(f"skipped={skipped}")
        parts.append("override=written" if self.override_written else "override=unmatched")
        return ",".join(parts)


class ApplyOccurrenceCancellation:
    def __init__(
        self,
        *,
        reader: OccurrenceCancellationReader,
        overrides: OccurrenceOverrideWriter,
        invoices: CancellationInvoiceLedger,
        credits: CancellationCreditLedger,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._reader = reader
        self._overrides = overrides
        self._invoices = invoices
        self._credits = credits
        self._now = clock

    async def execute(
        self, cmd: ApplyOccurrenceCancellationCommand
    ) -> ApplyOccurrenceCancellationResult:
        now = self._now()
        pricing = await self._reader.session_pricing(cmd.session_id)
        if pricing is None:
            log.warning(
                "apply_occurrence_cancellation_session_missing",
                extra={"session_id": cmd.session_id, "occurrence_id": cmd.occurrence_id},
            )
            return ApplyOccurrenceCancellationResult(
                period=period_of(cmd.start_at, None),
                billing_occurrence_id=None,
                override_written=False,
            )
        period = period_of(cmd.start_at, pricing.timezone)
        occurrences = await self._reader.occurrences_for_period(
            session_id=cmd.session_id, period=period
        )
        target = _match_occurrence(occurrences, cmd)
        if target is None:
            # The generator never priced this instant (a one-off session
            # outside its own window, or a schedule edited after the fact).
            # Nothing was charged for it, so there is nothing to credit; the
            # override is still recorded under the id the generator would use.
            billing_id = _synthesised_id(cmd, pricing.timezone)
            await self._overrides.mark_cancelled(
                session_id=cmd.session_id,
                occurrence_id=billing_id,
                source_occurrence_id=cmd.occurrence_id,
                reason=cmd.reason,
                now=now,
            )
            return ApplyOccurrenceCancellationResult(
                period=period, billing_occurrence_id=billing_id, override_written=False
            )

        # What the month's charge bought: every date the generator laid out
        # for the period, including the one being cancelled now and any
        # cancelled before it. See ``_NEVER_SCHEDULED_STATUSES``.
        priced = [o for o in occurrences if o.status not in _NEVER_SCHEDULED_STATUSES]
        await self._overrides.mark_cancelled(
            session_id=cmd.session_id,
            occurrence_id=target.occurrence_id,
            source_occurrence_id=cmd.occurrence_id,
            reason=cmd.reason,
            now=now,
        )

        decisions: list[OccurrenceCreditDecision] = []
        for enrollment in await self._reader.enrollments_for_session(cmd.session_id):
            decisions.append(
                await self._decide(
                    enrollment=enrollment,
                    pricing=pricing,
                    period=period,
                    priced=priced,
                    target=target,
                    cmd=cmd,
                    now=now,
                )
            )
        return ApplyOccurrenceCancellationResult(
            period=period,
            billing_occurrence_id=target.occurrence_id,
            override_written=True,
            decisions=tuple(decisions),
        )

    async def _tuition_cents(self, invoice: LedgerInvoice) -> int:
        """The period's TUITION on ``invoice``, net of its tuition discount.

        Not ``subtotal_cents - discount_cents``: ``recompute_totals`` rebuilds
        the subtotal from every line, so an equipment charge or registration
        fee added to the same monthly invoice inflates it — and once a line is
        added the invoice's own ``discount_cents`` is subtracted twice. Summing
        the tuition and discount lines is right in both states (#671).
        """
        try:
            lines = await self._invoices.get_lines_for_invoice(invoice.invoice_id)
        except Exception:  # pragma: no cover - defensive
            log.exception(
                "apply_occurrence_cancellation_invoice_lines_failed",
                extra={"invoice_id": invoice.invoice_id},
            )
            lines = []
        tuition = sum(line.amount_cents for line in lines if line.line_type in _TUITION_LINE_TYPES)
        if not lines:
            # Legacy invoice with no line documents: the header still holds
            # the monthly shape the generator wrote it with.
            tuition = invoice.subtotal_cents - invoice.discount_cents
        return max(tuition, 0)

    async def _decide(
        self,
        *,
        enrollment: BillableEnrollment,
        pricing: SessionPricing,
        period: str,
        priced: list[ClassOccurrence],
        target: ClassOccurrence,
        cmd: ApplyOccurrenceCancellationCommand,
        now: datetime,
    ) -> OccurrenceCreditDecision:
        source_id = class_cancellation_source_id(
            occurrence_id=cmd.occurrence_id, enrollment_id=enrollment.enrollment_id
        )
        existing = await self._credits.find_by_source(
            source_type=CLASS_CANCELLATION_SOURCE_TYPE, source_id=source_id
        )
        if existing is not None:
            return OccurrenceCreditDecision(
                enrollment.enrollment_id,
                existing.credit_id,
                existing.amount_cents,
                "already_credited",
            )
        if enrollment.status not in {"active", "paused"}:
            return _skip(enrollment, "enrollment_not_active")

        billing_start = enrollment.billing_start_at
        if billing_start is not None and target.start_at < billing_start:
            return _skip(enrollment, "before_billing_start")

        invoice = await self._invoices.get_invoice_for_enrollment_period(
            enrollment.enrollment_id, period
        )
        if invoice is not None and invoice.status == "void":
            return _skip(enrollment, "invoice_void")

        basis = await self._reader.period_charge_basis(
            enrollment_id=enrollment.enrollment_id,
            student_id=enrollment.student_id,
            session_id=cmd.session_id,
            period=period,
        )

        if invoice is not None:
            charge = await self._tuition_cents(invoice)
        elif basis is not None and basis.calculation_type == "FIRST_MONTH_PRORATION":
            # The family paid their first month at registration checkout: the
            # proration snapshot is CONSUMED, the Payment carries no
            # enrollment_id and no ledger invoice is keyed to
            # (enrollment, period), so ``get_invoice_for_enrollment_period``
            # finds nothing — but the generator will never re-price the month
            # either. Skipping here would leave them paying for a class the
            # academy called off (#671).
            charge = max(basis.final_amount_cents, 0)
        else:
            if enrollment.status == "paused":
                return _skip(enrollment, "paused_not_invoiced")
            if billing_start is not None and period_of(billing_start, pricing.timezone) == period:
                # Nothing priced yet. Rule 1 handles this family: their
                # first-month proration reads the overlay and excludes the
                # date from the numerator (while keeping it in the
                # denominator, so the month does not get more expensive).
                return _skip(enrollment, "first_month_proration_excludes_date")
            charge = max(pricing.monthly_price_cents - enrollment.monthly_discount_cents, 0)

        billed_classes, billed_ids = _billed_classes(
            basis=basis, priced=priced, billing_start=billing_start
        )
        free_extras = _free_extra_classes(basis)
        if free_extras and billed_ids is not None:
            # The month sold fewer classes than it scheduled (the "5th class
            # free" case). While enough dates still run to deliver everything
            # the family paid for, a cancellation costs them nothing, so there
            # is nothing to credit. Earlier cancellations of this family's
            # billed dates consume that slack one at a time; ``priced`` is
            # captured before this date's own override is written.
            already_cancelled = sum(
                1
                for occurrence in priced
                if occurrence.occurrence_id in billed_ids
                and occurrence.occurrence_id != target.occurrence_id
                and occurrence.status == CANCELLED_AFTER_PRICING_STATUS
            )
            if already_cancelled < free_extras:
                return _skip(enrollment, "covered_by_free_classes")
        if billed_ids is not None and target.occurrence_id not in billed_ids:
            # The charge never covered this date (it fell before the family's
            # enrollment, or inside the same-day cutoff). Crediting it would
            # hand back money that was never taken.
            return _skip(enrollment, "date_not_billed")
        amount = class_cancellation_credit_cents(
            period_charge_cents=charge, billable_classes=billed_classes
        )
        if amount <= 0:
            return _skip(enrollment, "zero_amount")

        local_day = target.start_at.astimezone(ZoneInfo(pricing.timezone)).date().isoformat()
        entry = CreditLedgerEntry(
            credit_id=str(new_ulid()),
            academy_id="",  # stamped by the tenant-scoped repository on write
            parent_id=enrollment.parent_id,
            student_id=enrollment.student_id,
            enrollment_id=enrollment.enrollment_id,
            type="CLASS_CANCELLATION_CREDIT",
            status="APPROVED",
            amount_cents=amount,
            remaining_amount_cents=amount,
            reason=_reason(local_day=local_day, note=cmd.reason, invoice=invoice),
            source_type=CLASS_CANCELLATION_SOURCE_TYPE,
            source_id=source_id,
            approved_by=cmd.actor_id,
            approved_at=now,
            created_at=now,
            updated_at=now,
        )
        created = await self._credits.create_if_absent(entry)
        if not created:
            again = await self._credits.find_by_source(
                source_type=CLASS_CANCELLATION_SOURCE_TYPE, source_id=source_id
            )
            return OccurrenceCreditDecision(
                enrollment.enrollment_id,
                again.credit_id if again else None,
                again.amount_cents if again else 0,
                "already_credited",
            )
        return OccurrenceCreditDecision(
            enrollment.enrollment_id, entry.credit_id, amount, "credited"
        )


#: Invoice lines that make up the period's TUITION. ``discount`` lines are
#: negative and belong here; a racket, a registration fee or any other
#: admin-added line does not — dividing those by the month's class count and
#: crediting the result would refund a purchase that has nothing to do with
#: the cancelled class (#671).
_TUITION_LINE_TYPES: frozenset[str] = frozenset({"tuition", "discount"})


def _billed_classes(
    *,
    basis: PeriodChargeBasis | None,
    priced: list[ClassOccurrence],
    billing_start: datetime | None,
) -> tuple[int, frozenset[str] | None]:
    """``(divisor, the ids the charge covered)`` for one family's period.

    The second element is ``None`` when membership is unknown — a full-month
    charge buys every class in the month, so there is nothing to check.
    """
    if basis is not None:
        if basis.calculation_type == "FIRST_MONTH_PRORATION" and basis.billable_remaining_classes:
            # ``charge / classes the charge bought``. For a first month that is
            # ``min(remaining, 4 * weekly meetings)``, NOT the whole remaining
            # list: a 5-class month is charged at the 4-class rate, so dividing
            # by 5 would credit each cancelled date more than it was billed at.
            return _paid_classes(basis), frozenset(basis.included_occurrence_ids)
        if basis.calculation_type == "MONTHLY_TUITION" and basis.total_eligible_classes:
            return basis.total_eligible_classes, None
    fallback = [o for o in priced if billing_start is None or o.start_at >= billing_start]
    return len(fallback), None


def _paid_classes(basis: PeriodChargeBasis) -> int:
    """The classes a first-month charge actually paid for."""
    denominator = basis.billable_classes_denominator or basis.billable_remaining_classes
    return min(basis.billable_remaining_classes, denominator)


def _free_extra_classes(basis: PeriodChargeBasis | None) -> int:
    """Scheduled-but-not-charged classes in a first month (the free extras)."""
    if basis is None or basis.calculation_type != "FIRST_MONTH_PRORATION":
        return 0
    return max(basis.billable_remaining_classes - _paid_classes(basis), 0)


def _skip(enrollment: BillableEnrollment, reason: str) -> OccurrenceCreditDecision:
    return OccurrenceCreditDecision(enrollment.enrollment_id, None, 0, f"skipped:{reason}")


def _match_occurrence(
    occurrences: list[ClassOccurrence], cmd: ApplyOccurrenceCancellationCommand
) -> ClassOccurrence | None:
    """The generator's row for this date: same instant first, same id second.

    The durable ``session_occurrences`` id and the generator's synthesised id
    are built by different writers and only agree for recurring templates, so
    the instant is the reliable key.
    """
    for occurrence in occurrences:
        if occurrence.start_at == cmd.start_at:
            return occurrence
    for occurrence in occurrences:
        if occurrence.occurrence_id == cmd.occurrence_id:
            return occurrence
    return None


def _synthesised_id(cmd: ApplyOccurrenceCancellationCommand, timezone_name: str) -> str:
    local = cmd.start_at.astimezone(ZoneInfo(timezone_name))
    return f"{cmd.session_id}:{local.date().isoformat()}:{local.strftime('%H:%M')}"


def _reason(*, local_day: str, note: str, invoice: LedgerInvoice | None) -> str:
    base = f"Class cancelled on {local_day}"
    if note:
        base = f"{base}: {note}"
    if invoice is not None:
        base = f"{base} (invoice {invoice.invoice_number or invoice.invoice_id})"
    return base[:500]
