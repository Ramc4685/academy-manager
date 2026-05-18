"""Mongo-backed UserRepository.

Identity lookup is the auth bootstrap step: it verifies a Firebase identity
against the app's Mongo user/role record before request tenant scope exists.
That makes this repository intentionally unscoped for reads; the resulting
``academy_id`` is what the auth middleware places into the tenant ContextVar.
"""

from __future__ import annotations

import re
from typing import Any

from backend.v2.contexts.identity.domain.models import Role, User
from backend.v2.contexts.identity.application.use_cases.admin_directory import (
    AdminUserSummary,
)


class MongoUserRepository:
    collection_name = "users"

    def __init__(self, db: Any, *, default_academy_id: str = "default-academy") -> None:
        self._db = db
        self.collection = db[self.collection_name]
        self._default_academy_id = default_academy_id

    def _to_domain(self, doc: dict[str, object]) -> User:
        legacy_role = doc.get("role")
        roles = doc.get("roles")
        if isinstance(roles, str):
            normalized_roles: tuple[Role, ...] = (roles,)  # type: ignore[assignment]
        elif isinstance(roles, (list, tuple)):
            normalized_roles = tuple(roles)  # type: ignore[assignment]
        elif isinstance(legacy_role, str):
            normalized_roles = (legacy_role,)  # type: ignore[assignment]
        else:
            normalized_roles = ()

        status = doc.get("status")
        is_active = bool(doc.get("is_active", status != "inactive" and status != "disabled"))

        return User(
            user_id=str(doc.get("user_id") or doc.get("auth_uid") or doc["_id"]),
            email=str(doc["email"]),
            display_name=str(doc.get("display_name") or doc.get("name") or doc["email"]),
            roles=normalized_roles,
            is_active=is_active,
            academy_id=str(doc.get("academy_id") or self._default_academy_id),
        )

    async def get_by_email(self, email: str) -> User | None:
        doc = await self.collection.find_one(
            {"email": {"$regex": f"^{re.escape(email)}$", "$options": "i"}}
        )
        return self._to_domain(doc) if doc else None

    async def get_by_id(self, user_id: str) -> User | None:
        doc = await self.collection.find_one(
            {"$or": [{"user_id": user_id}, {"auth_uid": user_id}, {"_id": user_id}]}
        )
        return self._to_domain(doc) if doc else None

    @staticmethod
    def _role_filter(role: Role) -> dict[str, object]:
        return {"$or": [{"role": role}, {"roles": role}, {"roles": {"$in": [role]}}]}

    def _to_admin_summary(self, doc: dict[str, object]) -> AdminUserSummary:
        user = self._to_domain(doc)
        primary_role = user.roles[0] if user.roles else "parent"
        status = str(doc.get("status") or ("active" if user.is_active else "inactive"))
        return AdminUserSummary(
            user_id=user.user_id,
            email=user.email,
            display_name=user.display_name,
            role=primary_role,
            status=status,
        )

    async def list_users(self, role: Role | None = None) -> list[AdminUserSummary]:
        query = self._role_filter(role) if role else {}
        cursor = self.collection.find(query).sort([("role", 1), ("display_name", 1), ("email", 1)])
        return [self._to_admin_summary(doc) async for doc in cursor]
