"""Parent academy info route."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.v2.interfaces.parent.deps import ParentUseCases, get_parent_use_cases
from backend.v2.interfaces.parent.views import ParentAcademyView
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["parent.academy"])


@router.get("/academy", response_model=ParentAcademyView, summary="Academy contact info")
async def get_academy_info(
    claims: AuthClaims = Depends(require_persona("parent")),
    use_cases: ParentUseCases = Depends(get_parent_use_cases),
) -> ParentAcademyView:
    info = await use_cases.get_academy_info(academy_id=claims.academy_id)  # type: ignore[operator]
    return ParentAcademyView(**info)
