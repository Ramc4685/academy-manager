"""Admin identity directory use cases."""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, EmailStr, Field

from backend.v2.contexts.identity.domain.models import Role


class AdminUserSummary(BaseModel):
    model_config = {"frozen": True}

    user_id: str
    email: EmailStr
    display_name: str
    role: Role
    status: str
    phone: str | None = None


class AdminUserDetail(AdminUserSummary):
    model_config = {"frozen": True}

    roles: tuple[Role, ...] = ()
    linked_student_count: int = 0


class UpdateAdminUserCommand(BaseModel):
    model_config = {"frozen": True}

    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    phone: str | None = Field(default=None, max_length=40)
    status: str | None = Field(default=None, max_length=32)
    actor_id: str = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=500)


class AdminUserDirectoryQuery(Protocol):
    async def list_users(
        self, role: Role | None = None, academy_id: str | None = None
    ) -> list[AdminUserSummary]: ...


class AdminUserDetailQuery(Protocol):
    async def get_admin_user(self, user_id: str, *, academy_id: str) -> AdminUserDetail | None: ...


class AdminUserWriter(Protocol):
    async def update_admin_user(
        self,
        user_id: str,
        command: UpdateAdminUserCommand,
        *,
        academy_id: str,
    ) -> AdminUserDetail | None: ...


class ListAdminUsers:
    def __init__(self, users: AdminUserDirectoryQuery) -> None:
        self._users = users

    async def execute(
        self,
        role: Literal["admin", "coach", "parent"] | None = None,
        academy_id: str | None = None,
    ) -> list[AdminUserSummary]:
        return await self._users.list_users(role, academy_id=academy_id)


class GetAdminUser:
    def __init__(self, users: AdminUserDetailQuery) -> None:
        self._users = users

    async def execute(self, user_id: str, *, academy_id: str) -> AdminUserDetail:
        from backend.v2.contexts.identity.domain.errors import UserNotFound

        user = await self._users.get_admin_user(user_id, academy_id=academy_id)
        if user is None:
            raise UserNotFound("user not found")
        return user


class UpdateAdminUser:
    def __init__(self, users: AdminUserWriter) -> None:
        self._users = users

    async def execute(
        self,
        user_id: str,
        command: UpdateAdminUserCommand,
        *,
        academy_id: str,
    ) -> AdminUserDetail:
        from backend.v2.contexts.identity.domain.errors import UserNotFound

        updated = await self._users.update_admin_user(
            user_id,
            command,
            academy_id=academy_id,
        )
        if updated is None:
            raise UserNotFound("user not found")
        return updated
