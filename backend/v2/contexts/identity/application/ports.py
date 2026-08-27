"""Identity application ports (Protocols implemented by infrastructure)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from backend.v2.contexts.identity.domain.models import (
    AcademyMembership,
    MagicLinkRecord,
    PlatformRole,
    User,
)


class UserRepository(Protocol):
    """Read/write port for User aggregates."""

    async def get_by_email(self, email: str) -> User | None: ...
    async def get_by_id(self, user_id: str) -> User | None: ...
    async def get_by_firebase_uid(self, firebase_uid: str) -> User | None: ...


class ParentLoginProvisioner(Protocol):
    """Create/link the Firebase identity for an academy roster parent."""

    async def ensure_parent_login(
        self,
        *,
        parent_id: str,
        email: str,
        display_name: str,
        academy_id: str,
        actor_id: str,
    ) -> str: ...


class StudentLoginProvisioner(Protocol):
    """Create/link the Firebase identity + membership for a student login (UIM12)."""

    async def ensure_student_login(
        self,
        *,
        student_id: str,
        email: str,
        display_name: str,
        academy_id: str,
        actor_id: str,
        reason: str,
    ) -> str: ...


class PublicParentRegistrationRepository(UserRepository, Protocol):
    """Write port for first-time parent self-registration.

    ``academy_id`` is the resolved tenant the request was made against.
    The implementation MUST write that value into ``User.academy_id`` on
    first insert (legacy single-tenant field) — never the configured
    default. For an existing user, the implementation MUST NOT overwrite
    the original ``academy_id``; multi-tenant access is carried by
    ``AcademyMembership`` rows added separately by the calling use case.
    """

    async def ensure_parent_user(
        self, *, email: str, display_name: str, firebase_uid: str, academy_id: str
    ) -> User: ...


class MembershipRepository(Protocol):
    """Read/write port for academy_memberships and platform_roles.

    Intentionally NOT tenant-scoped: membership lookup happens before
    tenant context is established during auth bootstrap. Every method
    takes an explicit `academy_id` so cross-tenant leakage is impossible.
    """

    # `aliases` lists the other identifiers the same account may be keyed by
    # in `academy_memberships` (`auth_uid` / `firebase_uid`) — see
    # `domain/identity_aliases.py`. Implementations match any of them and
    # never widen the academy scope.

    async def get_membership(
        self, academy_id: str, user_id: str, *, aliases: Sequence[str] | None = None
    ) -> AcademyMembership | None: ...

    async def list_memberships_for_user(
        self, user_id: str, *, aliases: Sequence[str] | None = None
    ) -> list[AcademyMembership]: ...

    async def upsert_membership(self, membership: AcademyMembership) -> AcademyMembership: ...

    async def list_active_platform_roles(self, user_id: str) -> list[PlatformRole]: ...

    async def upsert_platform_role(self, platform_role: PlatformRole) -> PlatformRole: ...


class TokenVerifier(Protocol):
    """Verifies a Firebase ID token and returns a dict of claims.

    Implementation lives in `infrastructure/firebase_token_verifier.py`. A
    test fake implements this to avoid hitting Firebase in unit tests.
    """

    async def verify(self, id_token: str) -> dict[str, object]: ...


class MembershipLookup(Protocol):
    """Read port for `academy_memberships`.

    SaaS `LoadAuthClaims` uses this to verify the authenticated user has an
    active membership for the resolved academy. The Mongo implementation
    lives in `infrastructure/mongo_membership_repo.py` (owned by Agent A).
    """

    async def get_for_user_in_academy(
        self, *, user_id: str, academy_id: str, aliases: Sequence[str] | None = None
    ) -> AcademyMembership | None:
        """Return the membership row for `(academy_id, user_id)` or None.

        `aliases` lists the other identifiers the same account may be keyed by
        in `academy_memberships` (`auth_uid` / `firebase_uid`); implementations
        match any of them, never widening the academy scope.
        """
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


class MagicLinkRepository(Protocol):
    """Read/write port for single-use parent auto-login tokens.

    The Mongo implementation lives in
    ``infrastructure/mongo_magic_link_repo.py`` on the ``parent_magic_links``
    collection. ``get_by_hash`` is intentionally NOT academy-scoped: tenant
    binding is enforced in the consume use case by comparing the stored
    ``academy_id`` to the resolved tenant, so a lookup that silently filtered by
    tenant could not distinguish "wrong tenant" (attack) from "no such token".
    """

    async def insert(self, record: MagicLinkRecord) -> None: ...

    async def get_by_hash(self, token_hash: str) -> MagicLinkRecord | None: ...

    async def mark_used(self, token_hash: str, *, used_at: datetime) -> bool:
        """Atomically stamp ``used_at`` iff still unused.

        Returns ``True`` when this call claimed the token and ``False`` when it
        was already consumed (or gone). The conditional (``used_at=None``
        filter) makes redemption single-use and race-safe: of two concurrent
        consumers, exactly one gets ``True``.
        """
        ...


class CustomTokenPort(Protocol):
    """Mint a Firebase custom token the browser can exchange for a session.

    Implemented by ``FirebaseAdminAdapter.create_custom_token`` in
    infrastructure. The returned token is a short-lived credential that the
    frontend passes to ``signInWithCustomToken``.
    """

    async def create_custom_token(self, uid: str) -> str: ...
