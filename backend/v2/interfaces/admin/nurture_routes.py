"""Admin BFF: the lead nurture sequence editor (AI strategy Phase 3, C1).

* ``GET /admin/crm/nurture-sequence``: the academy's switch (default off),
  when it went on, the day 2, 7 and 21 steps and the merge fields.
* ``PUT /admin/crm/nurture-sequence``: save the switch and the steps.
  Validation is the domain's (``Crm.InvalidNurtureSequence``, 422).
* ``POST /admin/crm/nurture-sequence/preview``: one step rendered with the
  academy's name and booking link and an example class, as plain text.

``require_persona("admin")`` like every People CRM route; coaches and parents
get the wrong-persona 404. The academy is the caller's tenant, never input.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from backend.v2.contexts.crm.application.use_cases.nurture_sequence import (
    MAX_BODY_LENGTH,
    MAX_SUBJECT_LENGTH,
    MERGE_FIELDS,
    NURTURE_STEP_DAYS,
    ManageNurtureSequence,
    NurtureSequence,
    NurtureStep,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona
from backend.v2.shared.tenancy import current_academy_id

router = APIRouter(tags=["admin.people"])

ROUTE = "/crm/nurture-sequence"


class NurtureStepBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    day: int
    subject: str = Field(default="", max_length=MAX_SUBJECT_LENGTH * 2)
    body: str = Field(default="", max_length=MAX_BODY_LENGTH * 2)


class NurtureSequenceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    steps: list[NurtureStepBody] = Field(default_factory=list, max_length=3)


class NurtureStepView(BaseModel):
    day: int
    subject: str
    body: str


class NurtureSequenceView(BaseModel):
    enabled: bool
    enabled_at: datetime | None
    steps: list[NurtureStepView]
    merge_fields: list[str]


class NurturePreviewView(BaseModel):
    subject: str
    body_text: str


def _manage(request: Request) -> ManageNurtureSequence:
    return request.app.state.nurture.manage  # type: ignore[no-any-return]


def _view(sequence: NurtureSequence) -> NurtureSequenceView:
    by_day = {s.day: s for s in sequence.steps}
    return NurtureSequenceView(
        enabled=sequence.enabled,
        enabled_at=sequence.enabled_at,
        # Always all three days, blank when unwritten, so the editor has a slot each.
        steps=[
            NurtureStepView(
                day=day,
                subject=by_day[day].subject if day in by_day else "",
                body=by_day[day].body if day in by_day else "",
            )
            for day in NURTURE_STEP_DAYS
        ],
        merge_fields=list(MERGE_FIELDS),
    )


def _step(body: NurtureStepBody) -> NurtureStep:
    return NurtureStep(day=body.day, subject=body.subject, body=body.body)


@router.get(ROUTE, response_model=NurtureSequenceView)
async def get_nurture_sequence(
    _claims: AuthClaims = Depends(require_persona("admin")),
    manage: ManageNurtureSequence = Depends(_manage),
) -> Any:
    return _view(await manage.get(current_academy_id()))


@router.put(ROUTE, response_model=NurtureSequenceView)
async def put_nurture_sequence(
    body: NurtureSequenceBody,
    claims: AuthClaims = Depends(require_persona("admin")),
    manage: ManageNurtureSequence = Depends(_manage),
) -> Any:
    sequence = await manage.save(
        current_academy_id(),
        enabled=body.enabled,
        steps=[_step(s) for s in body.steps],
        user_id=claims.user_id,
    )
    return _view(sequence)


@router.post(f"{ROUTE}/preview", response_model=NurturePreviewView)
async def preview_nurture_step(
    body: NurtureStepBody,
    _claims: AuthClaims = Depends(require_persona("admin")),
    manage: ManageNurtureSequence = Depends(_manage),
) -> Any:
    subject, text = await manage.preview(current_academy_id(), _step(body))
    return NurturePreviewView(subject=subject, body_text=text)
