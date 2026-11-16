"""Send the "forgot password" email through our own branded sender.

The login page used to call Firebase's client ``sendPasswordResetEmail``, which
mails from Firebase's shared ``firebaseapp.com`` sender (the one already seen
landing in spam for verification mail) and lands on Firebase's generic page.
This generates the same reset link server-side, re-hosted on the academy's own
``/auth/action`` page, and sends it the way ``SendLoginInvite`` does.

The caller is anonymous, so the use case never says whether the address is
known: unknown addresses, throttled mailboxes and send failures all return the
same way. Only an address with an active membership in *this* academy gets a
mail, so the endpoint cannot be used to mail arbitrary people under our name.
A roster parent who never activated has no Firebase account yet; the link port
provisions one (as the admin invite does), so this doubles as "email me a link
to set my password".
"""

from __future__ import annotations

import logging
from html import escape

from backend.v2.contexts.identity.application.ports import (
    MembershipLookup,
    UserRepository,
    VerificationEmailCooldownPort,
)
from backend.v2.contexts.identity.application.use_cases.send_login_invite import (
    AcademyBrandLookup,
    AcademyNameLookup,
    AcademyPortalUrlLookup,
    InviteEmailPort,
    PasswordResetLinkPort,
    resolve_email_brand,
)
from backend.v2.contexts.identity.domain.identity_aliases import identity_aliases
from backend.v2.shared.comms.email_brand import branded_as
from backend.v2.shared.comms.email_theme import INK, MUTED, EmailBrand, button, shell

logger = logging.getLogger(__name__)


def password_reset_body(
    *, academy_name: str, reset_link: str, brand: EmailBrand | None = None
) -> str:
    safe_academy_name = escape(academy_name)
    inner = (
        f'<h2 style="color:{INK};font-size:20px;margin:0 0 12px;">'
        f"Set your {safe_academy_name} password</h2>"
        f"<p>We got a request to set or reset the password for your account. "
        f"Choose a new password to sign in.</p>"
        f'<p style="margin:24px 0;">{button("Set your password", reset_link)}</p>'
        f'<p style="color:{MUTED};font-size:13px;">This link expires after a short time. '
        f"If you didn&rsquo;t ask for this, you can ignore this email; your password "
        f"stays the same.</p>"
    )
    return shell(brand=branded_as(brand, academy_name), inner_html=inner)


class SendPasswordResetEmail:
    def __init__(
        self,
        *,
        users: UserRepository,
        memberships: MembershipLookup,
        links: PasswordResetLinkPort,
        sender: InviteEmailPort,
        academies: AcademyNameLookup,
        cooldown: VerificationEmailCooldownPort,
        portals: AcademyPortalUrlLookup | None = None,
        brands: AcademyBrandLookup | None = None,
    ) -> None:
        self._users = users
        self._memberships = memberships
        self._links = links
        self._sender = sender
        self._academies = academies
        self._cooldown = cooldown
        self._portals = portals
        self._brands = brands

    async def execute(self, email: str, *, academy_id: str) -> None:
        """Send the reset mail if ``email`` belongs here. Always returns None."""
        email = email.strip()
        if not email or "@" not in email or not academy_id:
            return
        user = await self._users.get_by_email(email)
        if user is None:
            return
        membership = await self._memberships.get_for_user_in_academy(
            user_id=user.user_id,
            academy_id=academy_id,
            aliases=identity_aliases(user.user_id, user.firebase_uid, user.auth_uid),
        )
        if membership is None or not membership.is_active():
            return
        # Claimed before any link or provider call, so a caller cannot spend
        # Firebase quota or our sender reputation past the per-mailbox budget.
        if not await self._cooldown.claim_send(str(user.email)):
            return
        try:
            portal_url = (
                await self._portals.get_academy_portal_url(academy_id) if self._portals else None
            )
            reset_link = await self._links.generate_password_reset_link(
                str(user.email),
                uid=user.user_id,
                display_name=user.display_name,
                portal_url=portal_url,
            )
            academy_name = await self._academies.get_academy_name(academy_id) or "your academy"
            brand = await resolve_email_brand(self._brands, academy_id, academy_name=academy_name)
            outcome = await self._sender.send_invite_email(
                user_id=user.user_id,
                email=str(user.email),
                display_name=user.display_name,
                subject=f"Set your password for {academy_name}",
                body=password_reset_body(
                    academy_name=academy_name, reset_link=reset_link, brand=brand
                ),
            )
        except Exception:
            logger.exception("password reset email for user %s failed", user.user_id)
            return
        if not outcome.ok:
            logger.error(
                "password reset email for user %s not sent: %s",
                user.user_id,
                outcome.failed_reason,
            )
