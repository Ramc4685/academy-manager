"""Reshape a computed coach payout statement into persistable finance lines.

Extracted from ``composition/admin.py`` (audit item MT1). The calculator wraps
the coaching context's payout computation and maps its lines onto finance's
own ``PersistedPayoutLine`` — application logic, not wiring, so it lives here.
The computation itself is injected as a protocol so finance keeps no import
edge into the coaching context.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol, cast

from backend.v2.contexts.finance.application.ports import PayoutCalculation
from backend.v2.contexts.finance.domain.payout_period import PersistedPayoutLine


class CoachPayoutComputer(Protocol):
    """The coaching-side use case that computes a payout statement."""

    async def execute(
        self,
        *,
        coach_id: str,
        academy_id: str,
        period_start: datetime,
        period_end: datetime,
    ) -> Any: ...

    async def execute_many(
        self,
        *,
        coach_ids: list[str],
        academy_id: str,
        period_start: datetime,
        period_end: datetime,
    ) -> dict[str, Any]: ...


def _to_calculation(statement: Any) -> PayoutCalculation:
    updated = statement.model_copy(
        update={
            "lines": [
                PersistedPayoutLine(
                    occurrence_id=line.occurrence_id,
                    coach_id=line.coach_id,
                    basis=line.basis,
                    minutes=line.minutes,
                    amount_minor=line.amount_minor,
                    currency=line.currency,
                    rate_id=line.rate_id,
                    percent_bps=line.percent_bps,
                    expected_revenue_minor=line.expected_revenue_minor,
                )
                for line in statement.lines
            ]
        }
    )
    return cast(PayoutCalculation, updated)


class FinancePayoutCalculator:
    def __init__(self, compute: CoachPayoutComputer) -> None:
        self._compute = compute

    async def calculate(
        self,
        *,
        coach_id: str,
        academy_id: str,
        period_start: datetime,
        period_end: datetime,
    ) -> PayoutCalculation:
        statement = await self._compute.execute(
            coach_id=coach_id,
            academy_id=academy_id,
            period_start=period_start,
            period_end=period_end,
        )
        return _to_calculation(statement)

    async def calculate_many(
        self,
        *,
        coach_ids: list[str],
        academy_id: str,
        period_start: datetime,
        period_end: datetime,
    ) -> dict[str, PayoutCalculation]:
        """Batch variant sharing one occurrence fetch across coaches (#529)."""
        statements = await self._compute.execute_many(
            coach_ids=coach_ids,
            academy_id=academy_id,
            period_start=period_start,
            period_end=period_end,
        )
        return {coach_id: _to_calculation(statement) for coach_id, statement in statements.items()}
