"""Composition for Pipeline board moves (People CRM L3a).

Wiring only: ``MoveCardOnPipeline`` over the tenant-scoped
``MongoCrmContactRepository``. Built on first use and kept on
``app.state.crm_pipeline_moves`` by ``interfaces/admin/pipeline_routes.py``,
so ``main.py`` and the line-capped ``composition/admin.py`` stay untouched.
"""

from __future__ import annotations

from typing import Any

from backend.v2.contexts.crm.application.use_cases.pipeline_moves import MoveCardOnPipeline
from backend.v2.contexts.crm.infrastructure.mongo_crm_contact_repo import (
    MongoCrmContactRepository,
)


def compose_move_card_on_pipeline(db: Any) -> MoveCardOnPipeline:
    return MoveCardOnPipeline(MongoCrmContactRepository(db))


def move_card_from_state(state: Any) -> MoveCardOnPipeline | None:
    """The app's ``MoveCardOnPipeline``, composed once; ``None`` without a db."""
    service = getattr(state, "crm_pipeline_moves", None)
    if service is not None:
        return service  # type: ignore[no-any-return]
    db = getattr(state, "db", None)
    if db is None:
        return None
    service = compose_move_card_on_pipeline(db)
    state.crm_pipeline_moves = service
    return service
