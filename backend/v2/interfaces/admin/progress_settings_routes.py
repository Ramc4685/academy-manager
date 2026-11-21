"""Settings > Curriculum: celebration milestones and the share-page name rule (L5B).

``GET``/``PUT /admin/curriculum/progress-settings``. Owner or admin. The save
replaces the whole block (it is one small form), validated here and in the
domain model, written with a targeted ``$set`` and audited as
``progress_settings.changed``. Thresholds apply going forward only.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ValidationError

from backend.v2.contexts.student_progress.application.use_cases.progress_milestones import (
    MAX_MILESTONE_COUNT,
    MAX_MILESTONES,
    ProgressSettings,
    UpdateProgressSettingsCommand,
)
from backend.v2.interfaces.admin.deps import AdminUseCases, get_admin_use_cases
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["admin-pathway"])

PATH = "/curriculum/progress-settings"


class MilestoneInput(BaseModel):
    kind: Literal["skills_passed", "levels_completed"]
    count: int = Field(ge=1, le=MAX_MILESTONE_COUNT)


class UpdateProgressSettingsBody(BaseModel):
    milestones_enabled: bool
    milestones: list[MilestoneInput] = Field(default_factory=list, max_length=MAX_MILESTONES)
    share_name: Literal["first_name", "initial"]


class MilestoneView(BaseModel):
    kind: Literal["skills_passed", "levels_completed"]
    count: int
    #: When the threshold was added: milestones reached before it are not celebrated.
    since: datetime


class ProgressSettingsView(BaseModel):
    milestones_enabled: bool
    milestones: list[MilestoneView]
    share_name: Literal["first_name", "initial"]


def _view(settings: ProgressSettings) -> ProgressSettingsView:
    return ProgressSettingsView(
        milestones_enabled=settings.milestones_enabled,
        milestones=[
            MilestoneView(kind=m.kind, count=m.count, since=m.since) for m in settings.milestones
        ],
        share_name=settings.share_name,
    )


def _progress(use_cases: AdminUseCases) -> Any:
    if use_cases.student_progress is None:
        raise HTTPException(status_code=503, detail="Student progress service not configured")
    return use_cases.student_progress


@router.get(PATH, response_model=ProgressSettingsView)
async def get_progress_settings(
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> ProgressSettingsView:
    return _view(await _progress(use_cases).get_progress_settings.execute())


@router.put(PATH, response_model=ProgressSettingsView)
async def update_progress_settings(
    body: UpdateProgressSettingsBody,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> ProgressSettingsView:
    try:
        settings = await _progress(use_cases).update_progress_settings.execute(
            UpdateProgressSettingsCommand(
                actor_id=claims.user_id,
                milestones_enabled=body.milestones_enabled,
                milestones=[(m.kind, m.count) for m in body.milestones],
                share_name=body.share_name,
            )
        )
    except ValidationError as exc:
        # Only the duplicate rule is left for the domain model to catch.
        raise HTTPException(status_code=422, detail="Each milestone may appear once.") from exc
    return _view(settings)
