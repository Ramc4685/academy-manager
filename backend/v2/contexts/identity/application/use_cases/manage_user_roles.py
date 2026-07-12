"""Additive role management for the admin directory.

Unlike ``ChangeUserRole`` (which replaces all roles with one), these use
cases add/remove a single role while preserving the rest, updating both
the legacy ``users`` doc and the ``academy_memberships`` source of truth.
"""

from typing import Protocol

from pydantic import BaseModel, Field

from backend.v2.contexts.identity.application.use_cases.admin_directory import (
    AdminUserDetail,
)
from backend.v2.contexts.identity.domain.errors import UserNotFound
from backend.v2.contexts.identity.domain.models import Role


class ModifyUserRoleCommand(BaseModel):
    model_config = {"frozen": True}

    role: Role
    actor_id: str = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=500)


class AdminRoleModifier(Protocol):
    async def add_role(
        self, user_id: str, role: Role, *, academy_id: str, actor_id: str, reason: str
    ) -> AdminUserDetail | None: ...

    async def remove_role(
        self, user_id: str, role: Role, *, academy_id: str, actor_id: str, reason: str
    ) -> AdminUserDetail | None: ...


class AddUserRole:
    def __init__(self, users: AdminRoleModifier) -> None:
        self._users = users

    async def execute(
        self, user_id: str, command: ModifyUserRoleCommand, *, academy_id: str
    ) -> AdminUserDetail:
        result = await self._users.add_role(
            user_id,
            command.role,
            academy_id=academy_id,
            actor_id=command.actor_id,
            reason=command.reason,
        )
        if result is None:
            raise UserNotFound(user_id)
        return result


class RemoveUserRole:
    def __init__(self, users: AdminRoleModifier) -> None:
        self._users = users

    async def execute(
        self, user_id: str, command: ModifyUserRoleCommand, *, academy_id: str
    ) -> AdminUserDetail:
        result = await self._users.remove_role(
            user_id,
            command.role,
            academy_id=academy_id,
            actor_id=command.actor_id,
            reason=command.reason,
        )
        if result is None:
            raise UserNotFound(user_id)
        return result
