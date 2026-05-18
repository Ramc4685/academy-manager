"""Public parent registration use case.

Firebase proves identity. This use case only bootstraps the lowest-privilege
Mongo authorization row required for a parent to begin onboarding.
"""

from __future__ import annotations

from backend.v2.contexts.identity.application.ports import (
    PublicParentRegistrationRepository,
    TokenVerifier,
)
from backend.v2.contexts.identity.domain.errors import InvalidToken, UserInactive
from backend.v2.contexts.identity.domain.models import User


class RegisterPublicParent:
    def __init__(
        self,
        *,
        verifier: TokenVerifier,
        users: PublicParentRegistrationRepository,
    ) -> None:
        self._verifier = verifier
        self._users = users

    async def execute(self, id_token: str) -> User:
        try:
            token_claims = await self._verifier.verify(id_token)
        except Exception as exc:
            raise InvalidToken(str(exc)) from exc

        email = token_claims.get("email")
        if not isinstance(email, str) or not email:
            raise InvalidToken("token missing email")

        uid = token_claims.get("uid") or token_claims.get("sub")
        if not isinstance(uid, str) or not uid:
            raise InvalidToken("token missing uid")

        display_name = token_claims.get("name")
        if not isinstance(display_name, str) or not display_name.strip():
            display_name = email

        existing = await self._users.get_by_email(email)
        if existing is not None and not existing.is_active:
            raise UserInactive(f"user {existing.user_id} disabled")

        return await self._users.ensure_parent_user(
            email=email,
            display_name=display_name.strip(),
            firebase_uid=uid,
        )
