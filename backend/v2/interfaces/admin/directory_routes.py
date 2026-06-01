"""Admin directory routes for users and students."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.v2.contexts.enrollment.application.use_cases.admin_directory import (
    ChangeAdminStudentParentCommand,
    UpdateAdminStudentCommand,
    decode_student_cursor,
)
from backend.v2.contexts.identity.application.change_user_role_use_case import (
    ChangeUserRoleCommand,
)
from backend.v2.contexts.identity.application.use_cases.admin_directory import (
    CreateAdminUserCommand,
    UpdateAdminUserCommand,
)
from backend.v2.interfaces.admin.deps import AdminUseCases, get_admin_use_cases
from backend.v2.interfaces.admin.views import (
    AdminStudentDetailView,
    AdminStudentList,
    AdminStudentParentChangeView,
    AdminStudentView,
    AdminUserDetailView,
    AdminUserList,
    AdminUserView,
    ChangeAdminStudentParentRequest,
    CreateAdminUserRequest,
    UpdateAdminStudentRequest,
    UpdateAdminUserRequest,
    UpdateAdminUserRoleRequest,
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


@router.get("/users/{user_id}", response_model=AdminUserDetailView)
async def get_user(
    user_id: str,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminUserDetailView:
    use_case = use_cases.get_admin_user
    if use_case is None:
        raise HTTPException(status_code=503, detail="Admin user detail is not configured")
    user = await use_case.execute(user_id, academy_id=claims.academy_id)
    return AdminUserDetailView(**user.model_dump())


@router.post("/users", response_model=AdminUserDetailView, status_code=201)
async def create_user(
    payload: CreateAdminUserRequest,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminUserDetailView:
    use_case = use_cases.create_admin_user
    if use_case is None:
        raise HTTPException(status_code=503, detail="Admin user creation is not configured")
    user = await use_case.execute(
        CreateAdminUserCommand(
            role=payload.role,
            email=payload.email,
            display_name=payload.display_name,
            phone=payload.phone,
            actor_id=claims.user_id,
            reason=payload.reason,
        ),
        academy_id=claims.academy_id,
    )
    return AdminUserDetailView(**user.model_dump())


@router.patch("/users/{user_id}", response_model=AdminUserDetailView)
async def update_user(
    user_id: str,
    payload: UpdateAdminUserRequest,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminUserDetailView:
    use_case = use_cases.update_admin_user
    if use_case is None:
        raise HTTPException(status_code=503, detail="Admin user edit is not configured")
    user = await use_case.execute(
        user_id,
        UpdateAdminUserCommand(
            display_name=payload.display_name,
            phone=payload.phone,
            status=payload.status,
            actor_id=claims.user_id,
            reason=payload.reason,
        ),
        academy_id=claims.academy_id,
    )
    return AdminUserDetailView(**user.model_dump())


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
        user_id,
        ChangeUserRoleCommand(
            role=payload.role,
            actor_id=claims.user_id,
            reason=payload.reason,
        ),
        academy_id=claims.academy_id,
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


@router.get("/students/{student_id}", response_model=AdminStudentDetailView)
async def get_student(
    student_id: str,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminStudentDetailView:
    use_case = use_cases.get_admin_student
    if use_case is None:
        raise HTTPException(status_code=503, detail="Admin student detail is not configured")
    student = await use_case.execute(student_id)
    return AdminStudentDetailView(**student.model_dump())


@router.patch("/students/{student_id}", response_model=AdminStudentDetailView)
async def update_student(
    student_id: str,
    payload: UpdateAdminStudentRequest,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminStudentDetailView:
    use_case = use_cases.update_admin_student
    if use_case is None:
        raise HTTPException(status_code=503, detail="Admin student edit is not configured")
    student = await use_case.execute(
        student_id,
        UpdateAdminStudentCommand(
            full_name=payload.full_name,
            date_of_birth=payload.date_of_birth,
            level=payload.level,
            status=payload.status,
            parent_id=payload.parent_id,
            notes=payload.notes,
            actor_id=claims.user_id,
            reason=payload.reason,
        ),
    )
    return AdminStudentDetailView(**student.model_dump())


@router.post("/students/{student_id}/change-parent", response_model=AdminStudentParentChangeView)
async def change_student_parent(
    student_id: str,
    payload: ChangeAdminStudentParentRequest,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminStudentParentChangeView:
    use_case = use_cases.change_admin_student_parent
    if use_case is None:
        raise HTTPException(
            status_code=503,
            detail="Admin student parent change is not configured",
        )
    result = await use_case.execute(
        student_id,
        ChangeAdminStudentParentCommand(
            parent_id=payload.parent_id,
            actor_id=claims.user_id,
            reason=payload.reason,
        ),
    )
    return AdminStudentParentChangeView(**result.model_dump())
