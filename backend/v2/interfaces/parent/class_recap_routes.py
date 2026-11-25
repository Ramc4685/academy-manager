"""Parent class timeline: classes one's own child was marked present for,
newest first and paged, with what the class worked on, what this child
practised, and the skills this child passed at that class.

Never the raw coach report, other children, or classes the child missed. A
child who is not the caller's is 404, like every parent student route.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from backend.v2.interfaces.parent.deps import ParentUseCases, get_parent_use_cases
from backend.v2.interfaces.parent.progress_skill_routes import _verify_child_ownership
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["parent-class-recap"])


class ChildRecapSkillView(BaseModel):
    skill_id: str
    name: str


class ChildClassRecapView(BaseModel):
    occurrence_id: str
    class_starts_at: datetime
    taught_skills: list[ChildRecapSkillView]
    practiced_skills: list[ChildRecapSkillView]
    #: Passed by a demonstration in this class and still held.
    earned_skills: list[ChildRecapSkillView]


class ChildClassRecapList(BaseModel):
    recaps: list[ChildClassRecapView]
    #: Send back as ``cursor`` for older classes; null on the last page.
    next_cursor: str | None = None


@router.get("/students/{student_id}/class-recaps", response_model=ChildClassRecapList)
async def list_child_class_recaps(
    student_id: str,
    request: Request,
    cursor: str | None = Query(default=None, max_length=200),
    claims: AuthClaims = Depends(require_persona("parent")),
    use_cases: ParentUseCases = Depends(get_parent_use_cases),
) -> ChildClassRecapList:
    await _verify_child_ownership(claims.user_id, student_id, use_cases)
    page = await request.app.state.class_recap.list_for_child.execute(student_id, cursor=cursor)
    return ChildClassRecapList.model_validate(page.model_dump())
