"""Admin management of the coach rate sheet.

Rates are versioned, never edited in place: setting a new pay rate
supersedes the currently active one (its ``effective_until`` is closed at
the new rate's ``effective_from``) and inserts a new active row. History
is preserved so already-generated payout periods keep pointing at the
rate that was in effect when their occurrences happened.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from pydantic import BaseModel, Field

from backend.v2.contexts.coaching.domain.payout import CoachRate, CoachRateBillingUnit
from backend.v2.shared.ids import new_ulid
from backend.v2.shared.tenancy.context import current_academy_id


class CoachRateWriter(Protocol):
    async def list_for_coach(self, coach_id: str) -> list[CoachRate]: ...

    async def find_active(self, coach_id: str) -> CoachRate | None: ...

    async def supersede(self, rate_id: str, *, effective_until: datetime) -> None: ...

    async def insert(self, rate: CoachRate) -> None: ...


class SetCoachPayRateCommand(BaseModel):
    model_config = {"frozen": True}

    coach_id: str
    billing_unit: CoachRateBillingUnit
    amount_minor: int = Field(default=0, ge=0)
    percent_bps: int | None = Field(default=None, ge=0, le=10000)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    effective_from: datetime | None = None


class SetCoachPayRate:
    def __init__(
        self,
        *,
        rates: CoachRateWriter,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._rates = rates
        self._clock = clock or (lambda: datetime.now(UTC))
        self._id = id_factory or (lambda: str(new_ulid()))

    async def execute(self, command: SetCoachPayRateCommand) -> CoachRate:
        if command.billing_unit == "percent_of_revenue":
            if command.percent_bps is None:
                raise ValueError("percent is required for percent_of_revenue rates")
        elif command.amount_minor <= 0:
            raise ValueError("amount must be positive for per_session/per_hour rates")

        effective_from = command.effective_from or self._clock()

        active = await self._rates.find_active(command.coach_id)
        if active is not None:
            if effective_from <= active.effective_from:
                raise ValueError(
                    "effective_from must be after the current rate's effective_from "
                    f"({active.effective_from.isoformat()})"
                )
            await self._rates.supersede(active.rate_id, effective_until=effective_from)

        rate = CoachRate(
            rate_id=self._id(),
            academy_id=current_academy_id(),
            coach_id=command.coach_id,
            billing_unit=command.billing_unit,
            amount_minor=command.amount_minor,
            percent_bps=(
                command.percent_bps if command.billing_unit == "percent_of_revenue" else None
            ),
            currency=command.currency.upper(),
            effective_from=effective_from,
            effective_until=None,
            status="active",
        )
        await self._rates.insert(rate)
        return rate


class ListCoachPayRates:
    def __init__(self, *, rates: CoachRateWriter) -> None:
        self._rates = rates

    async def execute(self, *, coach_id: str) -> list[CoachRate]:
        rates = await self._rates.list_for_coach(coach_id)
        return sorted(rates, key=lambda r: r.effective_from, reverse=True)
