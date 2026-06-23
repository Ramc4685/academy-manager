"""Admin corrections to persisted payout periods (Phase 2).

Three mutations, all draft-gated and all audited:

- ``RecomputePayoutPeriod`` — re-run the calculator against current
  attendance/rates and rewrite the period's lines. Manual line overrides
  survive the recompute: they are re-applied by ``occurrence_id`` on top
  of the freshly computed amounts (the new computed amount becomes the
  override's ``original_amount_minor``).
- ``ReopenPayoutPeriod`` — approved/paid back to draft, reason required.
  Paid metadata is cleared on the period but preserved in the audit
  entry's ``before`` snapshot.
- ``OverridePayoutLine`` — set (or clear) a manual amount on one line,
  reason required. The period total is rebuilt from the lines.

``ListPayoutAuditEntries`` reads the trail back for the admin UI.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from backend.v2.contexts.finance.application.ports import (
    PayoutAuditLog,
    PayoutCalculator,
    PayoutPeriodRepository,
)
from backend.v2.contexts.finance.domain.payout_audit import PayoutAuditEntry
from backend.v2.contexts.finance.domain.payout_period import (
    PayoutPeriod,
    PayoutPeriodStateError,
    PayoutWarning,
    PersistedPayoutLine,
    reopen,
)
from backend.v2.shared.ids import new_ulid


class _Audited:
    def __init__(
        self,
        *,
        repository: PayoutPeriodRepository,
        audit: PayoutAuditLog,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._repo = repository
        self._audit = audit
        self._clock = clock or (lambda: datetime.now(UTC))
        self._id = id_factory or (lambda: str(new_ulid()))

    async def _load(self, period_id: str) -> PayoutPeriod:
        period = await self._repo.find_by_id(period_id)
        if period is None:
            raise LookupError(f"PayoutPeriod {period_id!r} not found")
        return period

    async def _record(
        self,
        period: PayoutPeriod,
        *,
        action: str,
        actor_id: str,
        occurrence_id: str | None = None,
        reason: str | None = None,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
    ) -> None:
        await self._audit.append(
            PayoutAuditEntry(
                audit_id=self._id(),
                academy_id=period.academy_id,
                period_id=period.period_id,
                occurrence_id=occurrence_id,
                action=action,  # type: ignore[arg-type]
                actor_id=actor_id,
                at=self._clock(),
                reason=reason,
                before=before,
                after=after,
            )
        )


class RecomputePayoutPeriod(_Audited):
    def __init__(
        self,
        *,
        calculator: PayoutCalculator,
        repository: PayoutPeriodRepository,
        audit: PayoutAuditLog,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        super().__init__(repository=repository, audit=audit, clock=clock, id_factory=id_factory)
        self._calc = calculator

    async def execute(self, *, period_id: str, actor_id: str) -> PayoutPeriod:
        period = await self._load(period_id)
        if period.status != "draft":
            raise PayoutPeriodStateError(
                f"cannot recompute payout period {period_id!r} in status "
                f"{period.status!r}; reopen it first"
            )

        calc = await self._calc.calculate(
            coach_id=period.coach_id,
            academy_id=period.academy_id,
            period_start=period.period_start,
            period_end=period.period_end,
        )

        overrides = {
            line.occurrence_id: line
            for line in period.lines
            if line.original_amount_minor is not None
        }
        lines: list[PersistedPayoutLine] = []
        for line in calc.lines:
            override = overrides.get(line.occurrence_id)
            if override is not None:
                line = line.model_copy(
                    update={
                        "amount_minor": override.amount_minor,
                        "original_amount_minor": line.amount_minor,
                        "adjustment_reason": override.adjustment_reason,
                    }
                )
            lines.append(line)

        total = sum(line.amount_minor for line in lines)
        updated = period.model_copy(
            update={
                "currency": calc.currency,
                "total_minor": total,
                "lines": lines,
                "unpaid_occurrence_ids": list(calc.unpaid_occurrence_ids),
                "unpaid_occurrences": list(calc.unpaid_occurrences),
                "payout_warnings": [
                    PayoutWarning.model_validate(
                        warning.model_dump() if hasattr(warning, "model_dump") else warning
                    )
                    for warning in getattr(calc, "payout_warnings", [])
                ],
                "generated_at": self._clock(),
            }
        )
        stored = await self._repo.replace_with_lines(updated)
        await self._record(
            stored,
            action="recomputed",
            actor_id=actor_id,
            before={"total_minor": period.total_minor, "line_count": len(period.lines)},
            after={"total_minor": stored.total_minor, "line_count": len(stored.lines)},
        )
        return stored


class ReopenPayoutPeriod(_Audited):
    async def execute(self, *, period_id: str, actor_id: str, reason: str) -> PayoutPeriod:
        if not reason.strip():
            raise ValueError("reason is required to reopen a payout period")
        period = await self._load(period_id)
        reopened = reopen(period)
        stored = await self._repo.replace(reopened)
        await self._record(
            stored,
            action="reopened",
            actor_id=actor_id,
            reason=reason,
            before={
                "status": period.status,
                "approved_at": _iso(period.approved_at),
                "paid_at": _iso(period.paid_at),
                "paid_method": period.paid_method,
                "paid_amount_minor": period.paid_amount_minor,
                "paid_reference": period.paid_reference,
            },
            after={"status": stored.status},
        )
        return stored


class OverridePayoutLine(_Audited):
    async def execute(
        self,
        *,
        period_id: str,
        occurrence_id: str,
        amount_minor: int | None,
        reason: str,
        actor_id: str,
    ) -> PayoutPeriod:
        if not reason.strip():
            raise ValueError("reason is required to change a payout line")
        if amount_minor is not None and amount_minor < 0:
            raise ValueError("amount must not be negative")

        period = await self._load(period_id)
        if period.status != "draft":
            raise PayoutPeriodStateError(
                f"cannot edit lines of payout period {period_id!r} in status "
                f"{period.status!r}; reopen it first"
            )

        target = next((ln for ln in period.lines if ln.occurrence_id == occurrence_id), None)
        if target is None:
            raise LookupError(f"occurrence {occurrence_id!r} is not on payout period {period_id!r}")

        if amount_minor is None:
            if target.original_amount_minor is None:
                raise ValueError(f"line {occurrence_id!r} has no override to clear")
            updated_line = target.model_copy(
                update={
                    "amount_minor": target.original_amount_minor,
                    "original_amount_minor": None,
                    "adjustment_reason": None,
                }
            )
            action = "line_override_cleared"
        else:
            updated_line = target.model_copy(
                update={
                    "amount_minor": amount_minor,
                    # Keep the first computed amount across repeated edits.
                    "original_amount_minor": (
                        target.original_amount_minor
                        if target.original_amount_minor is not None
                        else target.amount_minor
                    ),
                    "adjustment_reason": reason,
                }
            )
            action = "line_overridden"

        lines = [updated_line if ln.occurrence_id == occurrence_id else ln for ln in period.lines]
        updated = period.model_copy(
            update={"lines": lines, "total_minor": sum(ln.amount_minor for ln in lines)}
        )
        stored = await self._repo.replace_with_lines(updated)
        await self._record(
            stored,
            action=action,
            actor_id=actor_id,
            occurrence_id=occurrence_id,
            reason=reason,
            before={"amount_minor": target.amount_minor, "total_minor": period.total_minor},
            after={"amount_minor": updated_line.amount_minor, "total_minor": stored.total_minor},
        )
        return stored


class ListPayoutAuditEntries:
    def __init__(self, *, audit: PayoutAuditLog) -> None:
        self._audit = audit

    async def execute(self, *, period_id: str) -> list[PayoutAuditEntry]:
        return await self._audit.list_for_period(period_id)


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()
