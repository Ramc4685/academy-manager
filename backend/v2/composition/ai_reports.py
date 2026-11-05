"""B5 wiring: the month-close narrator, attached at ``app.state.ai_reports``.

Outside ``composition/admin.py`` (at its line budget). The existing month-close
reader is the payload source; the reader resolves the tenant at request time,
so nothing tenant-specific is captured here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.v2.composition.ai import AiComposition
from backend.v2.contexts.ai.application.use_cases.narrate_month_close import NarrateMonthClose


@dataclass(frozen=True)
class AiReportsComposition:
    narrate_month_close: NarrateMonthClose


def compose_ai_reports(ai: AiComposition, month_close: Any) -> AiReportsComposition:
    return AiReportsComposition(
        narrate_month_close=NarrateMonthClose(
            llm=ai.llm,
            entitlement=ai.entitlement,
            record_ai_call=ai.record_ai_call,
            source=month_close,
        )
    )
