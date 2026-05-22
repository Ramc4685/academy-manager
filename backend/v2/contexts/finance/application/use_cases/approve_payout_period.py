"""State-machine transitions on a persisted ``PayoutPeriod``.

Two use cases here because they're both small and naturally paired:

- ``ApprovePayoutPeriod``: draft -> approved
- ``MarkPayoutPaid``: approved -> paid

Both are idempotent. Calling approve on an already-approved period
returns it unchanged. Calling mark-paid on an already-paid period
returns it unchanged. Illegal transitions raise
``PayoutPeriodStateError``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Callable

from backend.v2.contexts.finance.application.ports import PayoutPeriodRepository
from backend.v2.contexts.finance.domain.payout_period import (
    PayoutPeriod,
    approve,
    mark_paid,
)


class _BaseTransition:
    def __init__(
        self,
        *,
        repository: PayoutPeriodRepository,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._repo = repository
        self._clock = clock

    async def _load(self, period_id: str) -> PayoutPeriod:
        period = await self._repo.find_by_id(period_id)
        if period is None:
            raise LookupError(f"PayoutPeriod {period_id!r} not found")
        return period


class ApprovePayoutPeriod(_BaseTransition):
    async def execute(self, *, period_id: str) -> PayoutPeriod:
        period = await self._load(period_id)
        approved = approve(period, at=self._clock())
        if approved is period:
            return period
        return await self._repo.replace(approved)


class MarkPayoutPaid(_BaseTransition):
    async def execute(self, *, period_id: str) -> PayoutPeriod:
        period = await self._load(period_id)
        paid = mark_paid(period, at=self._clock())
        if paid is period:
            return period
        return await self._repo.replace(paid)
