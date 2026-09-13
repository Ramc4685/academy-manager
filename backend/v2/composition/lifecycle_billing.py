"""Wire enrollment lifecycle transitions into billing (issue #651).

Adapts the enrollment context's ``EnrollmentBillingSync`` port onto the
billing context's ``ApplyEnrollmentLifecycle`` use case. Built once per
composition root and injected into every enrollment use case that stops or
resumes attendance.

INVARIANT: every composition root that builds cancel / withdraw / pause /
resume / session-cancel / self-cancel use cases MUST pass the adapter from
``compose_enrollment_billing_sync``. Leaving it out silently re-opens the
"cancelled family keeps getting auto-charged" defect; the use cases log an
error when the port is missing, but nothing else stops the charge.

Issue #670: ``WithdrawEnrollment`` additionally needs the withdrawal decision
adapter from ``compose_withdrawal_decision`` — the billing-side half of a
withdrawal (early-withdrawal credit ledger entry, legacy subscription cancel).
Without it a credit outcome issues no credit and the event says so.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime
from typing import Any

from backend.v2.contexts.billing.application.use_cases.apply_enrollment_lifecycle import (
    ApplyEnrollmentLifecycle,
    ApplyEnrollmentLifecycleCommand,
)
from backend.v2.contexts.billing.application.use_cases.apply_enrollment_move import (
    BILLING_POLICY as MOVE_BILLING_POLICY,
)
from backend.v2.contexts.billing.application.use_cases.apply_enrollment_move import (
    ApplyEnrollmentMove,
    ApplyEnrollmentMoveCommand,
    MoveNoticeResender,
)
from backend.v2.contexts.billing.application.use_cases.withdrawal_credit import (
    RecordWithdrawalDecision,
    RecordWithdrawalDecisionCommand,
)
from backend.v2.contexts.billing.domain.ledger import void_invoice
from backend.v2.contexts.billing.infrastructure.mongo_billing_counter_repo import (
    MongoBillingCounterRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_ledger_repo import (
    MongoBillingLedgerRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_settings_repo import (
    MongoBillingSettingsRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_credit_ledger_repo import (
    MongoCreditLedgerRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_dunning_state_repo import (
    MongoDunningStateRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_move_schedule_reader import (
    MongoMoveScheduleReader,
)
from backend.v2.contexts.billing.infrastructure.mongo_occurrence_cancellation import (
    MongoOccurrenceCancellationReader,
)
from backend.v2.contexts.billing.infrastructure.mongo_student_billing_enrollment_repo import (
    MongoStudentBillingEnrollmentRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_tuition_discount_repo import (
    MongoTuitionDiscountRepository,
)
from backend.v2.contexts.enrollment.application.ports import WithdrawalOutcome
from backend.v2.contexts.enrollment.domain.models import Enrollment
from backend.v2.shared.idempotency import IdempotencyStore
from backend.v2.shared.tenancy import current_academy_id
from backend.v2.shared.time.academy_timezone import academy_timezone_lookup

#: Issue #697: hold transitions map onto the existing pause/resume/withdraw/
#: cancel billing behavior — the billing context itself is not otherwise
#: touched. "held" behaves exactly like "paused" (void unpaid future-period
#: invoices, pause per-enrollment autopay, one BillingDeferral per held
#: month); "returned" like "resumed"; "dropped" (admin Drop or a system
#: reclaim/expiry) like "withdrawn"; "deleted" like "cancelled".
_HOLD_TRANSITION_MAP: dict[str, str] = {
    "held": "paused",
    "returned": "resumed",
    "dropped": "withdrawn",
    "deleted": "cancelled",
}


class EnrollmentBillingSyncAdapter:
    """``EnrollmentBillingSync`` implementation backed by the billing use case."""

    def __init__(self, use_case: ApplyEnrollmentLifecycle) -> None:
        self._use_case = use_case

    async def apply(
        self,
        *,
        enrollment_id: str,
        transition: str,
        effective_at: datetime,
        reason: str,
        actor_id: str | None,
    ) -> dict[str, Any]:
        result = await self._use_case.execute(
            ApplyEnrollmentLifecycleCommand(
                enrollment_id=enrollment_id,
                transition=_HOLD_TRANSITION_MAP.get(transition, transition),
                effective_at=effective_at,
                reason=reason[:500],
                actor_id=actor_id,
            )
        )
        return {
            "billing_policy": "current_period_payable_future_voided",
            "billing_result": result.billing_result,
            "voided_invoice_ids": list(result.voided_invoice_ids),
            "retained_invoice_ids": list(result.retained_invoice_ids),
            "autopay_status": result.autopay_status,
            "autopay_applied": result.autopay_applied,
            "ladders_suppressed": result.ladders_suppressed,
        }


def compose_enrollment_billing_sync(
    db: Any,
    *,
    ledger: MongoBillingLedgerRepository | None = None,
    autopay: MongoStudentBillingEnrollmentRepository | None = None,
    dunning: MongoDunningStateRepository | None = None,
) -> EnrollmentBillingSyncAdapter:
    """Build the adapter. Repos may be shared with the caller's own instances."""
    timezone_lookup = academy_timezone_lookup(db)

    async def request_academy_timezone() -> str | None:
        # Resolved at execution time from the request's tenant — never capture
        # an academy id at composition time (see AGENTS.md tenancy rule).
        return await timezone_lookup(current_academy_id())

    autopay_repo = autopay or MongoStudentBillingEnrollmentRepository(db)

    class _AutopayGateway:
        """Narrow the repo's Literal-typed writer to the use case's str port."""

        async def set_autopay_enrollment_status(self, *, enrollment_id: str, status: str) -> bool:
            return await autopay_repo.set_autopay_enrollment_status(
                enrollment_id=enrollment_id,
                status=status,  # type: ignore[arg-type]
            )

    use_case = ApplyEnrollmentLifecycle(
        ledger=ledger or MongoBillingLedgerRepository(db),
        autopay=_AutopayGateway(),
        dunning=dunning or MongoDunningStateRepository(db),
        academy_timezone=request_academy_timezone,
    )
    return EnrollmentBillingSyncAdapter(use_case)


