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
