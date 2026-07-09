"""Send a 'set your password' login invite to an admin-created user.

Used for parents (and others) who do not use Google sign-in: the admin
provisions the Firebase account, then this use case emails a Firebase
password-reset link so the user chooses their own password. Completing
the link also marks the Firebase email verified, which the password
login path requires.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

from pydantic import BaseModel

from backend.v2.contexts.identity.application.use_cases.admin_directory import (
    AdminUserDetail,
)
from backend.v2.contexts.identity.domain.errors import (
    LoginInviteSendFailed,
    UserNotFound,
)


class PasswordResetLinkPort(Protocol):
    async def generate_password_reset_link(self, email: str) -> str: ...


class InviteEmailOutcome(BaseModel):
    """Outcome of a single login-invite email send attempt.

    Identity-local mirror of the communications context's `SendOutcome`,
    kept separate so this context does not import another bounded context.
    """

    model_config = {"frozen": True}

    ok: bool
    failed_reason: str | None = None


class InviteEmailPort(Protocol):
    """Outbound email port for login invites, owned by the identity context."""

    async def send_invite_email(
        self,
        *,
        user_id: str,
        email: str,
        display_name: str,
        subject: str,
        body: str,
    ) -> InviteEmailOutcome: ...


class LoginInviteRecorder(Protocol):
    async def get_admin_user(self, user_id: str, *, academy_id: str) -> AdminUserDetail | None: ...

    async def record_login_invite(
        self, user_id: str, *, academy_id: str, sent_at: datetime
    ) -> None: ...


class AcademyNameLookup(Protocol):
    async def get_academy_name(self, academy_id: str) -> str | None: ...


class LoginInviteResult(BaseModel):
    model_config = {"frozen": True}

    sent_at: datetime


def _invite_body(*, display_name: str, academy_name: str, reset_link: str) -> str:
    return f"""
<div style="font-family: -apple-system, 'Segoe UI', sans-serif; max-width: 520px; margin: 0 auto;">
  <h2 style="color: #0a0f1c;">Your {academy_name} account is ready</h2>
  <p>Hi {display_name},</p>
  <p>Your account at <strong>{academy_name}</strong> has been set up. Set your
  password to log in, see your children's enrollment, and make payments.</p>
  <p style="margin: 24px 0;">
    <a href="{reset_link}"
       style="background: #2545d3; color: #ffffff; padding: 12px 20px;
              border-radius: 8px; text-decoration: none; font-weight: 600;">
      Set your password
    </a>
  </p>
  <p style="color: #64748b; font-size: 13px;">This link expires after a short
  time. If it has expired, ask your academy to send a new one, or use
  &ldquo;Forgot password&rdquo; on the login page with this email address.</p>
</div>
"""


class SendLoginInvite:
    def __init__(
        self,
        *,
        users: LoginInviteRecorder,
        links: PasswordResetLinkPort,
        sender: InviteEmailPort,
        academies: AcademyNameLookup,
    ) -> None:
        self._users = users
        self._links = links
        self._sender = sender
        self._academies = academies

    async def execute(self, user_id: str, *, academy_id: str) -> LoginInviteResult:
        user = await self._users.get_admin_user(user_id, academy_id=academy_id)
        if user is None:
            raise UserNotFound(user_id)

        reset_link = await self._links.generate_password_reset_link(str(user.email))
        academy_name = await self._academies.get_academy_name(academy_id) or "your academy"

        outcome = await self._sender.send_invite_email(
            user_id=user.user_id,
            email=str(user.email),
            display_name=user.display_name,
            subject=f"Set your password for {academy_name}",
            body=_invite_body(
                display_name=user.display_name,
                academy_name=academy_name,
                reset_link=reset_link,
            ),
        )
        if not outcome.ok:
            raise LoginInviteSendFailed(outcome.failed_reason or "send failed")

        sent_at = datetime.now(UTC)
        await self._users.record_login_invite(user.user_id, academy_id=academy_id, sent_at=sent_at)
        return LoginInviteResult(sent_at=sent_at)
