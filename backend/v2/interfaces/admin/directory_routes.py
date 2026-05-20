"""Admin directory routes for users and students."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.v2.interfaces.admin.deps import AdminUseCases, get_admin_use_cases
from backend.v2.interfaces.admin.views import (
    AdminStudentList,
    AdminStudentView,
    AdminUserList,
    AdminUserView,
    UpdateAdminUserRoleRequest,
)
from backend.v2.contexts.enrollment.application.use_cases.admin_directory import (
    decode_student_cursor,
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
    users = await use_cases.list_admin_users.execute(role, academy_id=_claims.academy_id)
    return AdminUserList(users=[AdminUserView(**u.model_dump()) for u in users])


@router.patch("/users/{user_id}/role", response_model=AdminUserView)
async def update_user_role(
    user_id: str,
    payload: UpdateAdminUserRoleRequest,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminUserView:
    if user_id == claims.user_id:
        from backend.v2.shared.http.errors import DomainError

        class SelfRoleChangeForbidden(DomainError):
            code = "Identity.SelfRoleChangeForbidden"
            status_code = 400

        raise SelfRoleChangeForbidden("cannot change your own role")
    user = await use_cases.change_user_role.execute(
        user_id, payload.role, academy_id=claims.academy_id
    )
    return AdminUserView(**user.model_dump())


@router.get("/students", response_model=AdminStudentList)
async def list_students(
    search: str | None = Query(default=None, min_length=1, max_length=80),
    status: str | None = Query(default=None, max_length=32),
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None, max_length=512),
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminStudentList:
    try:
        if cursor is not None:
            decode_student_cursor(cursor)
        page = await use_cases.list_admin_students.execute(
            search=search,
            status=status,
            limit=limit,
            cursor=cursor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return AdminStudentList(
        students=[AdminStudentView(**s.model_dump()) for s in page.students],
        next_cursor=page.next_cursor,
    )
