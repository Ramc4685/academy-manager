"""Month-dates AI helper wiring: ``SuggestNoClassDates`` over the gated
``LlmPort`` and ``RecordAiCall`` from ``composition/ai.py``. Attached at
``app.state.ai_schedule`` by ``main.py``."""

from __future__ import annotations

from backend.v2.composition.ai import AiComposition
from backend.v2.contexts.ai.application.use_cases.suggest_no_class_dates import (
    SuggestNoClassDates,
)


def compose_ai_schedule(ai: AiComposition) -> SuggestNoClassDates:
    return SuggestNoClassDates(llm=ai.llm, record_ai_call=ai.record_ai_call)
