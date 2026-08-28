"""Email the invoices a monthly generation run just created (issue #430).

The monthly generation job creates ledger invoices but sends nothing: until
this use case, ``SendInvoice`` was reachable only from an admin clicking
"Send" on one invoice at a time, so every non-autopay parent was billed into
the void unless someone remembered to click.

Design notes:

* **Idempotency lives in the query, not the sender.** ``SendInvoice`` is not
  idempotent — calling it twice re-mints a checkout and re-emails. The pass
  therefore only considers invoices whose ``delivery_status`` is not yet
  ``sent``, so a re-run (daily tick, catch-up run, lease handover) does not
  re-email anyone who already received their invoice.
* **Failures retry on the next tick for free.** A send that fails leaves the
  invoice at ``delivery_failed``, which the same query still selects
  tomorrow.
* **Autopay enrollments are skipped.** Their invoice gets charged by the
  dunning/autopay worker; emailing "here is your bill, pay here" alongside an
  automatic charge invites a double payment. Eligibility mirrors the charge
  path exactly (``autopay_enrollment_status == "active"``).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Protocol

from pydantic import BaseModel

from backend.v2.contexts.billing.domain.ledger import LedgerInvoice

log = logging.getLogger(__name__)

#: Mirrors ``_AUTOPAY_ELIGIBLE_STATUS`` in ``charge_invoice_via_autopay``:
#: paused / disabled / offered / setup_started enrollments are NOT auto-charged
#: and so must still receive an emailed invoice.
_AUTOPAY_ACTIVE_STATUS = "active"

#: Ceiling on one pass, so a misconfigured period can never turn into an
#: unbounded email run. Anything above this is left for the next daily tick,
#: and logged.
DEFAULT_SEND_LIMIT = 500


class UndeliveredInvoiceReader(Protocol):
    """The slice of ``LedgerRepository`` this use case needs."""

    async def list_undelivered_invoices_for_period(
        self, period: str, *, limit: int = 100
    ) -> list[LedgerInvoice]: ...


class AutopayStatusReader(Protocol):
    """The slice of ``EnrollmentAutopayGateway`` this use case needs."""

    async def get_autopay_enrollment_status(self, *, enrollment_id: str) -> str | None: ...


class SendGeneratedInvoicesResult(BaseModel):
    model_config = {"frozen": True}

    considered: int = 0
    emailed: int = 0
    email_failed: int = 0
    skipped_autopay: int = 0
    #: True when the pass hit ``limit`` and left invoices for the next tick.
    truncated: bool = False


class SendGeneratedInvoices:
    def __init__(
        self,
        *,
        ledger: UndeliveredInvoiceReader,
        autopay: AutopayStatusReader | None = None,
        send: Callable[[str], Awaitable[object]],
    ) -> None:
        self._ledger = ledger
        self._autopay = autopay
        self._send = send

    async def execute(
        self, period: str, *, limit: int = DEFAULT_SEND_LIMIT
    ) -> SendGeneratedInvoicesResult:
        invoices = await self._ledger.list_undelivered_invoices_for_period(period, limit=limit)

        emailed = 0
        email_failed = 0
        skipped_autopay = 0

        for invoice in invoices:
            if await self._is_autopaying(invoice):
                skipped_autopay += 1
                continue
            try:
                await self._send(invoice.invoice_id)
            except Exception:
                # One bad invoice must not stop the rest of the academy's
                # billing run. The invoice keeps its current delivery_status,
                # so the next daily tick re-selects and retries it.
                email_failed += 1
                log.exception(
                    "generated_invoice_email_failed",
                    extra={"invoice_id": invoice.invoice_id, "period": period},
                )
                continue
            emailed += 1

        truncated = len(invoices) >= limit
        if truncated:
            log.warning(
                "generated_invoice_email_truncated",
                extra={"period": period, "limit": limit},
            )

        return SendGeneratedInvoicesResult(
            considered=len(invoices),
            emailed=emailed,
            email_failed=email_failed,
            skipped_autopay=skipped_autopay,
            truncated=truncated,
        )

    async def _is_autopaying(self, invoice: LedgerInvoice) -> bool:
        """True when this invoice will be collected by the autopay worker.

        An invoice with no ``enrollment_id`` can never be auto-charged (the
        charge path fails closed on exactly that condition), so it is emailed.
        A status lookup that raises is treated as "not autopaying": a parent
        receiving an invoice they were also charged for is recoverable; a
        parent silently receiving nothing is the bug this fixes.
        """
        if self._autopay is None or not invoice.enrollment_id:
            return False
        try:
            status = await self._autopay.get_autopay_enrollment_status(
                enrollment_id=invoice.enrollment_id
            )
        except Exception:
            log.exception(
                "generated_invoice_autopay_lookup_failed",
                extra={"invoice_id": invoice.invoice_id},
            )
            return False
        return status == _AUTOPAY_ACTIVE_STATUS
