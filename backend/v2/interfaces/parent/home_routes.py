"""Parent home aggregate route (kid-first Home, slice 4).

One read backs the whole Home screen: rendering N children from the
per-resource parent endpoints would cost 2N round trips on a phone. All of
the fan-out lives in ``composition.parent.get_parent_home``; this route only
maps the result into views.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from backend.v2.interfaces.parent.deps import ParentUseCases, get_parent_use_cases
from backend.v2.interfaces.parent.views import (
    ParentHomeAttendanceView,
    ParentHomeBalanceView,
    ParentHomeChildView,
    ParentHomeMilestoneView,
    ParentHomeNextSessionView,
    ParentHomeResponse,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["parent.home"])


def _next_session_view(data: dict[str, Any] | None) -> ParentHomeNextSessionView | None:
    if not data:
        return None
    return ParentHomeNextSessionView(**data)


def _milestone_view(data: dict[str, Any] | None) -> ParentHomeMilestoneView | None:
    if not data:
        return None
    return ParentHomeMilestoneView(**data)


@router.get(
    "/home",
    response_model=ParentHomeResponse,
    summary="Everything the parent home screen needs, in one read",
)
async def get_parent_home(
    claims: AuthClaims = Depends(require_persona("parent")),
    use_cases: ParentUseCases = Depends(get_parent_use_cases),
) -> ParentHomeResponse:
    result: dict[str, Any] = await use_cases.get_parent_home(  # type: ignore[operator]
        parent_id=claims.user_id
    )
    return ParentHomeResponse(
        children=[
            ParentHomeChildView(
                student_id=child["student_id"],
                full_name=child["full_name"],
                next_session=_next_session_view(child.get("next_session")),
                attendance_this_month=ParentHomeAttendanceView(
                    **child["attendance_this_month"],
                ),
                latest_milestone=_milestone_view(child.get("latest_milestone")),
            )
            for child in result["children"]
        ],
        balance=ParentHomeBalanceView(**result["balance"]),
        month_label=result["month_label"],
        timezone=result["timezone"],
    )
