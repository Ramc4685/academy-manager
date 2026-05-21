"""Identity application ports (Protocols implemented by infrastructure)."""

from __future__ import annotations

from typing import Protocol

from backend.v2.contexts.identity.domain.models import (
    AcademyMembership,
    PlatformRole,
    User,
)


class UserRepository(Protocol):
    """Read/write port for User aggregates.

    The Mongo implementation in `infrastructure/mongo_user_repo.py` extends
    `TenantScopedRepository` so it automatically filters by `academy_id`.
    """

    async def get_by_email(self, email: str) -> User | None: ...
    async def get_by_id(self, user_id: str) -> User | None: ...


class PublicParentRegistrationRepository(UserRepository, Protocol):
    """Write port for first-time parent self-registration."""

    async def ensure_parent_user(
        self, *, email: str, display_name: str, firebase_uid: str
    ) -> User: ...


class TokenVerifier(Protocol):
    """Verifies a Firebase ID token and returns a dict of claims.

    Implementation lives in `infrastructure/firebase_token_verifier.py`. A
    test fake implements this to avoid hitting Firebase in unit tests.
    """

    async def verify(self, id_token: str) -> dict[str, object]: ...


class MembershipRepository(Protocol):
    """Read port for `academy_memberships`.

    SaaS `LoadAuthClaims` uses this to verify the authenticated user has an
    active membership for the resolved academy. The Mongo implementation
    lives in `infrastructure/mongo_membership_repo.py` (owned by Agent A).
    """

    async def get_for_user_in_academy(
        self, *, user_id: str, academy_id: str
    ) -> AcademyMembership | None:
        """Return the membership row for `(academy_id, user_id)` or None."""
        ...


class PlatformRoleRepository(Protocol):
    """Read port for `platform_roles`.

    Cross-tenant capabilities (e.g. `platform_admin`) are loaded from this
    port and carried on `AuthClaims.platform_roles` separately from
    academy-scoped roles.
    """

    async def list_active_for_user(self, user_id: str) -> list[PlatformRole]:
        """Return all active platform-role grants for the user."""
        ...
