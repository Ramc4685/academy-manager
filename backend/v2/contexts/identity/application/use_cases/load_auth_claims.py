"""Bridge a verified Firebase token + resolved tenant into AuthClaims.

The auth middleware calls this on every authenticated request after
``TenantResolver`` has resolved the academy from domain/subdomain (per
ADR-0007). The resulting ``AuthClaims`` drive both role enforcement
(``require_persona``) and tenant scope (``TenancyMiddleware``).

SaaS contract:

* Tenant is ALWAYS passed in by the caller. The use case never falls back
  to ``user.academy_id`` or ``settings.default_academy_id``.
* The user must have an **active** ``academy_memberships`` row for the
  resolved academy. Missing or inactive memberships raise
  ``MembershipNotFound`` (403).
* Platform roles are loaded from ``platform_roles`` separately from
  academy-scoped roles, so role guards stay tenant-isolated.
"""

from __future__ import annotations

from backend.v2.contexts.identity.application.ports import (
    MembershipLookup,
    PlatformRoleRepository,
    TokenVerifier,
    UserRepository,
)
from backend.v2.contexts.identity.domain.errors import (
    InvalidToken,
    MembershipNotFound,
    UserInactive,
    UserNotFound,
)
from backend.v2.shared.auth.claims import AuthClaims, PlatformRoleName


class LoadAuthClaims:
    def __init__(
        self,
        verifier: TokenVerifier,
        users: UserRepository,
        memberships: MembershipLookup,
        platform_roles: PlatformRoleRepository,
    ) -> None:
        self._verifier = verifier
        self._users = users
        self._memberships = memberships
        self._platform_roles = platform_roles

    async def execute(self, id_token: str, *, resolved_academy_id: str) -> AuthClaims:
        """Verify token, resolve identity, validate membership, build claims.

        ``resolved_academy_id`` MUST come from ``TenantResolver`` (subdomain,
        custom domain, or approved internal header). The use case never
        infers tenant from the user.
        """
        if not resolved_academy_id:
            # Defensive: middleware should never pass an empty tenant.
            # We refuse explicitly rather than risk a default_academy_id-style
            # implicit fallback elsewhere in the call graph.
            raise MembershipNotFound(
                "resolved_academy_id is required; SaaS auth has no default tenant"
            )

        try:
            token_claims = await self._verifier.verify(id_token)
        except Exception as exc:  # firebase raises various subclasses
            raise InvalidToken(str(exc)) from exc

        email = token_claims.get("email")
        if not isinstance(email, str) or not email:
            raise InvalidToken("token missing email")
        _require_verified_password_provider_email(token_claims)

        user = await self._users.get_by_email(email)
        if user is None:
            raise UserNotFound(f"no user for email {email}")
        if not _user_is_active(user):
            raise UserInactive(f"user {user.user_id} disabled")

        membership = await self._memberships.get_for_user_in_academy(
            user_id=user.user_id, academy_id=resolved_academy_id
        )
        if membership is None or not membership.is_active():
            raise MembershipNotFound(
                f"user {user.user_id} has no active membership in {resolved_academy_id}"
            )

        platform_grants = await self._platform_roles.list_active_for_user(user.user_id)
        platform_role_names: tuple[PlatformRoleName, ...] = tuple(
            grant.role for grant in platform_grants if grant.is_active()
        )

        return AuthClaims(
            user_id=user.user_id,
            email=str(user.email),
            academy_id=resolved_academy_id,
            membership_id=membership.membership_id,
            roles=membership.roles,
            platform_roles=platform_role_names,
        )


def _user_is_active(user) -> bool:
    """Treat the SaaS ``global_status`` as canonical, but accept the legacy
    ``is_active`` flag for users still produced by single-tenant repos."""
    global_status = getattr(user, "global_status", None)
    if global_status is not None:
        return global_status == "active"
    return bool(getattr(user, "is_active", True))


def _require_verified_password_provider_email(token_claims: dict[str, object]) -> None:
    firebase_claims = token_claims.get("firebase")
    provider = None
    if isinstance(firebase_claims, dict):
        provider = firebase_claims.get("sign_in_provider")
    if provider == "password" and token_claims.get("email_verified") is not True:
        raise InvalidToken("email must be verified")
