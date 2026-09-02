"""Send a 'set your password' login invite to an admin-created user.

Used for parents (and others) who do not use Google sign-in: the admin
provisions the Firebase account, then this use case emails a Firebase
password-reset link so the user chooses their own password. Completing
the link also marks the Firebase email verified, which the password
login path requires.
"""

from __future__ import annotations

from datetime import UTC, datetime
from html import escape
from typing import Protocol

from pydantic import BaseModel

from backend.v2.contexts.identity.application.use_cases.admin_directory import (
    AdminUserDetail,
)
from backend.v2.contexts.identity.domain.errors import (
    LoginInviteSendFailed,
    UserNotFound,
)
from backend.v2.shared.comms.email_theme import INK, MUTED, EmailBrand, button, shell


class PasswordResetLinkPort(Protocol):
    async def generate_password_reset_link(
        self,
        email: str,
        *,
        uid: str | None = None,
        display_name: str | None = None,
        portal_url: str | None = None,
    ) -> str: ...


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


class AcademyPortalUrlLookup(Protocol):
    """Resolves an academy's own portal origin, e.g.
    ``https://blno-academy.courtmastr.com``.

    Per ADR-0007 the tenant is resolved from the request host, so an invite
    must link to *that* academy's host — not the deployment-wide
    ``FRONTEND_URL``, which points at a generic default and would land the
    parent in the wrong tenant (or one that resolves to no tenant at all).
    Composition owns the slug→URL rewrite so this context stays free of
    deployment settings.
    """

    async def get_academy_portal_url(self, academy_id: str) -> str | None: ...


class LoginInviteResult(BaseModel):
    model_config = {"frozen": True}

    sent_at: datetime


def _invite_body(*, display_name: str, academy_name: str, reset_link: str) -> str:
    safe_display_name = escape(display_name)
    safe_academy_name = escape(academy_name)
    inner = (
        f'<h2 style="color:{INK};font-size:20px;margin:0 0 12px;">'
        f"Your {safe_academy_name} account is ready</h2>"
        f"<p>Hi {safe_display_name},</p>"
        f"<p>Your account at <strong>{safe_academy_name}</strong> has been set up. Set your "
        f"password to log in, see your children's enrollment, and make payments.</p>"
        f'<p style="margin:24px 0;">{button("Set your password", reset_link)}</p>'
        f'<p style="color:{MUTED};font-size:13px;">This link expires after a short time. '
        f"If it has expired, ask your academy to send a new one, or use "
        f"&ldquo;Forgot password&rdquo; on the login page with this email address.</p>"
    )
    return shell(brand=EmailBrand(academy_name=academy_name), inner_html=inner)


class SendLoginInvite:
    def __init__(
        self,
        *,
        users: LoginInviteRecorder,
        links: PasswordResetLinkPort,
        sender: InviteEmailPort,
        academies: AcademyNameLookup,
        portals: AcademyPortalUrlLookup | None = None,
    ) -> None:
        self._users = users
        self._links = links
        self._sender = sender
        self._academies = academies
        self._portals = portals

    async def execute(self, user_id: str, *, academy_id: str) -> LoginInviteResult:
        user = await self._users.get_admin_user(user_id, academy_id=academy_id)
        if user is None:
            raise UserNotFound(user_id)

        try:
            portal_url = (
                await self._portals.get_academy_portal_url(academy_id)
                if self._portals is not None
                else None
            )
            reset_link = await self._links.generate_password_reset_link(
                str(user.email),
                uid=user.user_id,
                display_name=user.display_name,
                portal_url=portal_url,
            )
            academy_name = await self._academies.get_academy_name(academy_id) or "your academy"
        except Exception as exc:
            raise LoginInviteSendFailed(f"could not prepare invite: {exc}") from exc

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
