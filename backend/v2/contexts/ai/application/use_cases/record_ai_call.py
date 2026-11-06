"""Reserve and record one model call against the academy's hard cap. No model call here."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from backend.v2.contexts.ai.application.ports import (
    AiCallCounterRepository,
    AiCallRepository,
    DailyCapSource,
    MonthlyCapSource,
)
from backend.v2.contexts.ai.domain.errors import AiDailyCapReached, AiMonthlyCapReached
from backend.v2.contexts.ai.domain.models import AiCallRecord, LlmResult

#: Calls per academy per UTC month when the academy document sets no cap.
DEFAULT_MONTHLY_CALL_CAP = 200


class RecordAiCall:
    def __init__(
        self,
        *,
        calls: AiCallRepository,
        counters: AiCallCounterRepository,
        cap_source: MonthlyCapSource,
        daily_caps: DailyCapSource | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._calls = calls
        self._counters = counters
        self._cap_source = cap_source
        self._daily_caps = daily_caps
        self._clock = clock or (lambda: datetime.now(UTC))

    @asynccontextmanager
    async def reserve(self, feature: str) -> AsyncIterator[None]:
        """Hold one slot of the month (and of ``feature``'s day, when the
        academy sets a daily ceiling) for the model call made inside the block.

        Refuses with ``AiMonthlyCapReached`` / ``AiDailyCapReached`` before any
        tokens are spent. The slot is taken atomically, so concurrent calls at
        the cap minus one let exactly one through. Any error raised inside the
        block (the provider failing, or the prep before it) gives the slot
        back. Features wrap only the model call (and its prep) in the block,
        then call ``execute`` after it."""
        now = self._clock()
        month_key = f"month:{now:%Y-%m}"
        cap = await self._cap_source.monthly_cap()
        if not await self._counters.reserve(month_key, cap):
            raise AiMonthlyCapReached(
                f"monthly AI call cap reached ({cap} of {cap})", used=cap, cap=cap
            )
        keys = [month_key]
        try:
            daily = await self._daily_caps.daily_cap(feature) if self._daily_caps else None
            if daily is not None:
                day_key = f"day:{now:%Y-%m-%d}:{feature}"
                if not await self._counters.reserve(day_key, daily):
                    raise AiDailyCapReached(
                        f"daily AI call cap reached for {feature} ({daily} of {daily})",
                        feature=feature,
                        used=daily,
                        cap=daily,
                    )
                keys.append(day_key)
            yield
        except BaseException:
            for key in keys:
                await self._counters.release(key)
            raise

    async def execute(
        self,
        *,
        feature: str,
        prompt_version: str,
        result: LlmResult,
        approver: str | None,
    ) -> AiCallRecord:
        """Write the audit row. Never refuses: the tokens are already spent."""
        record = AiCallRecord(
            feature=feature,
            prompt_version=prompt_version,
            model=result.model,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            cost_cents=result.cost_cents,
            approver=approver,
            created_at=self._clock(),
        )
        await self._calls.record(record)
        return record
