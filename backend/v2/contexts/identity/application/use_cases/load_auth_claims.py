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
from backend.v2.contexts.identity.domain.identity_aliases import identity_aliases
from backend.v2.contexts.identity.domain.models import User
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

        # The membership row may be keyed by any of this account's identity
        # aliases: `ensure_parent_login`/`ensure_student_login` keep a
        # pre-existing roster `user_id` on the users doc while keying the new
        # membership row by the provisioned `firebase_uid`. PR #400 taught the
        # login-invite path to match every alias; the login path must agree, or
        # such a parent signs in to Firebase and is then rejected here.
        # Tenant scope is untouched — `resolved_academy_id` stays mandatory.
        membership = await self._memberships.get_for_user_in_academy(
            user_id=user.user_id,
            academy_id=resolved_academy_id,
            aliases=_aliases_for(user),
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


def _aliases_for(user: User) -> tuple[str, ...]:
    """Identifiers the membership row for this account may be keyed by.

    Values are read off the already-resolved `User` record (the users doc),
    never off the token, so this can never be used to claim another
    account's membership. `auth_uid` is carried separately from
    `firebase_uid` because a record may hold a stale one alongside a newer
    one — the invite path matches all three, and so must this.
    """
    return identity_aliases(user.user_id, user.firebase_uid, user.auth_uid)


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
