"""Admin identity directory use cases."""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, EmailStr

from backend.v2.contexts.identity.domain.models import Role


class AdminUserSummary(BaseModel):
    model_config = {"frozen": True}

    user_id: str
    email: EmailStr
    display_name: str
    role: Role
    status: str


class AdminUserDirectoryQuery(Protocol):
    async def list_users(
        self, role: Role | None = None, academy_id: str | None = None
    ) -> list[AdminUserSummary]: ...


class ListAdminUsers:
    def __init__(self, users: AdminUserDirectoryQuery) -> None:
        self._users = users

    async def execute(
        self,
        role: Literal["admin", "coach", "parent"] | None = None,
        academy_id: str | None = None,
    ) -> list[AdminUserSummary]:
        return await self._users.list_users(role, academy_id=academy_id)
