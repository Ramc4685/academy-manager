"""Composition for the Pipeline board (People CRM L3a moves, L3b board).

Wiring only, built on first use and kept on ``app.state`` by
``interfaces/admin/pipeline_routes.py``, so ``main.py`` and the line-capped
``composition/admin.py`` stay untouched:

* ``app.state.crm_pipeline_moves``: ``MoveCardOnPipeline`` over the
  tenant-scoped ``MongoCrmContactRepository``;
* ``app.state.crm_pipeline_board``: ``GetPipelineBoard`` over the same
  repository and the family index already on ``app.state.admin_family_index``
  (``composition/families_crm.py``), so the board shares the index's cache;
* ``app.state.crm_quick_add``: the existing ``CreateContact`` (quick add lead).
"""

from __future__ import annotations

from typing import Any

from backend.v2.contexts.crm.application.pipeline_board import GetPipelineBoard
from backend.v2.contexts.crm.application.use_cases.create_contact import CreateContact
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


def pipeline_board_from_state(state: Any) -> GetPipelineBoard | None:
    """The app's ``GetPipelineBoard``, composed once; ``None`` without a db.

    Without the family index bundle the board still answers from
    ``crm_contacts`` with the ``families_unavailable`` warning.
    """
    service = getattr(state, "crm_pipeline_board", None)
    if service is not None:
        return service  # type: ignore[no-any-return]
    db = getattr(state, "db", None)
    if db is None:
        return None
    bundle = getattr(state, "admin_family_index", None)
    families = getattr(bundle, "index", None)
    service = GetPipelineBoard(MongoCrmContactRepository(db), families)
    state.crm_pipeline_board = service
    return service


def quick_add_from_state(state: Any) -> CreateContact | None:
    """The app's ``CreateContact`` for staff quick add; ``None`` without a db."""
    service = getattr(state, "crm_quick_add", None)
    if service is not None:
        return service  # type: ignore[no-any-return]
    db = getattr(state, "db", None)
    if db is None:
        return None
    service = CreateContact(MongoCrmContactRepository(db))
    state.crm_quick_add = service
    return service
