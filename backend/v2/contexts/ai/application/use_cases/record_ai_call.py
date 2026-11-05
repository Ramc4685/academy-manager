"""Record one model call against the academy's monthly cap. No model call here."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from backend.v2.contexts.ai.application.ports import AiCallRepository, MonthlyCapSource
from backend.v2.contexts.ai.domain.errors import AiMonthlyCapReached
from backend.v2.contexts.ai.domain.models import AiCallRecord, LlmResult

#: Calls per academy per UTC month when the academy document sets no cap.
DEFAULT_MONTHLY_CALL_CAP = 200


class RecordAiCall:
    def __init__(
        self,
        *,
        calls: AiCallRepository,
        cap_source: MonthlyCapSource,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._calls = calls
        self._cap_source = cap_source
        self._clock = clock or (lambda: datetime.now(UTC))

    async def assert_under_cap(self) -> None:
        """Refuse before any tokens are spent when the month is already at the cap.

        Features call this first, then the model, then ``execute``, which
        checks again when it records the row."""
        await self._check_cap(self._clock())

    async def _check_cap(self, now: datetime) -> None:
        month_start = datetime(now.year, now.month, 1, tzinfo=UTC)
        used = await self._calls.count_since(month_start)
        cap = await self._cap_source.monthly_cap()
        # shortcut: count-then-insert is not atomic (concurrent calls at cap-1
        # can each pass); upgrade to a reserve on a per-month counter document
        # ($inc with a $lt filter) when a paid feature needs a hard ceiling.
        if used + 1 > cap:
            raise AiMonthlyCapReached(
                f"monthly AI call cap reached ({used} of {cap})", used=used, cap=cap
            )

    async def execute(
        self,
        *,
        feature: str,
        prompt_version: str,
        result: LlmResult,
        approver: str | None,
    ) -> AiCallRecord:
        now = self._clock()
        await self._check_cap(now)
        record = AiCallRecord(
            feature=feature,
            prompt_version=prompt_version,
            model=result.model,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            cost_cents=result.cost_cents,
            approver=approver,
            created_at=now,
        )
        await self._calls.record(record)
        return record
