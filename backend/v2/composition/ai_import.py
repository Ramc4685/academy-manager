"""Roster-import copilot wiring (plan 2026-11-04 Phase 2, slice B2).

``MapImportColumns`` over the gated ``LlmPort`` and ``RecordAiCall`` that
``composition/ai.py`` built, plus the per-academy "share real spreadsheet
values" switch read from the academy document (``ai.share_import_values``)
the way ``AcademyAiCapLookup`` reads the cap. Attached at
``app.state.ai_import`` by ``main.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.v2.composition.ai import AiComposition
from backend.v2.contexts.ai.application.use_cases.map_import_columns import MapImportColumns
from backend.v2.contexts.identity.infrastructure.mongo_academy_repo import (
    MongoAcademyRepository,
)
from backend.v2.shared.tenancy import current_academy_id


class AcademyImportValueSharing:
    """``ImportValueSharing`` over ``ai.share_import_values``; absent or not a
    bool means off. Read for the academy in scope at execution time."""

    def __init__(self, academies: Any) -> None:
        self._academies = academies

    async def share_values(self) -> bool:
        doc = await self._academies.find_by_id(current_academy_id())
        ai = (doc or {}).get("ai") if isinstance(doc, dict) else None
        value = ai.get("share_import_values") if isinstance(ai, dict) else None
        return value is True

    async def set_share_values(self, value: bool) -> None:
        await self._academies.update_by_id(current_academy_id(), {"ai.share_import_values": value})


@dataclass(frozen=True)
class AiImportComposition:
    map_columns: MapImportColumns
    sharing: AcademyImportValueSharing


def compose_ai_import(db: Any, ai: AiComposition) -> AiImportComposition:
    sharing = AcademyImportValueSharing(MongoAcademyRepository(db))
    return AiImportComposition(
        map_columns=MapImportColumns(llm=ai.llm, record_ai_call=ai.record_ai_call, sharing=sharing),
        sharing=sharing,
    )
