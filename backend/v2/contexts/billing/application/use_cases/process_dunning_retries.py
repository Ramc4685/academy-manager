"""Worker use case for the app-owned autopay dunning ladder."""

from __future__ import annotations

import logging
from collections.abc import Collection, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import BaseModel
from pymongo.errors import DuplicateKeyError

from backend.v2.contexts.billing.application.autopay_eligibility import invoice_is_chargeable
from backend.v2.contexts.billing.application.ports import FamilyAutopayPauser
from backend.v2.contexts.billing.domain.checkout_hold import CHECKOUT_HOLD_DECLINE_CODE
from backend.v2.contexts.billing.domain.dunning import (
    NO_SAVED_PAYMENT_METHOD,
    PARK_REASONS_NEEDING_ATTENTION,
    STRIPE_UNAVAILABLE,
    TECHNICAL_FAILURE_CAPPED,
    TECHNICAL_PARK_CAP,
    DunningState,
)
from backend.v2.contexts.billing.domain.events import (
    DunningNoticeRequested,
    DunningNoticeRequestedPayload,
)
from backend.v2.contexts.billing.domain.ledger import LedgerInvoice
from backend.v2.shared.events.outbox import Outbox
from backend.v2.shared.ids import new_ulid

log = logging.getLogger(__name__)

# Charge outcomes that are NOT the parent's card saying no. None of these means "this
# family cannot pay"; every one of them means "we could not ask". Parking re-tries the
# same rung on a later tick, so the ladder never advances and autopay is never disabled
# on the strength of a problem that lives on our side of the wire (issue #434).
_PARK_REASONS = frozenset(
    {
        # Enrollment is not actively autopaying — nothing to charge against.
        "autopay_not_active",
        # A parent is paying this invoice manually right now; charging would double-bill.
        CHECKOUT_HOLD_DECLINE_CODE,
        # The academy's Stripe connected account is not charge-ready.
        "connected_account_not_ready",
        # No Stripe gateway wired at all. The card was never touched, so treating this
        # as a decline would spend a rung — and eventually a family's autopay — on our
        # own misconfiguration.
        "stripe_not_configured",
        # Stripe API or network error: we never reached the card or bank, so no
        # rung is spent and the parent is not told their payment failed (A4-3).
        STRIPE_UNAVAILABLE,
        # No saved card or bank: the parent has to act. Parked so it is charged as
        # soon as a method appears, with one "add a payment method" notice (A4-1).
        NO_SAVED_PAYMENT_METHOD,
    }
)

#: notification_attempts marker for the one-time "add a payment method" notice; real
#: rungs are numbered from 1.
_NO_METHOD_NOTICE_MARKER = 0


