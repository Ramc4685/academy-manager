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

from backend.v2.contexts.ai.application.ports import LlmPort
from backend.v2.contexts.ai.application.use_cases.record_ai_call import (
    DEFAULT_MONTHLY_CALL_CAP,
    RecordAiCall,
)
from backend.v2.contexts.ai.infrastructure.anthropic_llm_port import AnthropicLlmPort
from backend.v2.contexts.ai.infrastructure.disabled_llm_port import DisabledLlmPort
from backend.v2.contexts.ai.infrastructure.mongo_ai_call_repo import MongoAiCallRepository
from backend.v2.contexts.identity.infrastructure.mongo_academy_repo import (
    MongoAcademyRepository,
)
from backend.v2.shared.tenancy import current_academy_id

logger = logging.getLogger(__name__)


class AcademyAiCapLookup:
    """``MonthlyCapSource`` over the academy document: ``ai.monthly_call_cap``,
    read for the academy in scope, the way ``AcademyWinBackSwitch`` reads
    ``notifications.win_back_enabled``."""

    def __init__(self, academies: Any) -> None:
        self._academies = academies

    async def monthly_cap(self) -> int:
        doc = await self._academies.find_by_id(current_academy_id())
        ai = (doc or {}).get("ai") if isinstance(doc, dict) else None
        cap = ai.get("monthly_call_cap") if isinstance(ai, dict) else None
        if isinstance(cap, int) and not isinstance(cap, bool) and cap >= 0:
            return cap
        return DEFAULT_MONTHLY_CALL_CAP


@dataclass(frozen=True)
class AiComposition:
    llm: LlmPort
    record_ai_call: RecordAiCall


def compose_ai(db: Any, settings: Any) -> AiComposition:
    llm: LlmPort
    if settings.ai_enabled and settings.anthropic_api_key:
        llm = AnthropicLlmPort(api_key=settings.anthropic_api_key.get_secret_value())
    else:
        llm = DisabledLlmPort()
    return AiComposition(
        llm=llm,
        record_ai_call=RecordAiCall(
            calls=MongoAiCallRepository(db),
            cap_source=AcademyAiCapLookup(MongoAcademyRepository(db)),
        ),
    )
