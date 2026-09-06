"""Admin directory routes for users and students."""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.v2.contexts.billing.application.use_cases.tuition_discounts import (
    attach_tuition_discount_badges,
)
from backend.v2.contexts.enrollment.application.use_cases.admin_directory import (
    ChangeAdminStudentParentCommand,
    UpdateAdminStudentCommand,
    decode_student_cursor,
)
from backend.v2.contexts.identity.application.change_user_role_use_case import (
    ChangeUserRoleCommand,
)
from backend.v2.contexts.identity.application.errors import (
    CannotRemoveLastRole,
    LoginInviteSendFailed,
)
from backend.v2.contexts.identity.application.use_cases.admin_directory import (
    CreateAdminUserCommand,
    UpdateAdminUserCommand,
)
from backend.v2.contexts.identity.application.use_cases.manage_user_roles import (
    ModifyUserRoleCommand,
)
from backend.v2.contexts.identity.application.use_cases.provision_student_login import (
    ProvisionStudentLoginCommand,
)
from backend.v2.interfaces.admin.deps import AdminUseCases, get_admin_use_cases
from backend.v2.interfaces.admin.owner_gate import ensure_can_assign_role
from backend.v2.interfaces.admin.views import (
    AdminStudentDetailView,
    AdminStudentList,
    AdminStudentParentChangeView,
    AdminStudentView,
    AdminUserDetailView,
    AdminUserList,
    AdminUserUpdatedView,
    AdminUserView,
    BulkInviteRequest,
    BulkInviteResponse,
    BulkInviteResultItem,
    ChangeAdminStudentParentRequest,
    CreateAdminUserRequest,
    LoginInviteOutcomeView,
    LoginInviteResponse,
    ModifyUserRoleRequest,
    StudentLoginInviteRequest,
    UpdateAdminStudentRequest,
    UpdateAdminUserRequest,
    UpdateAdminUserRoleRequest,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.config.settings import get_settings
from backend.v2.shared.http import require_persona

logger = logging.getLogger(__name__)
router = APIRouter(tags=["admin.directory"])


async def _attach_tuition_discounts(data: dict, use_cases: AdminUseCases) -> None:
    """Enrich admin student detail with recurring tuition discount badges (#244).

    Delegates to the billing application layer so this BFF route never imports
    the billing domain directly (DDD boundary; enforced by import-linter).
    """
    discounts_repo = getattr(use_cases, "tuition_discounts", None)
    await attach_tuition_discount_badges(data.get("enrolled_sessions") or [], discounts_repo)


@router.get("/users", response_model=AdminUserList)
async def list_users(
    role: Literal["admin", "coach", "assistant_coach", "parent", "owner"] | None = Query(
        default=None
    ),
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
    ensure_can_assign_role(claims, payload.role)
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
    invite = use_cases.send_login_invite
    if invite is not None and payload.role == "parent":
        try:
            await invite.execute(user.user_id, academy_id=claims.academy_id)
        except Exception:
            logger.exception("login invite failed for %s", user.user_id)
    return AdminUserDetailView(**user.model_dump())


@router.post("/users/bulk-invite", response_model=BulkInviteResponse)
async def bulk_invite_parents(
    payload: BulkInviteRequest,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> BulkInviteResponse:
    from backend.v2.contexts.identity.application.errors import UserEmailAlreadyExists

    use_case = use_cases.create_admin_user
    if use_case is None:
        raise HTTPException(status_code=503, detail="Admin user creation is not configured")

    results: list[BulkInviteResultItem] = []
    created = skipped = failed = 0

    for item in payload.users:
        try:
            user = await use_case.execute(
                CreateAdminUserCommand(
                    role="parent",
                    email=item.email,
                    display_name=item.display_name,
                    actor_id=claims.user_id,
                    reason=payload.reason,
                ),
                academy_id=claims.academy_id,
            )
            results.append(
                BulkInviteResultItem(status="created", email=item.email, user_id=user.user_id)
            )
            created += 1
            invite = use_cases.send_login_invite
            if invite is not None:
                try:
                    await invite.execute(user.user_id, academy_id=claims.academy_id)
                except Exception:
                    logger.exception("login invite failed for %s", item.email)
        except UserEmailAlreadyExists:
            results.append(
                BulkInviteResultItem(
                    status="skipped", email=item.email, detail="email already exists"
                )
            )
            skipped += 1
        except Exception as exc:
            logger.exception("bulk invite failed for %s", item.email, exc_info=exc)
            results.append(
                BulkInviteResultItem(
                    status="failed", email=item.email, detail="user creation failed"
                )
            )
            failed += 1

    return BulkInviteResponse(created=created, skipped=skipped, failed=failed, results=results)


@router.post("/users/{user_id}/roles", response_model=AdminUserDetailView)
async def add_user_role(
    user_id: str,
    payload: ModifyUserRoleRequest,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminUserDetailView:
    ensure_can_assign_role(claims, payload.role)
    use_case = use_cases.add_user_role
    if use_case is None:
        raise HTTPException(status_code=503, detail="Role management is not configured")
    user = await use_case.execute(
        user_id,
        ModifyUserRoleCommand(role=payload.role, actor_id=claims.user_id, reason=payload.reason),
        academy_id=claims.academy_id,
    )
    return AdminUserDetailView(**user.model_dump())


@router.delete("/users/{user_id}/roles/{role}", response_model=AdminUserDetailView)
async def remove_user_role(
    user_id: str,
    role: Literal["admin", "coach", "assistant_coach", "parent", "owner"],
    reason: str = Query(default="Admin role change", min_length=1, max_length=500),
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminUserDetailView:
    if claims.user_id == user_id and role in ("admin", "owner"):
        raise HTTPException(status_code=409, detail=f"You cannot remove your own {role} role")
    ensure_can_assign_role(claims, role)
    use_case = use_cases.remove_user_role
    if use_case is None:
        raise HTTPException(status_code=503, detail="Role management is not configured")
    try:
        user = await use_case.execute(
            user_id,
            ModifyUserRoleCommand(role=role, actor_id=claims.user_id, reason=reason),
            academy_id=claims.academy_id,
        )
    except CannotRemoveLastRole:
        raise HTTPException(status_code=409, detail="User must keep at least one role") from None
    return AdminUserDetailView(**user.model_dump())


@router.patch("/users/{user_id}", response_model=AdminUserUpdatedView)
async def update_user(
    user_id: str,
    payload: UpdateAdminUserRequest,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminUserUpdatedView:
    """Edit a directory user; a changed email also re-sends the login invite.

    Firebase clears `email_verified` on an email change and the password
    login path rejects unverified tokens, so the edit alone would silently
    lock the user out. The use case sends one fresh invite and reports the
    outcome in `login_invite` so the admin sees a failed send instead of
    assuming it worked (issue #436).
    """
    use_case = use_cases.update_admin_user
    if use_case is None:
        raise HTTPException(status_code=503, detail="Admin user edit is not configured")
    result = await use_case.execute(
        user_id,
        UpdateAdminUserCommand(
            email=payload.email,
            display_name=payload.display_name,
            phone=payload.phone,
            status=payload.status,
            actor_id=claims.user_id,
            reason=payload.reason,
        ),
        academy_id=claims.academy_id,
    )
    return AdminUserUpdatedView(
        **result.user.model_dump(),
        login_invite=LoginInviteOutcomeView(**result.login_invite.model_dump()),
    )


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
    ensure_can_assign_role(claims, payload.role)
    # Replacing a role also revokes every role the target holds today, so an
    # admin-only caller must not be able to demote an owner/admin by setting
    # their role to "parent". Check the held roles, not just the requested one.
    detail_use_case = use_cases.get_admin_user
    if detail_use_case is not None:
        current = await detail_use_case.execute(user_id, academy_id=claims.academy_id)
        for held in getattr(current, "roles", None) or ():
            ensure_can_assign_role(claims, held)
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


@router.post("/users/{user_id}/login-invite", response_model=LoginInviteResponse)
async def send_login_invite(
    user_id: str,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> LoginInviteResponse:
    use_case = use_cases.send_login_invite
    if use_case is None:
        raise HTTPException(status_code=503, detail="Login invites are not configured")
    try:
        result = await use_case.execute(user_id, academy_id=claims.academy_id)
    except LoginInviteSendFailed as exc:
        logger.exception("login invite failed for %s", user_id)
        raise HTTPException(
            status_code=502, detail=f"Could not send the invite email: {exc}"
        ) from exc
    return LoginInviteResponse(sent_at=result.sent_at)


@router.get("/students", response_model=AdminStudentList)
async def list_students(
    search: str | None = Query(default=None, min_length=1, max_length=80),
    status: str | None = Query(default=None, max_length=32),
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None, max_length=512),
    missing: str | None = Query(
        default=None,
        max_length=200,
        description="Comma-separated required fields still missing, e.g. "
        "date_of_birth,emergency_contact_name (issue #380)",
    ),
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminStudentList:
    missing_keys = tuple(k.strip() for k in missing.split(",") if k.strip()) if missing else ()
    try:
        if cursor is not None:
            decode_student_cursor(cursor)
        page = await use_cases.list_admin_students.execute(
            search=search,
            status=status,
            limit=limit,
            cursor=cursor,
            missing=missing_keys,
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
    data = student.model_dump()
    await _attach_tuition_discounts(data, use_cases)
    return AdminStudentDetailView(**data)


@router.post("/students/{student_id}/login-invite", response_model=LoginInviteResponse)
async def send_student_login_invite(
    student_id: str,
    payload: StudentLoginInviteRequest,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> LoginInviteResponse:
    """UIM12: provision a student's own login and email a set-password invite.

    Two-step, same shape as `create_user` + its inline invite (lines ~92-118
    above): provision the account, then reuse `send_login_invite` unchanged.
    `StudentNotFound` / `StudentAlreadyLinked` / `UserAlreadyLinkedToStudent`
    / `UserOutsideAcademy` from the provisioning step map to 404/409 via the
    registered `DomainError` handler.

    Gated by `enable_student_login` exactly like the `/student/*` read
    surface: with the flag off (the shipping default, and the incident kill
    switch) this route must not mint Firebase accounts, grant `student`
    memberships, or send mail. 404 — not 403 — to match the persona-mismatch
    convention in `docs/security-matrix.md`.
    """
    if not get_settings().enable_student_login:
        raise HTTPException(status_code=404, detail="Not found")

    provision = use_cases.provision_student_login
    if provision is None:
        raise HTTPException(status_code=503, detail="Student login invites are not configured")

    display_name = payload.display_name
    if not display_name:
        get_student = use_cases.get_admin_student
        if get_student is None:
            raise HTTPException(status_code=503, detail="Admin student detail is not configured")
        student = await get_student.execute(student_id)
        display_name = student.full_name

    user_id = await provision.execute(
        ProvisionStudentLoginCommand(
            student_id=student_id,
            email=payload.email,
            display_name=display_name,
            actor_id=claims.user_id,
            reason=payload.reason,
        ),
        academy_id=claims.academy_id,
    )

    invite = use_cases.send_login_invite
    if invite is None:
        raise HTTPException(status_code=503, detail="Login invites are not configured")
    try:
        result = await invite.execute(user_id, academy_id=claims.academy_id)
    except LoginInviteSendFailed as exc:
        logger.exception("student login invite failed for %s", student_id)
        raise HTTPException(
            status_code=502, detail=f"Could not send the invite email: {exc}"
        ) from exc
    return LoginInviteResponse(sent_at=result.sent_at)


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
            status=payload.status,
            parent_id=payload.parent_id,
            notes=payload.notes,
            previous_experience=payload.previous_experience,
            medical_notes=payload.medical_notes,
            emergency_contact_name=payload.emergency_contact_name,
            emergency_contact_phone=payload.emergency_contact_phone,
            t_shirt_size=payload.t_shirt_size,
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
