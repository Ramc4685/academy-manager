"""Provision a Firebase-backed login for a roster parent before inviting them."""

from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field

from backend.v2.contexts.identity.application.ports import ParentLoginProvisioner


class ProvisionParentLoginCommand(BaseModel):
    model_config = {"frozen": True}

    parent_id: str = Field(min_length=1, max_length=128)
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=120)
    actor_id: str = Field(min_length=1, max_length=128)


class ProvisionParentLogin:
    def __init__(self, parents: ParentLoginProvisioner) -> None:
        self._parents = parents

    async def execute(self, command: ProvisionParentLoginCommand, *, academy_id: str) -> str:
        return await self._parents.ensure_parent_login(
            parent_id=command.parent_id,
            email=str(command.email),
            display_name=command.display_name,
            academy_id=academy_id,
            actor_id=command.actor_id,
        )
