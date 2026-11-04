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

    async def execute(
        self,
        *,
        feature: str,
        prompt_version: str,
        result: LlmResult,
        approver: str | None,
    ) -> AiCallRecord:
        now = self._clock()
        month_start = datetime(now.year, now.month, 1, tzinfo=UTC)
        used = await self._calls.count_since(month_start)
        cap = await self._cap_source.monthly_cap()
        # shortcut: the cap is checked when the call is recorded, after the
        # tokens were spent; split out a pre-call check when the first
        # feature must refuse before calling the model.
        if used + 1 > cap:
            raise AiMonthlyCapReached(
                f"monthly AI call cap reached ({used} of {cap})", used=used, cap=cap
            )
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
