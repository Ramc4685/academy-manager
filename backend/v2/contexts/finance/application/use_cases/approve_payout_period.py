"""State-machine transitions on a persisted ``PayoutPeriod``.

Two use cases here because they're both small and naturally paired:

- ``ApprovePayoutPeriod``: draft -> approved
- ``MarkPayoutPaid``: approved -> paid

Both are idempotent. Calling approve on an already-approved period
returns it unchanged. Calling mark-paid on an already-paid period
returns it unchanged. Illegal transitions raise
``PayoutPeriodStateError``.

Both are also audited (#787): approving and paying are the two moments
payroll money is committed, so each writes one ``PayoutAuditEntry``. A
no-op (re-approving, re-paying) writes nothing — the trail records
transitions, not requests.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from backend.v2.contexts.finance.application.payout_audit_recorder import PayoutAuditRecorder
from backend.v2.contexts.finance.application.ports import (
    PayoutAuditLog,
    PayoutPeriodRepository,
)
from backend.v2.contexts.finance.application.use_cases.generate_payout_period import (
    OverlappingPayoutPeriodError,
)
from backend.v2.contexts.finance.domain.payout_period import (
    PayoutPeriod,
    approve,
    mark_paid,
    require_version,
)


class MarkPayoutPaidCommand(BaseModel):
    period_id: str
    method: str = Field(min_length=1)
    paid_at: datetime
    amount_minor: int = Field(ge=0)
    reference: str | None = None


class _BaseTransition:
    def __init__(
        self,
        *,
        repository: PayoutPeriodRepository,
        audit: PayoutAuditLog,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._repo = repository
        self._clock = clock
        self._audit = PayoutAuditRecorder(audit=audit, clock=clock, id_factory=id_factory)

    async def _load(self, period_id: str) -> PayoutPeriod:
        period = await self._repo.find_by_id(period_id)
        if period is None:
            raise LookupError(f"PayoutPeriod {period_id!r} not found")
        return period


class ApprovePayoutPeriod(_BaseTransition):
    async def execute(
        self, *, period_id: str, actor_id: str = "system", expected_version: int | None = None
    ) -> PayoutPeriod:
        period = await self._load(period_id)
        if period.status == "approved":
            # Before the version check: a retry whose first response was lost
            # gets the approval back, not a 409 for its own write.
            return period
        require_version(period, expected_version)
        # Any status: two periods over the same days would pay those classes
        # twice, including overlaps stored before generation refused them (#504).
        other = await self._repo.find_overlapping(
            coach_id=period.coach_id,
            period_start=period.period_start,
            period_end=period.period_end,
            exclude_period_id=period.period_id,
        )
        if other is not None:
            raise OverlappingPayoutPeriodError(other)
        approved = approve(period, at=self._clock())
        stored = await self._repo.replace(approved)
        await self._audit.record(
            stored,
            action="approved",
            actor_id=actor_id,
            before={"status": period.status},
            after={
                "status": stored.status,
                "total_minor": stored.total_minor,
                "version": stored.version,
            },
        )
        return stored


class MarkPayoutPaid(_BaseTransition):
    async def execute(
        self,
        command: MarkPayoutPaidCommand | None = None,
        *,
        period_id: str | None = None,
        actor_id: str = "system",
        expected_version: int | None = None,
    ) -> PayoutPeriod:
        if command is None:
            if period_id is None:
                raise TypeError("MarkPayoutPaid.execute requires command or period_id")
            period = await self._load(period_id)
            require_version(period, expected_version)
            command = MarkPayoutPaidCommand(
                period_id=period_id,
                method="unspecified",
                paid_at=self._clock(),
                amount_minor=period.total_minor,
                reference=None,
            )
        else:
            period = await self._load(command.period_id)
            if not _same_payment(period, command):
                # A retry of the payment already recorded skips this check.
                require_version(period, expected_version)

        paid = mark_paid(
            period,
            at=command.paid_at,
            method=command.method,
            amount_minor=command.amount_minor,
            reference=command.reference,
        )
        if paid is period:
            return period
        stored = await self._repo.replace(paid)
        await self._audit.record(
            stored,
            action="marked_paid",
            actor_id=actor_id,
            before={"status": period.status},
            after={
                "status": stored.status,
                "paid_amount_minor": stored.paid_amount_minor,
                "paid_method": stored.paid_method,
                "paid_reference": stored.paid_reference,
                "version": stored.version,
            },
        )
        return stored


def _ms(value: datetime | None) -> datetime | None:
    # Mongo stores milliseconds; a retry's microseconds must not read as a new payment.
    return None if value is None else value.replace(microsecond=value.microsecond // 1000 * 1000)


def _same_payment(period: PayoutPeriod, command: MarkPayoutPaidCommand) -> bool:
    return period.status == "paid" and (
        period.paid_method,
        period.paid_amount_minor,
        period.paid_reference,
        _ms(period.paid_at),
    ) == (command.method, command.amount_minor, command.reference, _ms(command.paid_at))
