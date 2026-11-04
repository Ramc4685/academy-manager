"""Automated late fees on overdue invoices (issue #552).

``late_fee_cents`` and ``grace_days`` have been editable academy settings for
a long time (``billing_rules.py``), but nothing read them: an owner could
configure a late fee and a grace period and no overdue invoice ever accrued a
cent. This pass, run on the dunning scheduler tick, is what makes them real.

Rules, in the order they are checked:

* **$0 (or unset) fee is a no-op.** No query, no line, no audit row. Turning
  the fee off is how an academy opts out, so it must cost nothing.
* **Only ``open``/``partially_paid`` invoices with a balance.** ``paid``,
  ``void`` and ``draft`` are never touched — :func:`add_line` refuses the
  first two anyway, and charging a draft would bill work not yet finalised.
* **The grace period must have fully elapsed**: the fee lands the day *after*
  ``due_date + grace_days``, so the last grace day is still free. "Day" is the
  academy's calendar day, not UTC's: in Chicago the UTC date turns over
  around 7 pm, which charged the fee on the evening of the last free day.
* **Turning the fee on never back-charges.** When the fee goes from unset/$0
  to a positive amount the academy records ``late_fee_effective_from``; an
  invoice whose grace period had already ended by that day is left alone. The
  first hourly pass used to charge the oldest 200 overdue invoices at once.
  Academies that switched the fee on before the date was recorded have none,
  and keep being treated exactly as before.
* **One fee per invoice, ever.** The guard is a check-then-add over the
  invoice's existing lines, so a hand-added late fee also suppresses the
  automatic one — the parent is never charged twice for the same lateness.
  Operators only got a ``late_fee`` option in the admin "Add charge" dropdown
  alongside this feature; every late fee entered before that is sitting on the
  invoice as a ``fee`` or ``adjustment`` line whose description says so, so the
  guard matches those by keyword too (see :func:`_is_late_fee_line`). Migration
  0181 backs the guard with a partial unique index on the policy-written lines.
* **Autopay families still inside the retry ladder are skipped.** Their card
  is being retried on our schedule; the money is not late because the parent
  ignored us. Once the ladder finishes (``dunned``/``suppressed``/``resolved``)
  the invoice becomes an ordinary overdue one and the next pass charges it.

The fee raises ``balance_due_cents``, so the next dunning notice — which reads
that field — quotes the new total with no change to the notifier.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from backend.v2.contexts.billing.application.ports import LedgerRepository
from backend.v2.contexts.billing.application.use_cases.add_invoice_line import (
    AddInvoiceLine,
    AddInvoiceLineCommand,
)
from backend.v2.contexts.billing.application.use_cases.billing_rules import AcademyFeesReader
from backend.v2.contexts.billing.application.use_cases.billing_settings_admin import (
    BillingAuditAppender,
)
from backend.v2.contexts.billing.domain.billing_audit import BillingAuditEntry
from backend.v2.contexts.billing.domain.ledger import InvoiceLine, LedgerInvoice
from backend.v2.shared.ids import new_ulid

log = logging.getLogger(__name__)

#: Line type for a late fee. Shared with the manual ``add_invoice_line`` path
#: on purpose: the idempotency guard treats a hand-added late fee as "already
#: charged", so an operator who got there first is not doubled up on.
LATE_FEE_LINE_TYPE = "late_fee"

#: Line types an operator could reach *before* ``late_fee`` was offered in the
#: admin "Add charge" dropdown. A late fee typed in back then is a plain
#: ``fee``/``adjustment`` line, so matching the type alone would miss it and
#: charge the family a second time for the same lateness.
LEGACY_LATE_FEE_LINE_TYPES = frozenset({"fee", "adjustment"})

#: Description keywords that identify one of those legacy lines as a late fee.
#: Matched case-insensitively on the operator-typed description; deliberately
#: narrow, since a false positive silently forgives a real fee.
LEGACY_LATE_FEE_KEYWORDS = ("late fee", "late-fee", "late charge", "late payment fee")

#: Marks the lines *this policy* wrote, as opposed to a hand-added one. The
#: unique index (migration 0181) is scoped to this value so it can never
#: collide with fees an operator entered before the automation existed.
LATE_FEE_SOURCE_TYPE = "late_fee_policy"

#: Audit actor for an unattended write. Mirrors the other worker-written
#: entries: a human id would be a lie about who decided this.
LATE_FEE_ACTOR_ID = "system:late_fee_policy"

#: Rows fetched per query, and the most pages one tick will walk. 50 pages of
#: 200 is 10,000 overdue invoices per academy per hour, far beyond any real
#: academy; the cap only stops a runaway loop.
LATE_FEE_PAGE_SIZE = 200
LATE_FEE_MAX_PAGES = 50


def _is_late_fee_line(line: InvoiceLine) -> bool:
    """Has this invoice already been charged a late fee, by anyone?

    ``late_fee`` covers this policy's own lines and anything added through the
    dropdown from now on. The keyword arm covers the fees academies have been
    adding by hand for years under ``fee``/``adjustment`` — without it the very
    academies that were diligent about late fees would be the ones whose
    parents got double-charged the first time this pass ran.
    """
    if line.line_type == LATE_FEE_LINE_TYPE:
        return True
    if line.line_type not in LEGACY_LATE_FEE_LINE_TYPES:
        return False
    description = (line.description or "").casefold()
    return any(keyword in description for keyword in LEGACY_LATE_FEE_KEYWORDS)


class DunningRetryLookup(Protocol):
    """Read-only sliver of the dunning store.

    Deliberately not the full ``DunningStateRepository``: this pass has no
    business claiming, parking or finishing an attempt, and a narrow port is
    what keeps the ladder's lifecycle owned by ``ProcessDunningRetries``.
    """

    async def has_active_retry(self, invoice_id: str) -> bool: ...


class ApplyLateFeesResult(BaseModel):
    model_config = {"frozen": True}

    scanned: int = 0
    applied: int = 0
    skipped_existing: int = 0
    skipped_in_retry: int = 0
    fee_cents_applied: int = 0


class ApplyLateFees:
    def __init__(
        self,
        *,
        ledger: LedgerRepository,
        add_line: AddInvoiceLine,
        fees: AcademyFeesReader,
        dunning: DunningRetryLookup | None = None,
        audit: BillingAuditAppender | None = None,
        academy_timezone: Callable[[str], Awaitable[str | None]] | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._ledger = ledger
        self._add_line = add_line
        self._fees = fees
        self._dunning = dunning
        self._audit = audit
        self._academy_timezone = academy_timezone
        self._now = clock

    async def execute(
        self,
        *,
        academy_id: str,
        page_size: int = LATE_FEE_PAGE_SIZE,
        max_pages: int = LATE_FEE_MAX_PAGES,
    ) -> ApplyLateFeesResult:
        fees = await self._fees.execute(academy_id)
        fee_cents = int(fees.late_fee_cents or 0)
        if fee_cents <= 0:
            return ApplyLateFeesResult()
        grace_days = max(int(fees.grace_days or 0), 0)

        now = self._now()
        today = await self._local_date(academy_id, now)
        # `due_before` is exclusive: an invoice due exactly `grace_days` ago is
        # spending its last free day today and must not be charged until
        # tomorrow.
        due_before = today - timedelta(days=grace_days)
        # Inclusive floor: an invoice whose last free day (due + grace) fell on
        # or after the day the fee was switched on became late under the fee.
        effective_from = getattr(fees, "late_fee_effective_from", None)
        due_on_or_after = (
            await self._local_date(academy_id, effective_from) - timedelta(days=grace_days)
            if isinstance(effective_from, datetime)
            else None
        )

        counts = {
            "scanned": 0,
            "applied": 0,
            "skipped_existing": 0,
            "skipped_in_retry": 0,
            "fee_cents_applied": 0,
        }
        after: tuple[date, str] | None = None
        for _ in range(max_pages):
            invoices = await self._ledger.list_overdue_invoices(
                due_before=due_before,
                due_on_or_after=due_on_or_after,
                after=after,
                limit=page_size,
            )
            for invoice in invoices:
                await self._consider(invoice, counts, fee_cents, grace_days, now)
            if len(invoices) < page_size:
                break
            after = (invoices[-1].due_date, invoices[-1].invoice_id)
        return ApplyLateFeesResult(**counts)

    async def _consider(
        self,
        invoice: LedgerInvoice,
        counts: dict[str, int],
        fee_cents: int,
        grace_days: int,
        now: datetime,
    ) -> None:
        counts["scanned"] += 1
        if invoice.status not in ("open", "partially_paid") or invoice.balance_due_cents <= 0:
            return
        lines = await self._ledger.get_lines_for_invoice(invoice.invoice_id)
        if any(_is_late_fee_line(line) for line in lines):
            counts["skipped_existing"] += 1
            return
        if self._dunning is not None and await self._dunning.has_active_retry(invoice.invoice_id):
            counts["skipped_in_retry"] += 1
            return
        await self._charge(invoice, fee_cents=fee_cents, grace_days=grace_days, now=now)
        counts["applied"] += 1
        counts["fee_cents_applied"] += fee_cents

    async def _local_date(self, academy_id: str, moment: datetime) -> date:
        """``moment``'s calendar date on the academy's clock (UTC when unset)."""
        aware = moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)
        if self._academy_timezone is None:
            return aware.date()
        try:
            zone = await self._academy_timezone(academy_id)
            return aware.astimezone(ZoneInfo(zone)).date() if zone else aware.date()
        except Exception:
            # A bad zone name must not stop collection; UTC is the old rule.
            log.warning("late_fee_timezone_unresolved", extra={"academy_id": academy_id})
            return aware.date()

    async def _charge(
        self, invoice: LedgerInvoice, *, fee_cents: int, grace_days: int, now: datetime
    ) -> None:
        result = await self._add_line.execute(
            AddInvoiceLineCommand(
                invoice_id=invoice.invoice_id,
                description=f"Late fee — {invoice.period} invoice past due",
                line_type=LATE_FEE_LINE_TYPE,
                quantity=1,
                unit_amount_cents=fee_cents,
                source_type=LATE_FEE_SOURCE_TYPE,
                source_id=invoice.invoice_id,
            )
        )
        log.info(
            "late_fee_applied",
            extra={
                "invoice_id": invoice.invoice_id,
                "academy_id": invoice.academy_id,
                "fee_cents": fee_cents,
            },
        )
        if self._audit is None:
            return
        await self._audit.append(
            BillingAuditEntry(
                audit_id=f"audit-{new_ulid()}",
                academy_id=invoice.academy_id,
                action="late_fee_applied",
                actor_id=LATE_FEE_ACTOR_ID,
                at=now,
                invoice_id=invoice.invoice_id,
                parent_id=invoice.parent_id,
                reason=f"due {invoice.due_date.isoformat()} + {grace_days}d grace elapsed",
                before={"balance_due_cents": invoice.balance_due_cents},
                after={"balance_due_cents": result.invoice.balance_due_cents},
            )
        )
