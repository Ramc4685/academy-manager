"""Admin identity directory use cases."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel, EmailStr, Field

from backend.v2.contexts.identity.domain.models import Role

logger = logging.getLogger(__name__)


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
    session_count: int = 0
    login_invite_sent_at: datetime | None = None


class CreateAdminUserCommand(BaseModel):
    model_config = {"frozen": True}

    role: Role
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=120)
    phone: str | None = Field(default=None, max_length=40)
    actor_id: str = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=500)


class UpdateAdminUserCommand(BaseModel):
    model_config = {"frozen": True}

    email: EmailStr | None = None
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


class AdminUserCreator(Protocol):
    async def create_admin_user(
        self,
        command: CreateAdminUserCommand,
        *,
        academy_id: str,
    ) -> AdminUserDetail: ...


class LoginInviteOutcome(BaseModel):
    """Whether an email edit triggered a fresh login invite, and how it went.

    Firebase clears `email_verified` whenever an account's email changes
    (`FirebaseAdminAdapter.update_user_email`), and `load_auth_claims`
    rejects password-provider tokens with an unverified email — so an admin
    correcting a typo locks the parent out until they complete a new
    set-password link. We send that link automatically; this outcome is what
    tells the admin whether it actually went out (issue #436).
    """

    model_config = {"frozen": True}

    status: Literal["not_needed", "sent", "failed"]
    sent_at: datetime | None = None
    error: str | None = None


class UpdateAdminUserResult(BaseModel):
    model_config = {"frozen": True}

    user: AdminUserDetail
    login_invite: LoginInviteOutcome


class LoginInviteDispatcher(Protocol):
    """Narrow view of `SendLoginInvite` so this module stays decoupled."""

    async def execute(self, user_id: str, *, academy_id: str) -> object: ...


class ListAdminUsers:
    def __init__(self, users: AdminUserDirectoryQuery) -> None:
        self._users = users

    async def execute(
        self,
        role: Literal["admin", "coach", "parent", "owner"] | None = None,
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


class CreateAdminUser:
    def __init__(self, users: AdminUserCreator) -> None:
        self._users = users

    async def execute(
        self,
        command: CreateAdminUserCommand,
        *,
        academy_id: str,
    ) -> AdminUserDetail:
        return await self._users.create_admin_user(command, academy_id=academy_id)


def _same_email(left: str | None, right: str | None) -> bool:
    return (left or "").strip().lower() == (right or "").strip().lower()


class UpdateAdminUser:
    """Edit an admin-visible user, re-inviting them when their email moves.

    Changing the email in Firebase clears `email_verified`, which locks a
    password-login user out until they complete a fresh set-password link.
    So when (and only when) the address actually changes, we send one login
    invite through the existing `SendLoginInvite` path. A failed send is
    reported back to the caller rather than swallowed — the edit itself has
    already committed, so failing the whole request would be a lie in the
    other direction (issue #436).
    """

    def __init__(
        self,
        users: AdminUserWriter,
        *,
        reader: AdminUserDetailQuery | None = None,
        invites: LoginInviteDispatcher | None = None,
    ) -> None:
        self._users = users
        self._reader = reader
        self._invites = invites

    async def execute(
        self,
        user_id: str,
        command: UpdateAdminUserCommand,
        *,
        academy_id: str,
    ) -> UpdateAdminUserResult:
        from backend.v2.contexts.identity.domain.errors import UserNotFound

        before: AdminUserDetail | None = None
        if command.email is not None and self._reader is not None:
            before = await self._reader.get_admin_user(user_id, academy_id=academy_id)

        updated = await self._users.update_admin_user(
            user_id,
            command,
            academy_id=academy_id,
        )
        if updated is None:
            raise UserNotFound("user not found")

        invite = await self._maybe_reinvite(before, updated, academy_id=academy_id)
        return UpdateAdminUserResult(user=updated, login_invite=invite)

    async def _maybe_reinvite(
        self,
        before: AdminUserDetail | None,
        updated: AdminUserDetail,
        *,
        academy_id: str,
    ) -> LoginInviteOutcome:
        not_needed = LoginInviteOutcome(status="not_needed")
        if self._invites is None or before is None:
            return not_needed
        if _same_email(str(before.email), str(updated.email)):
            return not_needed

        try:
            result = await self._invites.execute(updated.user_id, academy_id=academy_id)
        except Exception as exc:
            logger.exception(
                "re-invite after email change failed for %s",
                updated.user_id,
            )
            return LoginInviteOutcome(status="failed", error=str(exc) or exc.__class__.__name__)
        sent_at = getattr(result, "sent_at", None)
        return LoginInviteOutcome(
            status="sent",
            sent_at=sent_at if isinstance(sent_at, datetime) else None,
        )
