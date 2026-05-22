"""Admin role-change use case."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field

from backend.v2.contexts.identity.application.use_cases.admin_directory import (
    AdminUserSummary,
)
from backend.v2.contexts.identity.domain.errors import UserNotFound
from backend.v2.contexts.identity.domain.models import Role


class AdminRoleWriter(Protocol):
    async def change_role(
        self,
        user_id: str,
        role: Role,
        *,
        academy_id: str,
        actor_id: str,
        reason: str,
    ) -> AdminUserSummary | None: ...


class ChangeUserRoleCommand(BaseModel):
    model_config = {"frozen": True}

    role: Role
    actor_id: str = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=500)


class ChangeUserRole:
    def __init__(self, users: AdminRoleWriter) -> None:
        self._users = users

    async def execute(
        self,
        user_id: str,
        command: ChangeUserRoleCommand,
        *,
        academy_id: str,
    ) -> AdminUserSummary:
        updated = await self._users.change_role(
            user_id,
            command.role,
            academy_id=academy_id,
            actor_id=command.actor_id,
            reason=command.reason,
        )
        if updated is None:
            raise UserNotFound("user not found")
        return updated