class WithdrawalDecisionAdapter:
    """``EnrollmentWithdrawalDecisionPort`` over billing's
    ``RecordWithdrawalDecision`` (issue #670)."""

    def __init__(self, use_case: RecordWithdrawalDecision) -> None:
        self._use_case = use_case

    async def record_withdrawal_decision(
        self,
        *,
        enrollment: Enrollment,
        outcome: WithdrawalOutcome,
        effective_at: datetime,
        actor_id: str,
        reason: str,
    ) -> dict[str, Any]:
        result = await self._use_case.execute(
            RecordWithdrawalDecisionCommand(
                enrollment_id=enrollment.enrollment_id,
                academy_id=enrollment.academy_id,
                student_id=enrollment.student_id,
                outcome=outcome,
                withdrawal_date=effective_at,
                actor_id=actor_id,
                reason=reason[:500],
            )
        )
        return {
            "billing_policy": result.billing_policy,
            "billing_result": result.billing_result,
            "credit_id": result.credit_id,
            "metadata": dict(result.metadata),
        }


def compose_withdrawal_decision(
    *, payments: Any, credits: Any, subscriptions: Any, stripe: Any
) -> WithdrawalDecisionAdapter:
    """Build the withdrawal decision adapter over the caller's billing repos."""
    return WithdrawalDecisionAdapter(
        RecordWithdrawalDecision(
            payments=payments,
            credits=credits,
            subscriptions=subscriptions,
            stripe=stripe,
        )
    )


