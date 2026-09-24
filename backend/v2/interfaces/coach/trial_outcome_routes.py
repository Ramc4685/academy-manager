"""Coach BFF: Came / Didn't come on a trial row of the coach's day (People CRM L3a).

``POST /coach/trials/{request_id}/outcome`` with
``{"outcome": "came" | "no_show"}``. The request id is the
``trial_request_id`` carried by a trial row of ``GET /coach/today``.

* ``require_coach_surface``: a coach, or a coach supervisor (academy admin or
  owner, #632). Parents get the wrong-persona 404.
* A coach may mark only a trial whose assigned date is on a session they
  coach (primary or assistant). Any other trial, another academy's trial and
  an unknown id all answer the same 404, so nothing leaks about classes the
  coach does not teach. A supervisor may mark any trial of the academy.
* 409 ``Enrollment.TrialOutcomeNotAllowed`` as on the admin route.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from backend.v2.composition.trial_outcomes import mark_trial_outcome_from_state
from backend.v2.contexts.enrollment.application.use_cases.trial_outcomes import (
    MarkTrialOutcome,
    MarkTrialOutcomeCommand,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import is_coach_supervisor, require_coach_surface

router = APIRouter(tags=["coach"])


class CoachTrialOutcomeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: Literal["came", "no_show"]


class CoachTrialOutcomeResponse(BaseModel):
    request_id: str
    status: str
    outcome: Literal["came", "no_show"] | None


def get_mark_trial_outcome(request: Request) -> MarkTrialOutcome:
    service = mark_trial_outcome_from_state(request.app.state)
    if service is None:
        raise HTTPException(status_code=503, detail="trial outcomes are not configured")
    return service


@router.post("/trials/{request_id}/outcome", response_model=CoachTrialOutcomeResponse)
async def record_trial_outcome(
    request_id: str,
    body: CoachTrialOutcomeBody,
    claims: AuthClaims = Depends(require_coach_surface()),
    mark: MarkTrialOutcome = Depends(get_mark_trial_outcome),
) -> CoachTrialOutcomeResponse:
    updated = await mark.execute(
        MarkTrialOutcomeCommand(
            request_id=request_id,
            actor_id=claims.user_id,
            outcome=body.outcome,
            coach_id=None if is_coach_supervisor(claims) else claims.user_id,
        )
    )
    return CoachTrialOutcomeResponse(
        request_id=updated.request_id, status=updated.status, outcome=updated.outcome
    )
