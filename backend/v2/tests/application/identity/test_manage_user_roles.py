from unittest.mock import AsyncMock

import pytest
from backend.v2.contexts.identity.application.errors import UserNotFound
from backend.v2.contexts.identity.application.use_cases.admin_directory import (
    AdminUserDetail,
)
from backend.v2.contexts.identity.application.use_cases.manage_user_roles import (
    AddUserRole,
    ModifyUserRoleCommand,
    RemoveUserRole,
)


def _detail(roles: list[str]) -> AdminUserDetail:
    return AdminUserDetail(
        user_id="user-1",
        email="user@example.com",
        display_name="User One",
        role=roles[0],
        status="active",
        phone=None,
        roles=roles,
        linked_student_count=0,
        session_count=0,
    )


@pytest.mark.asyncio
async def test_add_role_delegates_to_repo():
    repo = AsyncMock()
    repo.add_role.return_value = _detail(["admin", "coach"])

    result = await AddUserRole(repo).execute(
        "user-1",
        ModifyUserRoleCommand(role="coach", actor_id="admin-1", reason="Also coaches"),
        academy_id="acad",
    )

    assert set(result.roles) == {"admin", "coach"}
    repo.add_role.assert_awaited_once_with(
        "user-1",
        "coach",
        academy_id="acad",
        actor_id="admin-1",
        reason="Also coaches",
    )


@pytest.mark.asyncio
async def test_add_role_raises_when_user_not_found():
    repo = AsyncMock()
    repo.add_role.return_value = None
    with pytest.raises(UserNotFound):
        await AddUserRole(repo).execute(
            "user-x",
            ModifyUserRoleCommand(role="coach", actor_id="admin-1", reason="r"),
            academy_id="acad",
        )


@pytest.mark.asyncio
async def test_remove_role_delegates_to_repo():
    repo = AsyncMock()
    repo.remove_role.return_value = _detail(["admin"])

    result = await RemoveUserRole(repo).execute(
        "user-1",
        ModifyUserRoleCommand(role="coach", actor_id="admin-1", reason="No longer coaches"),
        academy_id="acad",
    )

    assert result.roles == ("admin",)
    repo.remove_role.assert_awaited_once_with(
        "user-1",
        "coach",
        academy_id="acad",
        actor_id="admin-1",
        reason="No longer coaches",
    )


@pytest.mark.asyncio
async def test_remove_role_raises_when_user_not_found():
    repo = AsyncMock()
    repo.remove_role.return_value = None
    with pytest.raises(UserNotFound):
        await RemoveUserRole(repo).execute(
            "user-x",
            ModifyUserRoleCommand(role="coach", actor_id="admin-1", reason="r"),
            academy_id="acad",
        )