class EnrollmentMoveBillingSyncAdapter:
    """``EnrollmentMoveBillingSync`` implementation backed by ``ApplyEnrollmentMove``."""

    def __init__(self, use_case: ApplyEnrollmentMove) -> None:
        self._use_case = use_case

    async def apply_move(
        self,
        *,
        enrollment_id: str,
        from_session_id: str,
        to_session_id: str,
        effective_at: datetime,
        reason: str,
        actor_id: str | None,
        effective_date: date | None = None,
        move_seq: int = 0,
    ) -> dict[str, Any]:
        result = await self._use_case.execute(
            ApplyEnrollmentMoveCommand(
                enrollment_id=enrollment_id,
                from_session_id=from_session_id,
                to_session_id=to_session_id,
                effective_at=effective_at,
                effective_date=effective_date,
                move_seq=move_seq,
                reason=reason[:500],
                actor_id=actor_id,
            )
        )
        return {
            "billing_policy": MOVE_BILLING_POLICY,
            "billing_result": result.billing_result,
            "metadata": result.metadata,
        }


def compose_enrollment_move_billing_sync(
    db: Any,
    *,
    idempotency: IdempotencyStore,
    ledger: MongoBillingLedgerRepository | None = None,
    credits: MongoCreditLedgerRepository | None = None,
    notice_resender: MoveNoticeResender | None = None,
) -> EnrollmentMoveBillingSyncAdapter:
    """Build the move adapter (issue #669). Repos may be shared with the caller."""
    timezone_lookup = academy_timezone_lookup(db)

    async def request_academy_timezone() -> str | None:
        # Resolved per request from the tenant context, never captured here.
        return await timezone_lookup(current_academy_id())

    use_case = ApplyEnrollmentMove(
        ledger=ledger or MongoBillingLedgerRepository(db),
        credits=credits or MongoCreditLedgerRepository(db),
        schedules=MongoMoveScheduleReader(db),
        # Credit the from-session against what the period's charge actually
        # bought, consumed-first, the way withdrawal and cancellation credits
        # do (issue #729). Same reader the cancellation use case uses.
        charge_basis=MongoOccurrenceCancellationReader(db),
        # Price the delta net of the same recurring tuition discount the
        # monthly generator priced the invoice with (issue #669 review).
        discounts=MongoTuitionDiscountRepository(db),
        idempotency_store=idempotency,
        academy_timezone=request_academy_timezone,
        # A move that grows an already-noticed autopay invoice re-notices the
        # family with the corrected amount (issue #691).
        notice_resender=notice_resender,
        counters=MongoBillingCounterRepository(db),
        settings=MongoBillingSettingsRepository(db),
    )
    return EnrollmentMoveBillingSyncAdapter(use_case)


def build_void_billing_invoice(*, ledger: Any, dunning: Any) -> Callable[..., Awaitable[None]]:
    """Admin void: refuse invoices with money on them, persist the reason and
    stop the dunning ladder (issue #651)."""

    async def void_billing_invoice(*, invoice_id: str, reason: str) -> None:
        invoice = await ledger.get_invoice(invoice_id)
        if invoice is None:
            raise ValueError("invoice not found")
        if (
            invoice.status in {"partially_paid", "paid"}
            or invoice.balance_due_cents != invoice.total_cents
        ):
            raise ValueError(
                "cannot void invoice with recorded payments; issue refund or credit first"
            )
        now = datetime.now(UTC)
        await ledger.save_invoice(void_invoice(invoice, reason=reason or "admin_void", now=now))
        # A void invoice must not keep an active dunning ladder.
        await dunning.suppress_for_invoice(invoice_id=invoice_id, reason="invoice_voided", now=now)

    return void_billing_invoice


def build_autopay_status_gateway(repo: MongoStudentBillingEnrollmentRepository) -> Any:
    """Adapt the billing enrollment repo to the enrollment-context
    ``EnrollmentAutopayStatusGateway`` port (``set_enrollment_status``)."""

    class _Gateway:
        async def set_enrollment_status(self, *, enrollment_id: str, status: str) -> bool:
            return await repo.set_autopay_enrollment_status(
                enrollment_id=enrollment_id,
                status=status,  # type: ignore[arg-type]
            )

    return _Gateway()
