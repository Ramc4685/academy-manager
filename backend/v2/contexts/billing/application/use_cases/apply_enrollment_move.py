"""Re-price the CURRENT billing period when an enrollment moves sessions (#669).

Policy (owner assumption, stated in the release note): for the period the
move takes effect in, the family owes or is owed the price difference for
the classes still to come; later periods are re-priced by the monthly
generator because it reads the enrollment's *current* session.

Decision table, once the effective period's invoice is found:

- no invoice yet for that period → do nothing. The generator has not run
  for it, and when it does it prices from the new session.
- delta > 0 and the invoice still accepts lines (open / draft /
  partially_paid) → append a ``move_proration`` line to it.
- delta > 0 but the invoice is already paid → mint a separate adjustment
  invoice through the ledger's idempotent ``create_invoice`` path. Lines are
  never corrected in place (they are ``$setOnInsert``), so a paid invoice is
  never re-opened. The new invoice carries ``enrollment_id`` and so follows
  the same autopay eligibility path as any other open invoice: the dunning
  worker decides whether and when to charge it; nothing charges here.
- delta < 0 → an APPROVED ``MOVE_PRORATION_CREDIT`` on the parent's credit
  ledger, the same ledger withdrawal credits use, applied to the next invoice.
- delta == 0 → record only.

Idempotency: one key per (tenant, enrollment, period, from, to). The
``@idempotent`` store returns the first result on a repeat; underneath, the
line lookup, ``create_invoice`` and the credit lookup are each keyed on the
same value so a crash between the write and the store put cannot double-apply.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from backend.v2.contexts.billing.application.ports import CreditLedgerRepository
from backend.v2.contexts.billing.application.use_cases.apply_enrollment_lifecycle import (
    period_of,
)
from backend.v2.contexts.billing.application.use_cases.invoice_numbering import (
    mint_invoice_number,
)
from backend.v2.contexts.billing.domain.ledger import InvoiceLine, LedgerInvoice, add_line
from backend.v2.contexts.billing.domain.models import CreditLedgerEntry
from backend.v2.contexts.billing.domain.proration import (
    BillingPeriod,
    ClassOccurrence,
    MoveProrationQuote,
    quote_move_proration,
)
from backend.v2.shared.idempotency import IdempotencyStore, idempotent
from backend.v2.shared.ids import new_ulid
from backend.v2.shared.tenancy import current_academy_id

log = logging.getLogger(__name__)

MOVE_LINE_TYPE = "move_proration"
MOVE_SOURCE_TYPE = "MOVE_PRORATION"
MOVE_CREDIT_TYPE = "MOVE_PRORATION_CREDIT"
BILLING_POLICY = "move_proration_current_period"

#: Invoice statuses that still accept a line (``domain.ledger.add_line``).
_LINE_ACCEPTING_STATUSES: frozenset[str] = frozenset({"open", "draft", "partially_paid"})

MoveOutcome = Literal["debited", "adjustment_invoiced", "credited", "no_change", "no_invoice"]


class MoveSessionSchedule(BaseModel):
    """What billing needs to know about one session for one period."""

    model_config = {"frozen": True}

    session_id: str
    monthly_price_cents: int = Field(ge=0)
    timezone: str
    occurrences: list[ClassOccurrence]


class MoveScheduleReader(Protocol):
    """Cross-context read of a session's price and period schedule.

    ``None`` when the session does not exist for the current tenant.
    """

    async def load(self, *, session_id: str, period: str) -> MoveSessionSchedule | None: ...


class MoveInvoiceLedger(Protocol):
    async def list_invoices_for_enrollment(self, enrollment_id: str) -> list[LedgerInvoice]: ...

    async def get_lines_for_invoice(self, invoice_id: str) -> list[InvoiceLine]: ...

    async def sum_allocations_for_invoice(self, invoice_id: str) -> int: ...

    async def save_invoice(self, invoice: LedgerInvoice) -> LedgerInvoice: ...

    async def save_line(self, line: InvoiceLine) -> InvoiceLine: ...

    async def create_invoice(
        self,
        invoice: LedgerInvoice,
        *,
        lines: list[InvoiceLine],
        idempotency_key: str,
    ) -> LedgerInvoice: ...


AcademyTimezoneReader = Callable[[], Awaitable[str | None]]


class ApplyEnrollmentMoveCommand(BaseModel):
    model_config = {"frozen": True}

    enrollment_id: str
    from_session_id: str
    to_session_id: str
    effective_at: datetime
    reason: str = Field(default="", max_length=500)
    actor_id: str | None = None


class ApplyEnrollmentMoveResult(BaseModel):
    model_config = {"frozen": True}

    outcome: MoveOutcome
    effective_period: str
    delta_cents: int = 0
    from_share_cents: int = 0
    to_share_cents: int = 0
    invoice_id: str | None = None
    line_id: str | None = None
    credit_id: str | None = None
    idempotency_key: str

    @property
    def billing_result(self) -> str:
        """Short audit label for the enrollment lifecycle event."""
        if self.outcome in {"debited", "adjustment_invoiced"}:
            return f"debit:{self.delta_cents}"
        if self.outcome == "credited":
            return f"credit:{-self.delta_cents}"
        return self.outcome

    @property
    def metadata(self) -> dict[str, str]:
        out = {
            "outcome": self.outcome,
            "effective_period": self.effective_period,
            "delta_cents": str(self.delta_cents),
            "from_share_cents": str(self.from_share_cents),
            "to_share_cents": str(self.to_share_cents),
        }
        if self.invoice_id:
            out["invoice_id"] = self.invoice_id
        if self.line_id:
            out["line_id"] = self.line_id
        if self.credit_id:
            out["credit_id"] = self.credit_id
        return out


def move_idempotency_key(
    *,
    academy_id: str,
    enrollment_id: str,
    period: str,
    from_session_id: str,
    to_session_id: str,
) -> str:
    # The idempotency store is global, so the tenant must be part of the key.
    return f"move-proration:{academy_id}:{enrollment_id}:{period}:{from_session_id}:{to_session_id}"


class ApplyEnrollmentMove:
    def __init__(
        self,
        *,
        ledger: MoveInvoiceLedger,
        credits: CreditLedgerRepository,
        schedules: MoveScheduleReader,
        idempotency_store: IdempotencyStore,
        academy_timezone: AcademyTimezoneReader | None = None,
        counters: Any | None = None,
        settings: Any | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._ledger = ledger
        self._credits = credits
        self._schedules = schedules
        self._idempotency_store = idempotency_store
        self._academy_timezone = academy_timezone
        self._counters = counters
        self._settings = settings
        self._now = clock

    async def execute(self, cmd: ApplyEnrollmentMoveCommand) -> ApplyEnrollmentMoveResult:
        timezone_name = await self._academy_timezone() if self._academy_timezone else None
        period = period_of(cmd.effective_at, timezone_name)
        key = move_idempotency_key(
            academy_id=current_academy_id(),
            enrollment_id=cmd.enrollment_id,
            period=period,
            from_session_id=cmd.from_session_id,
            to_session_id=cmd.to_session_id,
        )
        result = await self._execute_once(cmd, period=period, key=key)
        log.info(
            "apply_enrollment_move",
            extra={
                "enrollment_id": cmd.enrollment_id,
                "from_session_id": cmd.from_session_id,
                "to_session_id": cmd.to_session_id,
                "effective_period": period,
                "outcome": result.outcome,
                "delta_cents": result.delta_cents,
            },
        )
        return result

    @idempotent(
        key_from=lambda self, cmd, *, period, key: key,
        result_type=ApplyEnrollmentMoveResult,
    )
    async def _execute_once(
        self, cmd: ApplyEnrollmentMoveCommand, *, period: str, key: str
    ) -> ApplyEnrollmentMoveResult:
        now = self._now()
        invoice = self._period_invoice(
            await self._ledger.list_invoices_for_enrollment(cmd.enrollment_id), period
        )
        if invoice is None:
            return ApplyEnrollmentMoveResult(
                outcome="no_invoice", effective_period=period, idempotency_key=key
            )

        quote = await self._quote(cmd, period=period)
        base = {
            "effective_period": period,
            "delta_cents": quote.delta_cents,
            "from_share_cents": quote.from_share_cents,
            "to_share_cents": quote.to_share_cents,
            "idempotency_key": key,
        }
        if quote.delta_cents == 0:
            return ApplyEnrollmentMoveResult(
                outcome="no_change", invoice_id=invoice.invoice_id, **base
            )
        if quote.delta_cents < 0:
            credit = await self._credit(cmd, invoice=invoice, quote=quote, key=key, now=now)
            return ApplyEnrollmentMoveResult(
                outcome="credited",
                invoice_id=invoice.invoice_id,
                credit_id=credit.credit_id,
                **base,
            )
        if invoice.status in _LINE_ACCEPTING_STATUSES:
            line = await self._debit_existing(cmd, invoice=invoice, quote=quote, key=key, now=now)
            return ApplyEnrollmentMoveResult(
                outcome="debited", invoice_id=invoice.invoice_id, line_id=line.line_id, **base
            )
        adjustment, line = await self._mint_adjustment(
            cmd, paid_invoice=invoice, quote=quote, key=key, now=now
        )
        return ApplyEnrollmentMoveResult(
            outcome="adjustment_invoiced",
            invoice_id=adjustment.invoice_id,
            line_id=line.line_id,
            **base,
        )

    # -- helpers ----------------------------------------------------------

    @staticmethod
    def _period_invoice(invoices: list[LedgerInvoice], period: str) -> LedgerInvoice | None:
        """The invoice the period was billed on. Prefer one that still takes
        lines; otherwise the paid one (an adjustment invoice will be minted).
        Void invoices and earlier move adjustments are not "the period invoice"."""
        candidates = [
            inv
            for inv in invoices
            if inv.period == period and inv.status != "void" and inv.source_type != MOVE_SOURCE_TYPE
        ]
        for inv in candidates:
            if inv.status in _LINE_ACCEPTING_STATUSES:
                return inv
        return candidates[0] if candidates else None

    async def _quote(self, cmd: ApplyEnrollmentMoveCommand, *, period: str) -> MoveProrationQuote:
        from_schedule = await self._schedules.load(session_id=cmd.from_session_id, period=period)
        to_schedule = await self._schedules.load(session_id=cmd.to_session_id, period=period)
        effective_at = (
            cmd.effective_at
            if cmd.effective_at.tzinfo is not None
            else cmd.effective_at.replace(tzinfo=UTC)
        )
        known = to_schedule or from_schedule
        timezone_name = known.timezone if known is not None else "UTC"
        billing_period = BillingPeriod.from_label(period, timezone_name=timezone_name)
        return quote_move_proration(
            period=billing_period,
            from_session_id=cmd.from_session_id,
            to_session_id=cmd.to_session_id,
            from_price_cents=from_schedule.monthly_price_cents if from_schedule else 0,
            to_price_cents=to_schedule.monthly_price_cents if to_schedule else 0,
            from_occurrences=list(from_schedule.occurrences) if from_schedule else [],
            to_occurrences=list(to_schedule.occurrences) if to_schedule else [],
            effective_at=effective_at,
        )

    @staticmethod
    def _description(quote: MoveProrationQuote) -> str:
        return (
            f"Session move {quote.billing_period_label}: "
            f"{quote.to_remaining_classes}/{quote.to_total_classes} classes in new session "
            f"less {quote.from_remaining_classes}/{quote.from_total_classes} in previous"
        )

    def _line(
        self, *, invoice: LedgerInvoice, quote: MoveProrationQuote, key: str, now: datetime
    ) -> InvoiceLine:
        return InvoiceLine(
            line_id=f"line-{new_ulid()}",
            academy_id=invoice.academy_id,
            invoice_id=invoice.invoice_id,
            line_type=MOVE_LINE_TYPE,
            description=self._description(quote),
            quantity=1,
            unit_amount_cents=quote.delta_cents,
            amount_cents=quote.delta_cents,
            source_type=MOVE_SOURCE_TYPE,
            source_id=key,
            created_at=now,
        )

    async def _debit_existing(
        self,
        cmd: ApplyEnrollmentMoveCommand,
        *,
        invoice: LedgerInvoice,
        quote: MoveProrationQuote,
        key: str,
        now: datetime,
    ) -> InvoiceLine:
        lines = await self._ledger.get_lines_for_invoice(invoice.invoice_id)
        for line in lines:
            if line.source_type == MOVE_SOURCE_TYPE and line.source_id == key:
                return line  # already applied by an earlier attempt
        new_line = self._line(invoice=invoice, quote=quote, key=key, now=now)
        allocated = await self._ledger.sum_allocations_for_invoice(invoice.invoice_id)
        updated, _ = add_line(invoice, lines, new_line, now=now, allocated_cents=allocated)
        await self._ledger.save_line(new_line)
        await self._ledger.save_invoice(updated)
        return new_line

    async def _mint_adjustment(
        self,
        cmd: ApplyEnrollmentMoveCommand,
        *,
        paid_invoice: LedgerInvoice,
        quote: MoveProrationQuote,
        key: str,
        now: datetime,
    ) -> tuple[LedgerInvoice, InvoiceLine]:
        invoice_id = f"inv-move-{new_ulid()}"
        invoice_number = await mint_invoice_number(
            billing_counters=self._counters,
            billing_settings=self._settings,
            academy_id=paid_invoice.academy_id,
            period=paid_invoice.period,
        )
        draft = LedgerInvoice(
            invoice_id=invoice_id,
            academy_id=paid_invoice.academy_id,
            parent_id=paid_invoice.parent_id,
            student_id=paid_invoice.student_id,
            enrollment_id=cmd.enrollment_id,
            period=paid_invoice.period,
            status="open",
            subtotal_cents=quote.delta_cents,
            discount_cents=0,
            total_cents=quote.delta_cents,
            balance_due_cents=quote.delta_cents,
            currency=paid_invoice.currency,
            due_date=(now + timedelta(days=await self._invoice_due_days())).date(),
            invoice_number=invoice_number,
            source_type=MOVE_SOURCE_TYPE,
            source_id=key,
            created_at=now,
            updated_at=now,
        )
        line = self._line(invoice=draft, quote=quote, key=key, now=now)
        # ``create_invoice`` is idempotent on the key: a retry returns the
        # invoice minted the first time (with its own line ids), not a second one.
        stored = await self._ledger.create_invoice(draft, lines=[line], idempotency_key=key)
        stored_lines = await self._ledger.get_lines_for_invoice(stored.invoice_id)
        return stored, stored_lines[0] if stored_lines else line

    async def _invoice_due_days(self) -> int:
        if self._settings is None:
            return 7
        try:
            settings = await self._settings.get()
        except Exception:
            log.exception("apply_enrollment_move_settings_unreadable")
            return 7
        return int(getattr(settings, "invoice_due_days", 7) or 0)

    async def _credit(
        self,
        cmd: ApplyEnrollmentMoveCommand,
        *,
        invoice: LedgerInvoice,
        quote: MoveProrationQuote,
        key: str,
        now: datetime,
    ) -> CreditLedgerEntry:
        existing = await self._credits.find_active_for_enrollment(
            enrollment_id=cmd.enrollment_id, type=MOVE_CREDIT_TYPE
        )
        if existing is not None and existing.source_id == key:
            return existing
        amount = -quote.delta_cents
        entry = CreditLedgerEntry(
            credit_id=str(new_ulid()),
            academy_id=invoice.academy_id,
            parent_id=invoice.parent_id,
            student_id=invoice.student_id,
            enrollment_id=cmd.enrollment_id,
            invoice_id=invoice.invoice_id,
            type=MOVE_CREDIT_TYPE,
            status="APPROVED",
            amount_cents=amount,
            remaining_amount_cents=amount,
            currency=invoice.currency,
            reason=cmd.reason or self._description(quote),
            source_type=MOVE_SOURCE_TYPE,
            source_id=key,
            approved_by=cmd.actor_id,
            approved_at=now,
            expires_at=now + timedelta(days=365),
            created_at=now,
            updated_at=now,
        )
        await self._credits.create(entry)
        return entry
