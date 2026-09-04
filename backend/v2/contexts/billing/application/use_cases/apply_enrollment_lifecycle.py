"""Apply an enrollment lifecycle transition to billing (issue #651).

INVARIANT — a family must never be charged for a class they will not attend.
Every enrollment transition that stops attendance (cancel, withdraw, session
cancelled, pause) MUST reach this use case, and every transition that restores
attendance (resume) MUST reach it too. Composition wires this into the
enrollment use cases; do not "simplify" that wiring away.

Policy (owner decision 2026-09-04):
- Cancel / withdraw mid-month: the CURRENT period stays payable in full. Only
  invoices for LATER periods are voided. No refund, no proration on the way out.
- Join mid-month proration is a separate policy (``domain/proration.py``) and is
  not touched here.
- Only invoices with no money recorded are voided (open / draft with the full
  balance still due). A future invoice that already has a partial payment is
  left alone and reported so an admin can credit it by hand.

Side effects, all idempotent:
1. Void unpaid invoices for periods after the effective period.
2. Move the per-enrollment autopay status (disabled on cancel/withdraw/session
   cancel, paused on pause, active on resume). A rejected transition (for
   example an ``offered`` enrollment that was never set up) is reported, not
   raised — there is nothing to charge in that case.
3. Suppress the dunning ladder of every voided invoice so the hourly worker
   stops re-claiming it.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Literal, Protocol
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from backend.v2.contexts.billing.domain.ledger import LedgerInvoice, void_invoice

log = logging.getLogger(__name__)

LifecycleTransition = Literal["cancelled", "withdrawn", "session_cancelled", "paused", "resumed"]

#: Statuses that mean "attendance stopped": future invoices are voided.
STOPPING_TRANSITIONS: frozenset[str] = frozenset(
    {"cancelled", "withdrawn", "session_cancelled", "paused"}
)

#: Autopay status each transition lands on. ``resumed`` re-enables collection.
AUTOPAY_STATUS_FOR_TRANSITION: dict[str, str] = {
    "cancelled": "disabled",
    "withdrawn": "disabled",
    "session_cancelled": "disabled",
    "paused": "paused",
    "resumed": "active",
}

#: Only invoices with no money recorded may be voided automatically.
_VOIDABLE_STATUSES: frozenset[str] = frozenset({"open", "draft"})


class LifecycleInvoiceLedger(Protocol):
    async def list_invoices_for_enrollment(self, enrollment_id: str) -> list[LedgerInvoice]: ...

    async def save_invoice(self, invoice: LedgerInvoice) -> LedgerInvoice: ...


class LifecycleAutopayGateway(Protocol):
    async def set_autopay_enrollment_status(self, *, enrollment_id: str, status: str) -> bool: ...


class LifecycleDunningSuppressor(Protocol):
    async def suppress_for_invoice(
        self, *, invoice_id: str, reason: str, now: datetime
    ) -> bool: ...


AcademyTimezoneReader = Callable[[], Awaitable[str | None]]


class ApplyEnrollmentLifecycleCommand(BaseModel):
    model_config = {"frozen": True}

    enrollment_id: str
    transition: LifecycleTransition
    effective_at: datetime
    reason: str = Field(default="", max_length=500)
    actor_id: str | None = None


class ApplyEnrollmentLifecycleResult(BaseModel):
    model_config = {"frozen": True}

    transition: LifecycleTransition
    effective_period: str
    voided_invoice_ids: tuple[str, ...] = ()
    #: Future invoices left alone because money was already recorded on them.
    retained_invoice_ids: tuple[str, ...] = ()
    autopay_status: str
    autopay_applied: bool
    ladders_suppressed: int = 0

    @property
    def billing_result(self) -> str:
        """Short audit label for the enrollment lifecycle event."""
        if self.transition == "resumed":
            return "autopay_resumed" if self.autopay_applied else "autopay_resume_rejected"
        parts = [f"voided={len(self.voided_invoice_ids)}"]
        if self.retained_invoice_ids:
            parts.append(f"retained={len(self.retained_invoice_ids)}")
        parts.append(f"autopay={self.autopay_status if self.autopay_applied else 'unchanged'}")
        return ",".join(parts)


def period_of(moment: datetime, timezone_name: str | None) -> str:
    """Billing period (``YYYY-MM``) that ``moment`` falls in for the academy."""
    aware = moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)
    if timezone_name:
        try:
            aware = aware.astimezone(ZoneInfo(timezone_name))
        except (KeyError, ValueError):
            log.warning("apply_enrollment_lifecycle_bad_timezone", extra={"tz": timezone_name})
    return aware.strftime("%Y-%m")


class ApplyEnrollmentLifecycle:
    def __init__(
        self,
        *,
        ledger: LifecycleInvoiceLedger,
        autopay: LifecycleAutopayGateway | None = None,
        dunning: LifecycleDunningSuppressor | None = None,
        academy_timezone: AcademyTimezoneReader | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._ledger = ledger
        self._autopay = autopay
        self._dunning = dunning
        self._academy_timezone = academy_timezone
        self._now = clock

    async def execute(self, cmd: ApplyEnrollmentLifecycleCommand) -> ApplyEnrollmentLifecycleResult:
        now = self._now()
        timezone_name = await self._academy_timezone() if self._academy_timezone else None
        effective_period = period_of(cmd.effective_at, timezone_name)

        voided: list[str] = []
        retained: list[str] = []
        suppressed = 0
        if cmd.transition in STOPPING_TRANSITIONS:
            reason = cmd.reason or f"enrollment_{cmd.transition}"
            for invoice in await self._ledger.list_invoices_for_enrollment(cmd.enrollment_id):
                if invoice.period <= effective_period:
                    continue  # current and past periods stay payable (policy)
                if invoice.status not in _VOIDABLE_STATUSES:
                    if invoice.status == "partially_paid":
                        retained.append(invoice.invoice_id)
                    continue
                if invoice.balance_due_cents != invoice.total_cents:
                    retained.append(invoice.invoice_id)
                    continue
                await self._ledger.save_invoice(void_invoice(invoice, reason=reason, now=now))
                voided.append(invoice.invoice_id)
                if self._dunning is not None and await self._dunning.suppress_for_invoice(
                    invoice_id=invoice.invoice_id, reason="invoice_voided", now=now
                ):
                    suppressed += 1

        autopay_status = AUTOPAY_STATUS_FOR_TRANSITION[cmd.transition]
        applied = False
        if self._autopay is not None:
            try:
                applied = await self._autopay.set_autopay_enrollment_status(
                    enrollment_id=cmd.enrollment_id, status=autopay_status
                )
            except Exception:
                log.exception(
                    "apply_enrollment_lifecycle_autopay_failed",
                    extra={"enrollment_id": cmd.enrollment_id, "status": autopay_status},
                )
            if not applied:
                log.info(
                    "apply_enrollment_lifecycle_autopay_unchanged",
                    extra={"enrollment_id": cmd.enrollment_id, "status": autopay_status},
                )

        result = ApplyEnrollmentLifecycleResult(
            transition=cmd.transition,
            effective_period=effective_period,
            voided_invoice_ids=tuple(voided),
            retained_invoice_ids=tuple(retained),
            autopay_status=autopay_status,
            autopay_applied=applied,
            ladders_suppressed=suppressed,
        )
        log.info(
            "apply_enrollment_lifecycle",
            extra={
                "enrollment_id": cmd.enrollment_id,
                "transition": cmd.transition,
                "effective_period": effective_period,
                "voided": len(voided),
                "retained": len(retained),
                "autopay_applied": applied,
            },
        )
        return result
