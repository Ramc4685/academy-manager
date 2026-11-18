"""Parent class recap read: recent classes one's own child was marked present
for, what the class worked on, what this child practised, and which of those
skills the pass pipeline records as passed.

Never the raw coach report, other children, or classes the child missed. A
child who is not the caller's is 404, like every parent student route.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from backend.v2.interfaces.parent.deps import ParentUseCases, get_parent_use_cases
from backend.v2.interfaces.parent.progress_skill_routes import _verify_child_ownership
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["parent-class-recap"])


class ChildClassRecapView(BaseModel):
    occurrence_id: str
    class_starts_at: datetime
    taught_skills: list[str]
    practiced_skills: list[str]
    passed_skills: list[str]


class ChildClassRecapList(BaseModel):
    recaps: list[ChildClassRecapView]


@router.get("/students/{student_id}/class-recaps", response_model=ChildClassRecapList)
async def list_child_class_recaps(
    student_id: str,
    request: Request,
    claims: AuthClaims = Depends(require_persona("parent")),
    use_cases: ParentUseCases = Depends(get_parent_use_cases),
) -> ChildClassRecapList:
    await _verify_child_ownership(claims.user_id, student_id, use_cases)
    rows = await request.app.state.class_recap.list_for_child.execute(student_id)
    return ChildClassRecapList(recaps=[ChildClassRecapView(**r.model_dump()) for r in rows])
