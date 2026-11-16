"""Send the "verify your email" message for public parent self-registration.

The frontend used to call Firebase's client-side ``sendEmailVerification``
directly, which delivers from Firebase's shared, unbranded mailer
(``noreply@<project>.firebaseapp.com``) and lands in spam at a high rate —
confirmed against production. This use case instead generates the same
Firebase verification link server-side (Admin SDK) and sends it through our
own Resend domain, matching the pattern ``send_login_invite.py`` already
uses successfully for admin-created accounts.

Moving the send onto our own domain also moves the *abuse* onto our own domain.
The caller is unauthenticated apart from a Firebase ID token, and anybody can
mint a Firebase account for an address they do not own using the public web API
key — so the address in the token is attacker-chosen, and every message sent
here spends the reputation of the domain our invoices go out on. Hence the
per-address cooldown below, which the IP rate limit cannot substitute for: a
mail bomb aimed at one victim is a *recipient*-side limit, not a source-side
one.
"""

from __future__ import annotations

from html import escape
from typing import Protocol

from backend.v2.contexts.identity.application.ports import (
    TokenVerifier,
    UserRepository,
    VerificationEmailCooldownPort,
)
from backend.v2.contexts.identity.application.use_cases.send_login_invite import (
    AcademyBrandLookup,
    AcademyPortalUrlLookup,
    InviteEmailOutcome,
    InviteEmailPort,
    PasswordResetLinkPort,
    resolve_email_brand,
)
from backend.v2.contexts.identity.application.use_cases.send_password_reset_email import (
    password_reset_body,
)
from backend.v2.contexts.identity.domain.errors import (
    InvalidToken,
    LoginInviteSendFailed,
    VerificationEmailThrottled,
)
from backend.v2.shared.comms.email_brand import branded_as
from backend.v2.shared.comms.email_theme import INK, MUTED, EmailBrand, button, shell
from backend.v2.shared.http.errors import DomainError


class EmailVerificationLinkPort(Protocol):
    async def generate_email_verification_link(
        self, email: str, *, portal_url: str | None = None
    ) -> str: ...


class AcademyNameLookup(Protocol):
    async def get_academy_name(self, academy_id: str) -> str | None: ...


def _verification_body(
    *, academy_name: str, verify_link: str, brand: EmailBrand | None = None
) -> str:
    safe_academy_name = escape(academy_name)
    inner = (
        f'<h2 style="color:{INK};font-size:20px;margin:0 0 12px;">'
        f"Confirm your email for {safe_academy_name}</h2>"
        f"<p>Thanks for registering. Confirm your email address to finish setting up "
        f"your account and enroll your child.</p>"
        f'<p style="margin:24px 0;">{button("Verify email address", verify_link)}</p>'
        f'<p style="color:{MUTED};font-size:13px;">If you didn&rsquo;t request this, '
        f"you can ignore this email.</p>"
    )
    return shell(brand=branded_as(brand, academy_name), inner_html=inner)


class SendRegistrationVerificationEmail:
    def __init__(
        self,
        *,
        verifier: TokenVerifier,
        links: EmailVerificationLinkPort,
        sender: InviteEmailPort,
        academies: AcademyNameLookup,
        cooldown: VerificationEmailCooldownPort,
        users: UserRepository,
        password_links: PasswordResetLinkPort,
        brands: AcademyBrandLookup | None = None,
        portals: AcademyPortalUrlLookup | None = None,
    ) -> None:
        self._portals = portals
        self._users = users
        self._password_links = password_links
        self._verifier = verifier
        self._links = links
        self._sender = sender
        self._academies = academies
        self._cooldown = cooldown
        self._brands = brands

    async def execute(self, id_token: str, *, academy_id: str) -> None:
        token_claims = await self._verify(id_token)

        # The address is read from the verified token, never from the request
        # body: a body-supplied address would let any caller aim our mailer at
        # anyone without even creating a Firebase account first.
        email = token_claims.get("email")
        if not isinstance(email, str) or not email:
            raise InvalidToken("token missing email")
        uid = token_claims.get("uid") or token_claims.get("sub")
        if not isinstance(uid, str) or not uid:
            raise InvalidToken("token missing uid")
        display_name = token_claims.get("name")
        if not isinstance(display_name, str) or not display_name.strip():
            display_name = email

        # Claimed before anything is generated or sent, so a caller cannot
        # burn Firebase link quota or provider calls past the budget either.
        if not await self._cooldown.claim_send(email):
            raise VerificationEmailThrottled(
                "A verification email was already sent to this address recently. "
                "Check your inbox and spam folder, then try again in a few minutes."
            )

        try:
            # Re-hosted on the academy's own /auth/action page so the parent
            # can verify from any browser and continue to that academy's login.
            portal_url = (
                await self._portals.get_academy_portal_url(academy_id) if self._portals else None
            )
            # An address we already hold (a roster parent who never activated)
            # gets the set-password mail, never "verify": whoever created this
            # Firebase account may not own the mailbox, and verifying it would
            # hand them the parent's account.
            existing = await self._users.get_by_email(email)
            if existing is not None:
                link = await self._password_links.generate_password_reset_link(
                    email,
                    uid=existing.user_id,
                    display_name=existing.display_name,
                    portal_url=portal_url,
                )
            else:
                link = await self._links.generate_email_verification_link(
                    email, portal_url=portal_url
                )
            academy_name = await self._academies.get_academy_name(academy_id) or "your academy"
        except Exception as exc:
            raise LoginInviteSendFailed(f"could not prepare verification email: {exc}") from exc

        brand = await resolve_email_brand(self._brands, academy_id, academy_name=academy_name)
        if existing is not None:
            subject = f"Set your password for {academy_name}"
            body = password_reset_body(academy_name=academy_name, reset_link=link, brand=brand)
        else:
            subject = f"Verify your email for {academy_name}"
            body = _verification_body(academy_name=academy_name, verify_link=link, brand=brand)
        outcome: InviteEmailOutcome = await self._sender.send_invite_email(
            user_id=existing.user_id if existing is not None else uid,
            email=email,
            display_name=display_name,
            subject=subject,
            body=body,
        )
        if not outcome.ok:
            raise LoginInviteSendFailed(outcome.failed_reason or "send failed")

    async def _verify(self, id_token: str) -> dict[str, object]:
        """Verify the bearer token, mapping *only* genuine token failures to 401.

        A blanket ``except Exception`` here would rewrite a Firebase outage —
        which the verifier surfaces as a 5xx ``HTTPException`` — into "your
        login is invalid", sending the parent off to re-authenticate against a
        service that is down and hiding the incident from the error budget.
        Anything that already carries an HTTP ``status_code`` — a ``DomainError``
        or a Starlette ``HTTPException`` — has had its status chosen
        deliberately by whoever raised it, so it is re-raised untouched. The
        check is duck-typed rather than an ``except HTTPException`` so this
        application-layer module stays free of a web-framework import. Anything
        else really is an unparseable or rejected token.
        """
        try:
            claims = await self._verifier.verify(id_token)
        except Exception as exc:
            if isinstance(exc, DomainError) or getattr(exc, "status_code", None) is not None:
                raise
            raise InvalidToken(str(exc)) from exc
        return dict(claims)
