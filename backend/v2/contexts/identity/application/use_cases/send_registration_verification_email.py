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

from backend.v2.contexts.identity.application.ports import TokenVerifier
from backend.v2.contexts.identity.application.use_cases.send_login_invite import (
    InviteEmailOutcome,
    InviteEmailPort,
)
from backend.v2.contexts.identity.domain.errors import (
    InvalidToken,
    LoginInviteSendFailed,
    VerificationEmailThrottled,
)
from backend.v2.shared.http.errors import DomainError


class EmailVerificationLinkPort(Protocol):
    async def generate_email_verification_link(self, email: str) -> str: ...


class AcademyNameLookup(Protocol):
    async def get_academy_name(self, academy_id: str) -> str | None: ...


class VerificationEmailCooldownPort(Protocol):
    """Per-recipient send budget. ``False`` means "throttled, do not send"."""

    async def claim_send(self, email: str) -> bool: ...


def _verification_body(*, academy_name: str, verify_link: str) -> str:
    safe_academy_name = escape(academy_name)
    safe_verify_link = escape(verify_link, quote=True)
    return f"""
<div style="font-family: -apple-system, 'Segoe UI', sans-serif; max-width: 520px; margin: 0 auto;">
  <h2 style="color: #0a0f1c;">Confirm your email for {safe_academy_name}</h2>
  <p>Thanks for registering. Confirm your email address to finish setting up
  your account and enroll your child.</p>
  <p style="margin: 24px 0;">
    <a href="{safe_verify_link}"
       style="background: #2545d3; color: #ffffff; padding: 12px 20px;
              border-radius: 8px; text-decoration: none; font-weight: 600;">
      Verify email address
    </a>
  </p>
  <p style="color: #64748b; font-size: 13px;">If you didn't request this,
  you can ignore this email.</p>
</div>
"""


class SendRegistrationVerificationEmail:
    def __init__(
        self,
        *,
        verifier: TokenVerifier,
        links: EmailVerificationLinkPort,
        sender: InviteEmailPort,
        academies: AcademyNameLookup,
        cooldown: VerificationEmailCooldownPort,
    ) -> None:
        self._verifier = verifier
        self._links = links
        self._sender = sender
        self._academies = academies
        self._cooldown = cooldown

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
            verify_link = await self._links.generate_email_verification_link(email)
            academy_name = await self._academies.get_academy_name(academy_id) or "your academy"
        except Exception as exc:
            raise LoginInviteSendFailed(f"could not prepare verification email: {exc}") from exc

        outcome: InviteEmailOutcome = await self._sender.send_invite_email(
            user_id=uid,
            email=email,
            display_name=display_name,
            subject=f"Verify your email for {academy_name}",
            body=_verification_body(academy_name=academy_name, verify_link=verify_link),
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
