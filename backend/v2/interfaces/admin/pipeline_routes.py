"""Admin BFF: move a lead's card on the Pipeline board (People CRM L3a).

``POST /admin/crm/contacts/{contact_id}/pipeline-move`` with
``{"to_column": "inquiry" | "trial_booked" | "trial_done" | "registered"}``
records a staff move with no system write behind it as
``crm_contacts.pipeline_override = {column, set_by, set_at}`` and answers the
card's new position.

* ``require_persona("admin")``, like every People CRM route
  (``tests/structural/test_crm_admin_persona_gate.py``). Coaches and parents
  get the wrong-persona 404 (docs/security-matrix.md).
* Tenant-scoped: another academy's contact id is the same 404 as an unknown
  one; the body carries no academy (extra fields are refused).
* 409 ``Crm.PipelineMoveNotAllowed`` (``details.reason``): a forward skip
  (``stage_skip``), a move of an enrolled contact (``contact_enrolled``) or a
  concurrent move (``changed``). ``enrolled`` is not accepted as a target:
  only the conversion flow enrolls.
* Trial moves that DO have a system write (approve a trial, Came / Didn't
  come) use their own routes, never this one.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from backend.v2.composition.crm_pipeline import move_card_from_state
from backend.v2.contexts.crm.application.use_cases.pipeline_moves import (
    MoveCardCommand,
    MoveCardOnPipeline,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["admin.people"])


class PipelineMoveBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to_column: Literal["inquiry", "trial_booked", "trial_done", "registered"]


class PipelineOverrideView(BaseModel):
    column: str
    set_by: str
    set_at: datetime


class PipelineCardView(BaseModel):
    contact_id: str
    pipeline_status: str
    column: Literal["inquiry", "trial_booked", "trial_done", "registered", "enrolled"]
    pipeline_override: PipelineOverrideView | None


def get_move_card(request: Request) -> MoveCardOnPipeline:
    service = move_card_from_state(request.app.state)
    if service is None:
        raise HTTPException(status_code=503, detail="pipeline moves are not configured")
    return service


@router.post("/crm/contacts/{contact_id}/pipeline-move", response_model=PipelineCardView)
async def move_pipeline_card(
    contact_id: str,
    body: PipelineMoveBody,
    claims: AuthClaims = Depends(require_persona("admin")),
    move: MoveCardOnPipeline = Depends(get_move_card),
) -> PipelineCardView:
    result = await move.execute(
        MoveCardCommand(contact_id=contact_id, to_column=body.to_column, actor_id=claims.user_id)
    )
    contact = result.contact
    override = contact.pipeline_override
    return PipelineCardView(
        contact_id=contact.contact_id,
        pipeline_status=contact.pipeline_status,
        column=result.column,
        pipeline_override=(
            PipelineOverrideView(
                column=override.column, set_by=override.set_by, set_at=override.set_at
            )
            if override
            else None
        ),
    )
