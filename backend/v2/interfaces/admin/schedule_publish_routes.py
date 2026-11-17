"""Publish class dates to parents, a month at a time.

``schedule_published_through`` is the last month the academy calls final.
Parents see later months marked "not confirmed yet" and the calendar feed
leaves them out. ``null`` withdraws publishing (every date shows, as before
the academy first published).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.v2.interfaces.admin.deps import AdminUseCases, get_admin_use_cases
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["admin.schedule"])

_MONTH = r"^\d{4}-(0[1-9]|1[0-2])$"


class SchedulePublishView(BaseModel):
    published_through: str | None = None


class SchedulePublishRequest(BaseModel):
    published_through: str | None = Field(default=None, pattern=_MONTH)


@router.get("/schedule/publish", response_model=SchedulePublishView)
async def get_schedule_publish(
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> SchedulePublishView:
    if use_cases.self_service_policy is None:
        raise HTTPException(status_code=503, detail="Schedule publishing is not configured")
    policy = await use_cases.self_service_policy.execute()
    return SchedulePublishView(published_through=policy.schedule_published_through)


@router.put("/schedule/publish", response_model=SchedulePublishView)
async def set_schedule_publish(
    body: SchedulePublishRequest,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> SchedulePublishView:
    if use_cases.set_schedule_published_through is None:
        raise HTTPException(status_code=503, detail="Schedule publishing is not configured")
    policy = await use_cases.set_schedule_published_through.execute(body.published_through)
    return SchedulePublishView(published_through=policy.schedule_published_through)
