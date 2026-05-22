"""Admin role-change use case."""

from __future__ import annotations

from typing import Protocol

from backend.v2.contexts.identity.application.use_cases.admin_directory import (
    AdminUserSummary,
)
from backend.v2.contexts.identity.domain.errors import UserNotFound
from backend.v2.contexts.identity.domain.models import Role


class AdminRoleWriter(Protocol):
    async def change_role(
        self, user_id: str, role: Role, *, academy_id: str
    ) -> AdminUserSummary | None: ...


class ChangeUserRole:
    def __init__(self, users: AdminRoleWriter) -> None:
        self._users = users

    async def execute(self, user_id: str, role: Role, *, academy_id: str) -> AdminUserSummary:
        updated = await self._users.change_role(user_id, role, academy_id=academy_id)
        if updated is None:
            raise UserNotFound("user not found")
        return updated
