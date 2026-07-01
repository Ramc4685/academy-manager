"""Worker use case for the app-owned autopay dunning ladder."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import BaseModel

from backend.v2.contexts.billing.domain.dunning import DunningState
from backend.v2.contexts.billing.domain.ledger import LedgerInvoice

log = logging.getLogger(__name__)


class DunningStateRepository(Protocol):
    async def prepare_due_states(self, *, now: datetime, limit: int) -> int: ...

    async def claim_next_due(
        self, *, now: datetime, worker_id: str
    ) -> tuple[LedgerInvoice, DunningState] | None: ...

    async def finish_attempt(
        self,
        *,
        state: DunningState,
        succeeded: bool,
        failure_code: str | None,
        now: datetime,
    ) -> DunningState: ...

    async def release_attempt(
        self,
        *,
        state: DunningState,
        next_attempt_at: datetime | None,
        now: datetime,
    ) -> DunningState: ...

    async def park_attempt(
        self,
        *,
        state: DunningState,
        reason: str,
        now: datetime,
    ) -> DunningState: ...

    async def mark_notification_sent(
        self, *, invoice_id: str, attempt_no: int, sent_at: datetime
    ) -> DunningState: ...

    async def list_terminal_disable_pending(self, *, limit: int) -> list[DunningState]: ...

    async def mark_autopay_disable_result(
        self,
        *,
        invoice_id: str,
        succeeded: bool,
        error: str | None,
        now: datetime,
    ) -> DunningState: ...


class ChargeInvoicePort(Protocol):
    async def execute(self, invoice_id: str, *, retry_scope: str | None = None) -> Any: ...


class DunningNotificationPort(Protocol):
    async def send_dunning_notice(
        self,
        *,
        parent_id: str,
        invoice_id: str,
        period: str,
        balance_due_cents: int,
        currency: str,
        attempt_no: int,
        terminal: bool,
    ) -> None: ...


class DunningEnrollmentAutopayPort(Protocol):
    async def set_autopay_enrollment_status(self, *, enrollment_id: str, status: str) -> bool: ...


class ProcessDunningRetriesResult(BaseModel):
    model_config = {"frozen": True}

    prepared: int = 0
    processed: int = 0
    succeeded: int = 0
    failed: int = 0
    dunned: int = 0
    transient: int = 0
    parked: int = 0
    technical_failures: int = 0
    notifications_sent: int = 0
    notifications_failed: int = 0
    autopay_disabled: int = 0
    autopay_disable_failed: int = 0


class ProcessDunningRetries:
    def __init__(
        self,
        *,
        dunning: DunningStateRepository,
        charge_invoice: ChargeInvoicePort,
        notifier: DunningNotificationPort | None = None,
        enrollment_autopay: DunningEnrollmentAutopayPort | None = None,
        clock=lambda: datetime.now(UTC),
    ) -> None:
        self._dunning = dunning
        self._charge_invoice = charge_invoice
        self._notifier = notifier
        self._enrollment_autopay = enrollment_autopay
        self._now = clock

    async def execute(
        self,
        *,
        limit: int = 100,
        worker_id: str = "dunning-worker",
    ) -> ProcessDunningRetriesResult:
        now = self._now()
        prepared = await self._dunning.prepare_due_states(now=now, limit=limit)
        counts = {
            "prepared": prepared,
            "processed": 0,
            "succeeded": 0,
            "failed": 0,
            "dunned": 0,
            "transient": 0,
            "parked": 0,
            "technical_failures": 0,
            "notifications_sent": 0,
            "notifications_failed": 0,
            "autopay_disabled": 0,
            "autopay_disable_failed": 0,
        }
        await self._process_pending_autopay_disables(limit=limit, counts=counts, now=now)

        for _ in range(limit):
            claimed = await self._dunning.claim_next_due(now=now, worker_id=worker_id)
            if claimed is None:
                break
            invoice, state = claimed
            counts["processed"] += 1

            try:
                raw_result = await self._charge_invoice.execute(
                    invoice.invoice_id,
                    retry_scope=f"dunning-attempt:{state.processing_attempt_no}",
                )
            except Exception as exc:
                log.warning(
                    "dunning charge technical failure invoice=%s attempt=%s err=%s",
                    invoice.invoice_id,
                    state.processing_attempt_no,
                    exc,
                )
                await self._dunning.park_attempt(
                    state=state,
                    reason="charge_technical_failure",
                    now=now,
                )
                counts["technical_failures"] += 1
                counts["parked"] += 1
                continue

            result = _result_dict(raw_result)
            succeeded = bool(result.get("success"))
            failure_code = _failure_code(result)
            if not succeeded and (bool(result.get("processing")) or failure_code is None):
                await self._dunning.park_attempt(
                    state=state,
                    reason="payment_processing"
                    if bool(result.get("processing"))
                    else "attempt_indeterminate",
                    now=now,
                )
                counts["parked"] += 1
                if not bool(result.get("processing")):
                    counts["transient"] += 1
                continue
            if failure_code == "autopay_not_active":
                await self._dunning.park_attempt(
                    state=state,
                    reason="autopay_not_active",
                    now=now,
                )
                counts["parked"] += 1
                continue

            updated = await self._dunning.finish_attempt(
                state=state,
                succeeded=succeeded,
                failure_code=failure_code,
                now=now,
            )
            if succeeded:
                counts["succeeded"] += 1
                continue

            counts["failed"] += 1
            if updated.status == "dunned":
                counts["dunned"] += 1
                await self._disable_autopay(updated, counts=counts, now=now)

            if await self._notify_parent(invoice=invoice, state=updated):
                counts["notifications_sent"] += 1
            else:
                counts["notifications_failed"] += 1

        return ProcessDunningRetriesResult(**counts)

    async def _process_pending_autopay_disables(
        self,
        *,
        limit: int,
        counts: dict[str, int],
        now: datetime,
    ) -> None:
        for state in await self._dunning.list_terminal_disable_pending(limit=limit):
            await self._disable_autopay(state, counts=counts, now=now)

    async def _notify_parent(self, *, invoice: LedgerInvoice, state: DunningState) -> bool:
        attempt_no = state.attempt_count
        if self._notifier is None or attempt_no in state.notification_attempts:
            return False
        try:
            await self._notifier.send_dunning_notice(
                parent_id=invoice.parent_id,
                invoice_id=invoice.invoice_id,
                period=invoice.period,
                balance_due_cents=invoice.balance_due_cents,
                currency=invoice.currency,
                attempt_no=attempt_no,
                terminal=state.status == "dunned",
            )
            await self._dunning.mark_notification_sent(
                invoice_id=invoice.invoice_id,
                attempt_no=attempt_no,
                sent_at=self._now(),
            )
            return True
        except Exception as exc:
            log.warning(
                "dunning notification failed invoice=%s attempt=%s err=%s",
                invoice.invoice_id,
                attempt_no,
                exc,
            )
            return False

    async def _disable_autopay(
        self,
        state: DunningState,
        *,
        counts: dict[str, int],
        now: datetime,
    ) -> None:
        if self._enrollment_autopay is None or not state.enrollment_id:
            await self._dunning.mark_autopay_disable_result(
                invoice_id=state.invoice_id,
                succeeded=True,
                error=None,
                now=now,
            )
            return
        try:
            disabled = await self._enrollment_autopay.set_autopay_enrollment_status(
                enrollment_id=state.enrollment_id,
                status="disabled",
            )
        except Exception as exc:
            await self._dunning.mark_autopay_disable_result(
                invoice_id=state.invoice_id,
                succeeded=False,
                error=str(exc),
                now=now,
            )
            counts["autopay_disable_failed"] += 1
            return
        if disabled:
            await self._dunning.mark_autopay_disable_result(
                invoice_id=state.invoice_id,
                succeeded=True,
                error=None,
                now=now,
            )
            counts["autopay_disabled"] += 1
        else:
            await self._dunning.mark_autopay_disable_result(
                invoice_id=state.invoice_id,
                succeeded=False,
                error="transition rejected",
                now=now,
            )
            counts["autopay_disable_failed"] += 1


def _result_dict(raw_result: Any) -> dict[str, Any]:
    if isinstance(raw_result, dict):
        return raw_result
    if hasattr(raw_result, "model_dump"):
        return raw_result.model_dump(mode="python")
    return dict(raw_result)


def _failure_code(result: dict[str, Any]) -> str | None:
    decline_code = result.get("decline_code")
    if decline_code:
        return str(decline_code)
    if result.get("requires_action"):
        return "requires_action"
    return None
