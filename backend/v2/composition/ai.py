"""AI foundation composition (plan section 4, Phase 1).

The one construction site for ``AnthropicLlmPort`` (structural test
``test_email_sender_construction``): the real adapter is wired only when
``V2_AI_ENABLED`` and ``V2_ANTHROPIC_API_KEY`` are both set, otherwise the
``DisabledLlmPort`` answers every call with ``AiDisabled``. Attached at
``app.state.ai``; no feature reads it yet.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from backend.v2.contexts.ai.application.ports import AiEntitlement, LlmPort
from backend.v2.contexts.ai.application.use_cases.record_ai_call import (
    DEFAULT_MONTHLY_CALL_CAP,
    RecordAiCall,
)
from backend.v2.contexts.ai.infrastructure.anthropic_llm_port import AnthropicLlmPort
from backend.v2.contexts.ai.infrastructure.disabled_llm_port import DisabledLlmPort
from backend.v2.contexts.ai.infrastructure.mongo_ai_call_counter_repo import (
    MongoAiCallCounterRepository,
)
from backend.v2.contexts.ai.infrastructure.mongo_ai_call_repo import MongoAiCallRepository
from backend.v2.contexts.identity.infrastructure.mongo_academy_repo import (
    MongoAcademyRepository,
)
from backend.v2.shared.tenancy import current_academy_id

logger = logging.getLogger(__name__)


def _cap_value(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


class AcademyAiCapLookup:
    """``MonthlyCapSource`` and ``DailyCapSource`` over the academy document:
    ``ai.monthly_call_cap`` and ``ai.daily_call_cap.<feature>``, read for the
    academy in scope, the way ``AcademyWinBackSwitch`` reads
    ``notifications.win_back_enabled``."""

    def __init__(self, academies: Any) -> None:
        self._academies = academies

    async def _ai(self) -> dict[str, Any]:
        doc = await self._academies.find_by_id(current_academy_id())
        ai = (doc or {}).get("ai") if isinstance(doc, dict) else None
        return ai if isinstance(ai, dict) else {}

    async def monthly_cap(self) -> int:
        cap = _cap_value((await self._ai()).get("monthly_call_cap"))
        return DEFAULT_MONTHLY_CALL_CAP if cap is None else cap

    async def daily_cap(self, feature: str) -> int | None:
        """None (no daily ceiling) when the setting is absent or invalid."""
        daily = (await self._ai()).get("daily_call_cap")
        return _cap_value(daily.get(feature)) if isinstance(daily, dict) else None


class PlatformAiEntitlement:
    """``AiEntitlement`` over ``has_feature(academy, "ai")`` for the academy in scope.
    No HasFeature wired (tests) means no entitlement."""

    def __init__(self, has_feature: Any | None) -> None:
        self._has_feature = has_feature

    async def has_ai(self) -> bool:
        if self._has_feature is None:
            return False
        return bool(await self._has_feature.execute(current_academy_id(), "ai"))


@dataclass(frozen=True)
class AiComposition:
    llm: LlmPort
    record_ai_call: RecordAiCall
    entitlement: AiEntitlement


def compose_ai(db: Any, settings: Any, *, has_feature: Any | None = None) -> AiComposition:
    llm: LlmPort
    if settings.ai_enabled and settings.anthropic_api_key:
        llm = AnthropicLlmPort(api_key=settings.anthropic_api_key.get_secret_value())
    else:
        llm = DisabledLlmPort()
    caps = AcademyAiCapLookup(MongoAcademyRepository(db))
    return AiComposition(
        llm=llm,
        record_ai_call=RecordAiCall(
            calls=MongoAiCallRepository(db),
            counters=MongoAiCallCounterRepository(db),
            cap_source=caps,
            daily_caps=caps,
        ),
        entitlement=PlatformAiEntitlement(has_feature),
    )
