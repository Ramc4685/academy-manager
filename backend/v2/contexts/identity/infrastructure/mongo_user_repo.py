"""Mongo-backed UserRepository.

The TenantScopedRepository base class filters every query by ``academy_id``
from the request ContextVar (ADR-0006). Application code never sees it.
"""

from __future__ import annotations

from backend.v2.contexts.identity.domain.models import User
from backend.v2.shared.tenancy import TenantScopedRepository


class MongoUserRepository(TenantScopedRepository):
    collection_name = "users"

    @staticmethod
    def _to_domain(doc: dict[str, object]) -> User:
        return User(
            user_id=str(doc["user_id"]),
            email=str(doc["email"]),
            display_name=str(doc.get("display_name", doc["email"])),
            roles=tuple(doc.get("roles", ())),  # type: ignore[arg-type]
            is_active=bool(doc.get("is_active", True)),
            academy_id=str(doc["academy_id"]),
        )

    async def get_by_email(self, email: str) -> User | None:
        doc = await self._find_one({"email": email})
        return self._to_domain(doc) if doc else None

    async def get_by_id(self, user_id: str) -> User | None:
        doc = await self._find_one({"user_id": user_id})
        return self._to_domain(doc) if doc else None
