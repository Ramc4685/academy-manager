"""Bridge a verified Firebase token into request-scoped AuthClaims.

The auth middleware calls this on every authenticated request; the resulting
AuthClaims drive both role enforcement (`require_persona`) and tenant scope
(`TenancyMiddleware`).
"""

from __future__ import annotations

from backend.v2.contexts.identity.application.ports import TokenVerifier, UserRepository
from backend.v2.contexts.identity.domain.errors import InvalidToken, UserInactive, UserNotFound
from backend.v2.shared.auth.claims import AuthClaims


class LoadAuthClaims:
    def __init__(self, verifier: TokenVerifier, users: UserRepository) -> None:
        self._verifier = verifier
        self._users = users

    async def execute(self, id_token: str) -> AuthClaims:
        try:
            token_claims = await self._verifier.verify(id_token)
        except Exception as exc:  # firebase raises various subclasses
            raise InvalidToken(str(exc)) from exc

        email = token_claims.get("email")
        if not isinstance(email, str) or not email:
            raise InvalidToken("token missing email")

        user = await self._users.get_by_email(email)
        if user is None:
            raise UserNotFound(f"no user for email {email}")
        if not user.is_active:
            raise UserInactive(f"user {user.user_id} disabled")

        return AuthClaims(
            user_id=user.user_id,
            email=user.email,
            academy_id=user.academy_id,
            roles=user.roles,
        )
