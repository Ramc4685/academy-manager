"""Identity application ports (Protocols implemented by infrastructure)."""

from __future__ import annotations

from typing import Protocol

from backend.v2.contexts.identity.domain.models import User


class UserRepository(Protocol):
    """Read/write port for User aggregates.

    The Mongo implementation in `infrastructure/mongo_user_repo.py` extends
    `TenantScopedRepository` so it automatically filters by `academy_id`.
    """

    async def get_by_email(self, email: str) -> User | None: ...
    async def get_by_id(self, user_id: str) -> User | None: ...


class TokenVerifier(Protocol):
    """Verifies a Firebase ID token and returns a dict of claims.

    Implementation lives in `infrastructure/firebase_token_verifier.py`. A
    test fake implements this to avoid hitting Firebase in unit tests.
    """

    async def verify(self, id_token: str) -> dict[str, object]: ...
