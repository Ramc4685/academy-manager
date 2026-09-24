"""Admin BFF: Came / Didn't come on an approved trial (People CRM L3a).

``POST /admin/self-service/trials/{request_id}/outcome`` with
``{"outcome": "came" | "no_show"}`` records the outcome through
``MarkTrialOutcome`` and answers the updated Inbox trial row.

* ``require_persona("admin")``: the same gate as the Inbox approve and deny
  routes beside it. A coach, a parent, or a staff tier without the ``admin``
  role gets the wrong-persona 404 (docs/security-matrix.md). No money is
  involved.
* Tenant-scoped: the trial is read through the tenant-scoped repository, so
  another academy's id is the same 404 as an unknown one.
* 409 ``Enrollment.TrialOutcomeNotAllowed`` (``details.reason``) when the
  trial is not approved, has no or a cancelled date, or has not started.
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
from backend.v2.interfaces.admin.self_service_request_routes import TrialRequestAdminRow
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["admin.self-service-requests"])


class TrialOutcomeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: Literal["came", "no_show"]


def get_mark_trial_outcome(request: Request) -> MarkTrialOutcome:
    service = mark_trial_outcome_from_state(request.app.state)
    if service is None:
        raise HTTPException(status_code=503, detail="trial outcomes are not configured")
    return service


@router.post(
    "/self-service/trials/{request_id}/outcome",
    response_model=TrialRequestAdminRow,
)
async def record_trial_outcome(
    request_id: str,
    body: TrialOutcomeBody,
    claims: AuthClaims = Depends(require_persona("admin")),
    mark: MarkTrialOutcome = Depends(get_mark_trial_outcome),
) -> TrialRequestAdminRow:
    updated = await mark.execute(
        MarkTrialOutcomeCommand(
            request_id=request_id, actor_id=claims.user_id, outcome=body.outcome
        )
    )
    return TrialRequestAdminRow(**updated.model_dump(exclude={"academy_id", "parent_user_id"}))
