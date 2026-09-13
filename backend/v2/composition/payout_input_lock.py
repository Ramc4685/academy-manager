"""Frozen-payout lookup shared by the contexts that own payroll inputs (#787).

Coach attendance (coaching) and date cancellation (enrollment) both feed the
payout calculation, and both used to be editable long after Finance had
approved or paid the period covering the date. A frozen period does not
re-read those inputs, so the edit never reached payroll and nothing said so.

Finance owns ``PayoutPeriod``; neither context may import it (ADR-0005
rule 5). Each declares its own one-method ``PayoutPeriodLock`` protocol, and
this adapter — structurally satisfying both — is the single place that
translates "is this coach's window frozen?" into a Finance read.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.v2.contexts.finance.application.ports import PayoutPeriodRepository
from backend.v2.contexts.finance.infrastructure.mongo_payout_period_repo import (
    MongoPayoutPeriodRepository,
)


class PayoutInputLock:
    """``PayoutPeriodLock`` for coaching and enrollment, backed by finance."""

    def __init__(self, periods: PayoutPeriodRepository) -> None:
        self._periods = periods

    async def locked_status_for(self, *, coach_id: str, at: datetime) -> str | None:
        return await self._periods.find_locked_status_for_coach(coach_id=coach_id, at=at)


def compose_payout_input_lock(
    db: Any, *, periods: PayoutPeriodRepository | None = None
) -> PayoutInputLock:
    return PayoutInputLock(periods or MongoPayoutPeriodRepository(db))
