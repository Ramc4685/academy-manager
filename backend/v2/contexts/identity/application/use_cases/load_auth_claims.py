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

import logging
from typing import Any

from backend.v2.contexts.identity.application.ports import (
    LoginAuditRecorder,
    MembershipLookup,
    PlatformRoleRepository,
    TokenVerifier,
    UserRepository,
)
from backend.v2.contexts.identity.application.token_claims import (
    require_verified_email,
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

logger = logging.getLogger(__name__)

# Most privileged role first: the persona stamped on a login event is the one
# the session can actually act as.
_PERSONA_PRIORITY = ("owner", "admin", "coach", "assistant_coach", "parent", "student")


class LoadAuthClaims:
    def __init__(
        self,
        verifier: TokenVerifier,
        users: UserRepository,
        memberships: MembershipLookup,
        platform_roles: PlatformRoleRepository,
        login_audit: LoginAuditRecorder | None = None,
    ) -> None:
        self._verifier = verifier
        self._users = users
        self._memberships = memberships
        self._platform_roles = platform_roles
        # Optional: composition wires the real recorder, tests and any caller
        # that only needs claims stay unchanged.
        self._login_audit = login_audit

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
        require_verified_email(token_claims)

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

        await self._record_login(
            user=user,
            academy_id=resolved_academy_id,
            membership_id=membership.membership_id,
            roles=[str(role) for role in membership.roles],
            token_claims=token_claims,
        )

        return AuthClaims(
            user_id=user.user_id,
            email=str(user.email),
            academy_id=resolved_academy_id,
            membership_id=membership.membership_id,
            roles=membership.roles,
            platform_roles=platform_role_names,
        )

    async def _record_login(
        self,
        *,
        user: User,
        academy_id: str,
        membership_id: str,
        roles: list[str],
        token_claims: dict[str, Any],
    ) -> None:
        """Leave a sign-in on the audit trail. Never fails the login.

        The token's ``iat`` makes the key stable for one session, so the
        recorder collapses the many requests a token makes into one row.
        Auditing is observability, not authorisation: a store that is down
        must not lock everyone out, so failures are logged and swallowed.
        """
        if self._login_audit is None:
            return
        try:
            await self._login_audit.record_login(
                user_id=user.user_id,
                academy_id=academy_id,
                membership_id=membership_id,
                roles=roles,
                provider=_sign_in_provider(token_claims),
                persona=_persona_for(roles),
                dedupe_key=f"{user.user_id}:{academy_id}:{token_claims.get('iat') or 'unknown'}",
            )
        except Exception:  # pragma: no cover - defensive
            logger.warning("login audit failed for user %s", user.user_id, exc_info=True)


def _sign_in_provider(token_claims: dict[str, Any]) -> str | None:
    """The Firebase sign-in method behind this token (password, google.com...)."""
    firebase = token_claims.get("firebase")
    if isinstance(firebase, dict):
        provider = firebase.get("sign_in_provider")
        if isinstance(provider, str) and provider:
            return provider
    provider = token_claims.get("sign_in_provider")
    return provider if isinstance(provider, str) and provider else None


def _persona_for(roles: list[str]) -> str | None:
    return next((role for role in _PERSONA_PRIORITY if role in roles), None)


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
