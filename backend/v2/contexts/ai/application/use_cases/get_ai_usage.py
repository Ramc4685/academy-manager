"""The AI usage meter (plan 2026-11-04 Phase 2, slice A3): this month's
``ai_calls`` against the plan's cap. Read-only; the free cap is a soft
upgrade prompt (owner decision 4), never a refusal. ``RecordAiCall`` keeps
the hard abuse ceiling."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel

from backend.v2.contexts.ai.application.ports import (
    AiCallRepository,
    EntitlementSource,
    MonthlyCapSource,
)
from backend.v2.contexts.ai.domain.errors import AiAcademyNotFound
from backend.v2.shared.tenancy import tenant_scope

#: Drafts per UTC month before the free tier is prompted to upgrade.
FREE_TIER_MONTHLY_DRAFTS = 20


class AiUsage(BaseModel):
    model_config = {"frozen": True}

    used: int
    cap: int
    tier: Literal["free", "growth"]
    upgrade_suggested: bool
    month: str


class GetAiUsage:
    """Usage for the academy in scope."""

    def __init__(
        self,
        *,
        calls: AiCallRepository,
        cap_source: MonthlyCapSource,
        entitlements: EntitlementSource,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._calls = calls
        self._cap_source = cap_source
        self._entitlements = entitlements
        self._clock = clock or (lambda: datetime.now(UTC))

    async def execute(self) -> AiUsage:
        now = self._clock()
        used = await self._calls.count_since(datetime(now.year, now.month, 1, tzinfo=UTC))
        growth = await self._entitlements.has_feature("ai")
        cap = await self._cap_source.monthly_cap() if growth else FREE_TIER_MONTHLY_DRAFTS
        return AiUsage(
            used=used,
            cap=cap,
            tier="growth" if growth else "free",
            upgrade_suggested=not growth and used >= cap,
            month=now.strftime("%Y-%m"),
        )


class GetAiUsageForAcademy:
    """Platform view: the same meter for the academy named on the route,
    entered through ``tenant_scope`` like ``GetApplicationFee``."""

    def __init__(
        self, *, usage: GetAiUsage, academy_exists: Callable[[str], Awaitable[bool]]
    ) -> None:
        self._usage = usage
        self._academy_exists = academy_exists

    async def execute(self, academy_id: str) -> AiUsage:
        if not await self._academy_exists(academy_id):
            raise AiAcademyNotFound("academy not found", academy_id=academy_id)
        with tenant_scope(academy_id):
            return await self._usage.execute()
