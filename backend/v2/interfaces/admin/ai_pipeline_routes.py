"""Admin BFF: the AI-drafted reply on a pipeline card (B3, paid).

* ``POST /admin/pipeline/cards/{contact_id}/reply-draft``: a draft for the
  staff member to edit (``DraftPipelineReply``). Writes nothing but the
  ``ai_calls`` row. 404 for a contact outside the tenant; 403
  ``Ai.NotEntitled`` without the plan's ``ai`` feature; 429 at the monthly
  cap; 503 ``Ai.Disabled`` while AI is off; 502 for an unreadable answer.
* ``POST /admin/pipeline/cards/{contact_id}/reply``: the human approval.
  Sends the edited text to the lead through the prospect send path and logs
  it on the family contact log (``SendPipelineReply``). Works with AI off.
  409 ``Crm.PipelineReplyNotSendable`` for a lead with no email or a
  suppressed address.

``require_persona("admin")`` like every pipeline route; coaches and parents
get the wrong-persona 404.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from backend.v2.contexts.crm.application.use_cases.family_notes import Actor
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona
from backend.v2.shared.tenancy import TenantContextUnset, current_academy_id

router = APIRouter(tags=["admin.people"])


class ReplyDraftView(BaseModel):
    subject: str
    body: str
    key_points: list[str]
    prompt_version: str


class ReplyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=1500)


class ReplySentView(BaseModel):
    log_id: str
    parent_id: str
    channel: str
    status: str
    note: str | None
    author_user_id: str
    created_at: datetime


def get_ai_pipeline(request: Request) -> Any:
    services = getattr(request.app.state, "ai_pipeline", None)
    if services is None:
        raise HTTPException(status_code=503, detail="pipeline replies are not configured")
    return services


def _academy_id(claims: AuthClaims) -> str:
    try:
        return current_academy_id()
    except TenantContextUnset:
        return claims.academy_id


@router.post("/pipeline/cards/{contact_id}/reply-draft", response_model=ReplyDraftView)
async def draft_pipeline_reply(
    contact_id: str,
    claims: AuthClaims = Depends(require_persona("admin")),
    services: Any = Depends(get_ai_pipeline),
) -> ReplyDraftView:
    result = await services.draft_reply.execute(contact_id=contact_id, staff_user_id=claims.user_id)
    return ReplyDraftView(
        subject=result.draft.subject,
        body=result.draft.body,
        key_points=list(result.draft.key_points),
        prompt_version=result.prompt_version,
    )


@router.post("/pipeline/cards/{contact_id}/reply", response_model=ReplySentView, status_code=201)
async def send_pipeline_reply(
    contact_id: str,
    body: ReplyBody,
    claims: AuthClaims = Depends(require_persona("admin")),
    services: Any = Depends(get_ai_pipeline),
) -> ReplySentView:
    row = await services.send_reply.execute(
        academy_id=_academy_id(claims),
        contact_id=contact_id,
        subject=body.subject.strip(),
        body=body.body.strip(),
        actor=Actor(user_id=claims.user_id, roles=tuple(claims.roles)),
    )
    return ReplySentView(
        log_id=row.log_id,
        parent_id=row.parent_id,
        channel=row.channel,
        status=row.status,
        note=row.note,
        author_user_id=row.author_user_id,
        created_at=row.created_at,
    )
