"""Admin BFF: the Pipeline board (People CRM L3a moves, L3b board and quick add).

``GET /admin/crm/pipeline`` answers every card on the board
(``contexts/crm/application/pipeline_board.py``): ``crm_contacts`` leads plus
the family index's trial and lead-only families. No money on a card, so the
board is the same for every admin-persona tier.

``POST /admin/crm/contacts`` is the board's quick add lead: the existing
``CreateContact`` with a staff source (``whatsapp_or_phone``, ``referral``,
``other``; never ``website``), ``created_by`` the caller, stage ``lead``.
Staff rows are never deduped (README "Idempotency"); the form disables its
button while saving and shows the duplicate warning.

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
from pydantic import BaseModel, ConfigDict, Field

from backend.v2.composition.crm_pipeline import (
    move_card_from_state,
    pipeline_board_from_state,
    quick_add_from_state,
)
from backend.v2.contexts.crm.application.pipeline_board import (
    GetPipelineBoard,
    PipelineCard,
    contact_card,
    quick_add_command,
)
from backend.v2.contexts.crm.application.use_cases.create_contact import CreateContact
from backend.v2.contexts.crm.application.use_cases.pipeline_moves import (
    MoveCardCommand,
    MoveCardOnPipeline,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona
from backend.v2.shared.tenancy import TenantContextUnset, current_academy_id

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


# --- L3b: the board and quick add -------------------------------------------

BoardColumn = Literal["inquiry", "trial_booked", "trial_done", "registered", "enrolled"]


class PipelineBoardCardView(BaseModel):
    card_id: str
    kind: Literal["contact", "family"]
    column: BoardColumn
    name: str
    contact_id: str | None = None
    family_id: str | None = None
    child: str | None = None
    child_age: str | None = None
    source: str | None = None
    created_at: datetime | None = None
    lead_age_days: int | None = None
    override_column: str | None = None
    override_set_by: str | None = None
    override_set_at: datetime | None = None
    move_targets: list[BoardColumn] = Field(default_factory=list)


class PipelineBoardView(BaseModel):
    generated_at: datetime
    cards: list[PipelineBoardCardView]
    warnings: list[str] = Field(default_factory=list)


class QuickAddLeadBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(max_length=200)
    phone: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=300)
    child_name: str | None = Field(default=None, max_length=200)
    child_age: str | None = Field(default=None, max_length=40)
    source: Literal["whatsapp_or_phone", "referral", "other"]


def _card_view(card: PipelineCard) -> PipelineBoardCardView:
    return PipelineBoardCardView(
        card_id=card.card_id,
        kind=card.kind,
        column=card.column,
        name=card.name,
        contact_id=card.contact_id,
        family_id=card.family_id,
        child=card.child,
        child_age=card.child_age,
        source=card.source,
        created_at=card.created_at,
        lead_age_days=card.lead_age_days,
        override_column=card.override_column,
        override_set_by=card.override_set_by,
        override_set_at=card.override_set_at,
        move_targets=list(card.move_targets),
    )


def get_pipeline_board(request: Request) -> GetPipelineBoard:
    service = pipeline_board_from_state(request.app.state)
    if service is None:
        raise HTTPException(status_code=503, detail="pipeline board is not configured")
    return service


def get_quick_add(request: Request) -> CreateContact:
    service = quick_add_from_state(request.app.state)
    if service is None:
        raise HTTPException(status_code=503, detail="quick add is not configured")
    return service


def _academy_id(claims: AuthClaims) -> str:
    try:
        return current_academy_id()
    except TenantContextUnset:
        return claims.academy_id


@router.get("/crm/pipeline", response_model=PipelineBoardView)
async def pipeline_board(
    claims: AuthClaims = Depends(require_persona("admin")),
    board: GetPipelineBoard = Depends(get_pipeline_board),
) -> PipelineBoardView:
    result = await board.execute(_academy_id(claims))
    return PipelineBoardView(
        generated_at=result.generated_at,
        cards=[_card_view(card) for card in result.cards],
        warnings=list(result.warnings),
    )


@router.post("/crm/contacts", response_model=PipelineBoardCardView, status_code=201)
async def quick_add_lead(
    body: QuickAddLeadBody,
    claims: AuthClaims = Depends(require_persona("admin")),
    create: CreateContact = Depends(get_quick_add),
) -> PipelineBoardCardView:
    result = await create.execute(
        quick_add_command(
            name=body.name,
            source=body.source,
            actor_id=claims.user_id,
            phone=body.phone,
            email=body.email,
            child_name=body.child_name,
            child_age=body.child_age,
        )
    )
    contact = result.contact
    return _card_view(contact_card(contact, now=contact.created_at))
