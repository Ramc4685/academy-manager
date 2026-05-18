"""Admin directory routes for users and students."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query

from backend.v2.interfaces.admin.deps import AdminUseCases, get_admin_use_cases
from backend.v2.interfaces.admin.views import (
    AdminStudentList,
    AdminStudentView,
    AdminUserList,
    AdminUserView,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["admin.directory"])


@router.get("/users", response_model=AdminUserList)
async def list_users(
    role: Literal["admin", "coach", "parent"] | None = Query(default=None),
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminUserList:
    users = await use_cases.list_admin_users.execute(role)
    return AdminUserList(users=[AdminUserView(**u.model_dump()) for u in users])


@router.get("/students", response_model=AdminStudentList)
async def list_students(
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminStudentList:
    students = await use_cases.list_admin_students.execute()
    return AdminStudentList(
        students=[AdminStudentView(**s.model_dump()) for s in students]
    )