class DunningStateRepository(Protocol):
    async def prepare_due_states(self, *, now: datetime, limit: int) -> int: ...

    async def claim_next_due(
        self,
        *,
        now: datetime,
        worker_id: str,
        exclude_invoice_ids: Collection[str] = (),
        charge_group_id: str | None = None,
    ) -> tuple[LedgerInvoice, DunningState] | None: ...

    async def claim_group_siblings(
        self,
        *,
        lead: DunningState,
        now: datetime,
        worker_id: str,
        rejoin: bool,
        period: str,
        exclude_invoice_ids: Collection[str] = (),
    ) -> list[tuple[LedgerInvoice, DunningState]]: ...

    async def count_group_members(self, charge_group_id: str) -> int: ...

    async def list_group_invoices(self, charge_group_id: str) -> list[LedgerInvoice]: ...

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
    async def execute(
        self, invoice_id: str, *, retry_scope: str | None = None, check_existing: bool = False
    ) -> Any: ...

    async def execute_family(
        self,
        invoice_ids: Sequence[str],
        *,
        charge_group_id: str,
        retry_scopes: Mapping[str, str | None],
        check_existing: bool = False,
    ) -> Any: ...


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
        failure_code: str | None = None,
        next_attempt_at: datetime | None = None,
        bank_debit: bool = False,
        invoice_ids: Sequence[str] = (),
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
        outbox: Outbox | None = None,
        family_autopay: FamilyAutopayPauser | None = None,
        clock=lambda: datetime.now(UTC),
    ) -> None:
        self._dunning = dunning
        self._charge_invoice = charge_invoice
        self._notifier = notifier
        self._enrollment_autopay = enrollment_autopay
        self._outbox = outbox
        self._family_autopay = family_autopay
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

        # Parking leaves next_attempt_at=None, and claim_next_due sorts on that column
        # ascending — BSON puts Null before Date, so a state parked this tick would be
        # handed straight back ahead of every genuinely-due invoice. Exclude it from
        # the rest of the tick instead: a counter-based "stop on repeats" guard ended
        # the tick after ONE parked invoice and starved all due charges behind it
        # (2026-11-08: three BLNO autopay charges never ran for six days).
        parked_this_tick: dict[str, str] = {}

        for _ in range(limit):
            group_id = new_ulid()
            claimed = await self._dunning.claim_next_due(
                now=now,
                worker_id=worker_id,
                exclude_invoice_ids=parked_this_tick.keys(),
                charge_group_id=group_id,
            )
            if claimed is None:
                break
            invoice, state = claimed

            counts["processed"] += 1

            if state.settling_failure_code is not None:
                await self._settle_failed_debit(invoice, state, counts=counts, now=now)
                continue

            members = [(invoice, state)]
            rejoin = False
            if state.charge_group_id is not None:
                # L8: the family's other rungs for this month due now join one
                # charge. A retry of a group that may already have charged (stale
                # lease or technical park) takes back exactly its old members.
                rejoin = state.charge_group_id != group_id
                siblings = await self._dunning.claim_group_siblings(
                    lead=state,
                    now=now,
                    worker_id=worker_id,
                    rejoin=rejoin,
                    period=invoice.period,
                    exclude_invoice_ids=parked_this_tick.keys(),
                )
                counts["processed"] += len(siblings)
                for sibling_invoice, sibling in siblings:
                    if sibling.settling_failure_code is not None:
                        await self._settle_failed_debit(
                            sibling_invoice, sibling, counts=counts, now=now
                        )
                    else:
                        members.append((sibling_invoice, sibling))
                if rejoin and len(members) < await self._dunning.count_group_members(
                    state.charge_group_id
                ):
                    # Part of that charge already moved on, so it may have gone
                    # through. Charging the rest would be a different charge:
                    # park them until the webhook, reconcile or the L3 cap decides.
                    await self._park_unresolved_group(members, counts, parked_this_tick, now)
                    continue

            # A group of one was charged alone, so it retries alone too.
            if len(members) > 1:
                await self._charge_family(
                    members,
                    rejoin=rejoin,
                    counts=counts,
                    parked_this_tick=parked_this_tick,
                    now=now,
                )
            else:
                await self._charge_one(
                    invoice, state, counts=counts, parked_this_tick=parked_this_tick, now=now
                )

        return ProcessDunningRetriesResult(**counts)

    async def _settle_failed_debit(
        self, invoice: LedgerInvoice, state: DunningState, *, counts: dict[str, int], now: datetime
    ) -> None:
        # The bank debit this rung waited on came back failed. Record that
        # answer; debiting again now would bounce the same way (A4-2).
        updated = await self._dunning.finish_attempt(
            state=state,
            succeeded=False,
            failure_code=state.settling_failure_code,
            now=now,
        )
        await self._after_failed_attempts(
            [(invoice, updated)], counts=counts, now=now, settled=True
        )

    async def _charge_one(
        self,
        invoice: LedgerInvoice,
        state: DunningState,
        *,
        counts: dict[str, int],
        parked_this_tick: dict[str, str],
        now: datetime,
    ) -> None:
        # Charged alone, so not part of any family charge's notice (L8).
        state = state.model_copy(update={"charge_group_id": None})
        try:
            raw_result = await self._charge_invoice.execute(
                invoice.invoice_id,
                retry_scope=f"dunning-attempt:{state.processing_attempt_no}",
                check_existing=_key_may_be_forgotten(state, now),
            )
        except Exception as exc:
            log.warning(
                "dunning charge technical failure invoice=%s attempt=%s err=%s",
                invoice.invoice_id,
                state.processing_attempt_no,
                exc,
            )
            await self._park_technical_failure([(invoice, state)], counts, parked_this_tick, now)
            return
        await self._apply_result(
            [(invoice, state)],
            raw_result,
            counts=counts,
            parked_this_tick=parked_this_tick,
            now=now,
        )

    async def _charge_family(
        self,
        members: list[tuple[LedgerInvoice, DunningState]],
        *,
        rejoin: bool,
        counts: dict[str, int],
        parked_this_tick: dict[str, str],
        now: datetime,
    ) -> None:
        """One charge for one family's rungs due now; one result for all of them.

        Any dropped member means no family charge. A fresh group then charges
        each member alone; a ``rejoin`` parks them all, since the earlier charge
        may have gone through and charging any member again would double it.
        """
        group_id = members[0][1].charge_group_id
        assert group_id is not None
        try:
            family = _result_dict(
                await self._charge_invoice.execute_family(
                    [invoice.invoice_id for invoice, _ in members],
                    charge_group_id=group_id,
                    retry_scopes={
                        invoice.invoice_id: f"dunning-attempt:{state.processing_attempt_no}"
                        for invoice, state in members
                    },
                    check_existing=any(_key_may_be_forgotten(s, now) for _, s in members),
                )
            )
        except Exception as exc:
            log.warning("dunning family charge technical failure group=%s err=%s", group_id, exc)
            await self._park_technical_failure(members, counts, parked_this_tick, now)
            return
        by_id = {invoice.invoice_id: (invoice, state) for invoice, state in members}
        if rejoin and family.get("dropped_invoice_ids"):
            await self._park_unresolved_group(members, counts, parked_this_tick, now)
            return
        for invoice_id in family.get("dropped_invoice_ids") or ():
            # Paid, voided, held or no longer autopaying: the single path decides.
            await self._charge_one(
                *by_id[invoice_id], counts=counts, parked_this_tick=parked_this_tick, now=now
            )
        charged = [by_id[invoice_id] for invoice_id in family.get("charged_invoice_ids") or ()]
        if charged:
            await self._apply_result(
                charged,
                family["result"],
                counts=counts,
                parked_this_tick=parked_this_tick,
                now=now,
            )

    async def _park_unresolved_group(
        self,
        members: list[tuple[LedgerInvoice, DunningState]],
        counts: dict[str, int],
        parked_this_tick: dict[str, str],
        now: datetime,
    ) -> None:
        for _invoice, member in members:
            await self._park(state=member, reason="attempt_indeterminate", now=now)
            parked_this_tick[member.invoice_id] = "attempt_indeterminate"
            counts["parked"] += 1
            counts["transient"] += 1

    async def _park_technical_failure(
        self,
        members: list[tuple[LedgerInvoice, DunningState]],
        counts: dict[str, int],
        parked_this_tick: dict[str, str],
        now: datetime,
    ) -> None:
        for _invoice, state in members:
            await self._park(state=state, reason="charge_technical_failure", now=now)
            parked_this_tick[state.invoice_id] = "charge_technical_failure"
            counts["technical_failures"] += 1
            counts["parked"] += 1

    async def _apply_result(
        self,
        members: list[tuple[LedgerInvoice, DunningState]],
        raw_result: Any,
        *,
        counts: dict[str, int],
        parked_this_tick: dict[str, str],
        now: datetime,
    ) -> None:
        """One charge result, applied to every member it covered."""
        result = _result_dict(raw_result)
        succeeded = bool(result.get("success"))
        failure_code = _failure_code(result)
        if not succeeded and (bool(result.get("processing")) or failure_code is None):
            reason = (
                "payment_processing" if bool(result.get("processing")) else "attempt_indeterminate"
            )
            for _invoice, state in members:
                await self._park(state=state, reason=reason, now=now)
                parked_this_tick[state.invoice_id] = reason
                counts["parked"] += 1
                if not bool(result.get("processing")):
                    counts["transient"] += 1
            return
        if failure_code in _PARK_REASONS:
            for _invoice, state in members:
                await self._park(state=state, reason=failure_code, now=now)
                parked_this_tick[state.invoice_id] = failure_code
                # An operator has to fix these: billing-health counts them.
                if failure_code in PARK_REASONS_NEEDING_ATTENTION:
                    counts["technical_failures"] += 1
                counts["parked"] += 1
            if failure_code == NO_SAVED_PAYMENT_METHOD and await self._notify_parent(
                members,
                failure_code=NO_SAVED_PAYMENT_METHOD,
                marker=_NO_METHOD_NOTICE_MARKER,
            ):
                counts["notifications_sent"] += 1
            return

        finished = [
            (
                invoice,
                await self._dunning.finish_attempt(
                    state=state,
                    succeeded=succeeded,
                    failure_code=failure_code,
                    now=now,
                ),
            )
            for invoice, state in members
        ]
        if succeeded:
            # The receipt comes from the payment_intent.succeeded webhook, once
            # per payment and for every method (L1 A5-2).
            counts["succeeded"] += len(finished)
            return
        await self._after_failed_attempts(finished, counts=counts, now=now)

    async def _park(self, *, state: DunningState, reason: str, now: datetime) -> None:
        parked = await self._dunning.park_attempt(state=state, reason=reason, now=now)
        if parked.suppression_reason == TECHNICAL_FAILURE_CAPPED:
            # Rechecked once a day from now on; shows in Failed autopay and as autopay stuck (A7-6).
            log.error(
                "dunning_technical_failure_capped invoice=%s since=%s last_reason=%s",
                state.invoice_id,
                parked.technical_parked_since,
                reason,
                extra={"invoice_id": state.invoice_id, "academy_id": state.academy_id},
            )

    async def _after_failed_attempts(
        self,
        members: list[tuple[LedgerInvoice, DunningState]],
        *,
        counts: dict[str, int],
        now: datetime,
        settled: bool = False,
    ) -> None:
        counts["failed"] += len(members)
        for _invoice, updated in members:
            if updated.status == "dunned":
                counts["dunned"] += 1
                await self._disable_autopay(updated, counts=counts, now=now)

        cover: list[LedgerInvoice] | None = None
        group_id = members[0][1].charge_group_id
        if settled and group_id is not None:
            # A family debit's members settle one claim at a time; each finds the
            # whole family here, and the shared event id sends the notice once.
            cover = await self._dunning.list_group_invoices(group_id)
        if await self._notify_parent(
            members, failure_code=members[0][1].last_failure_code, cover=cover
        ):
            counts["notifications_sent"] += 1
        else:
            counts["notifications_failed"] += 1

    async def _process_pending_autopay_disables(
        self,
        *,
        limit: int,
        counts: dict[str, int],
        now: datetime,
    ) -> None:
        for state in await self._dunning.list_terminal_disable_pending(limit=limit):
            await self._disable_autopay(state, counts=counts, now=now)

    async def _notify_parent(
        self,
        members: list[tuple[LedgerInvoice, DunningState]],
        *,
        failure_code: str | None,
        marker: int | None = None,
        cover: list[LedgerInvoice] | None = None,
    ) -> bool:
        """Tell the parent this attempt failed, once for every member it covered.
        Returns True once the notice is *durably owed* — enqueued or sent — not
        necessarily delivered.

        Issue #435: with an outbox wired, the notice becomes an event and the
        dispatcher's retry ladder owns delivery, so a Resend blip no longer
        means the parent is never told their payment failed. Without one (no
        e-mail configured, or older wiring) the direct best-effort send is kept
        so behaviour is unchanged where nothing can deliver anyway.

        ``mark_notification_sent`` is recorded on enqueue, not on delivery: it
        is the guard that stops the *next* worker tick from queuing a second
        notice for the same attempt. Duplicate suppression on delivery is the
        dispatcher's job — it tracks ``(event_id, handler_name)``.

        A family charge (L8) sends ONE notice naming every invoice, with the
        balances summed; ``cover`` widens it to the whole family when only one
        member is in hand. Its event id is the charge group, so a second member
        settling the same debit later finds it already queued.
        """
        owed = [
            (invoice, state, state.attempt_count if marker is None else marker)
            for invoice, state in members
            if (state.attempt_count if marker is None else marker)
            not in state.notification_attempts
        ]
        if self._notifier is None or not owed:
            return False
        # A terminal notice says autopay is off for that invoice, so each gets its
        # own (per-invoice event id); the rest share one family notice.
        terminal = [row for row in owed if row[1].status == "dunned"]
        retrying = [row for row in owed if row[1].status != "dunned"]
        sent = True
        for row in terminal:
            sent = await self._send_notice([row], [row[0]], failure_code) and sent
        if retrying:
            named = [row[0] for row in retrying]
            if cover:
                named = [
                    row
                    for row in cover
                    if invoice_is_chargeable(row.status, row.balance_due_cents)
                    and row.invoice_id not in {t[0].invoice_id for t in terminal}
                ] or named
            sent = await self._send_notice(retrying, named, failure_code) and sent
        return sent

    async def _send_notice(
        self,
        owed: list[tuple[LedgerInvoice, DunningState, int]],
        named: list[LedgerInvoice],
        failure_code: str | None,
    ) -> bool:
        assert self._notifier is not None
        invoice, state, attempt_no = owed[0]
        family = len(named) > 1
        terminal = state.status == "dunned"
        payload = DunningNoticeRequestedPayload(
            invoice_id=invoice.invoice_id,
            parent_id=invoice.parent_id,
            period=invoice.period,
            balance_due_cents=sum(row.balance_due_cents for row in named),
            currency=invoice.currency,
            attempt_no=attempt_no,
            terminal=terminal,
            failure_code=failure_code,
            next_attempt_at=None if terminal else state.next_attempt_at,
            bank_debit=state.last_failure_was_bank_debit,
            invoice_ids=tuple(row.invoice_id for row in named) if family else (),
        )
        try:
            if self._outbox is not None:
                event = DunningNoticeRequested(
                    aggregate_id=invoice.invoice_id,
                    academy_id=invoice.academy_id,
                    payload=payload,
                )
                if family and state.charge_group_id:
                    event = event.model_copy(
                        update={"event_id": f"dunning-notice:group:{state.charge_group_id}"}
                    )
                try:
                    await self._outbox.append(event)
                except DuplicateKeyError:
                    pass  # another member of this family charge already queued it
            else:
                await self._notifier.send_dunning_notice(**payload.model_dump())
            for row_invoice, _state, row_attempt in owed:
                await self._dunning.mark_notification_sent(
                    invoice_id=row_invoice.invoice_id,
                    attempt_no=row_attempt,
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
            if state.last_failure_was_bank_debit and self._family_autopay is not None:
                # A bank that cannot be debited pauses the whole family, so a
                # sibling on the same account is not debited next (L1 B4).
                await self._family_autopay.pause_family(
                    academy_id=state.academy_id,
                    parent_id=state.parent_id,
                    reason=f"bank_failure:{state.last_failure_code or 'unknown'}",
                    request_id=f"dunning-terminal:{state.invoice_id}:{state.attempt_count}",
                )
                disabled = True
            else:
                # Bank failures pause so a re-linked bank turns autopay back on; a
                # card that ran out of retries is disabled (owner 2026-11-15).
                disabled = await self._enrollment_autopay.set_autopay_enrollment_status(
                    enrollment_id=state.enrollment_id,
                    status="paused" if state.last_failure_was_bank_debit else "disabled",
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


def _key_may_be_forgotten(state: DunningState, now: datetime) -> bool:
    """A rung parked for TECHNICAL_PARK_CAP or more is retried with an idempotency
    key Stripe may have forgotten (it keeps them 24h), so an earlier attempt that
    did charge would be charged again. ``parked_since``, not the technical clock:
    a later non-technical park (say, no saved card) clears that one, while
    ``parked_since`` survives every park and re-claim until the rung finishes."""
    since = state.parked_since
    return since is not None and now - since >= TECHNICAL_PARK_CAP
