"""Mongo-backed MembershipRepository.

Auth bootstrap note: membership lookup happens before the normal tenant
ContextVar is set, so this repository queries by explicit `academy_id`
rather than extending TenantScopedRepository.  The query ALWAYS includes
`academy_id` so cross-tenant leakage is structurally impossible.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pymongo import ReturnDocument

from backend.v2.contexts.identity.domain.models import (
    AcademyMembership,
    PlatformRole,
    Role,
)
from backend.v2.shared.ids import new_ulid


class MongoMembershipRepository:
    """Repository for `academy_memberships` and `platform_roles` collections.

    Does NOT extend TenantScopedRepository — membership lookup must work
    before tenant context exists.  Every query includes an explicit
    `academy_id` argument to prevent cross-tenant access.
    """

    memberships_collection = "academy_memberships"
    platform_roles_collection = "platform_roles"

    def __init__(self, db: Any) -> None:
        self._db = db
        self._memberships = db[self.memberships_collection]
        self._platform_roles = db[self.platform_roles_collection]

    # ------------------------------------------------------------------
    # Conversion helpers
    # ------------------------------------------------------------------

    def _to_membership(self, doc: dict[str, object]) -> AcademyMembership:
        roles_raw = doc.get("roles", [])
        if isinstance(roles_raw, str):
            roles: tuple[Role, ...] = (roles_raw,)  # type: ignore[assignment]
        else:
            roles = tuple(roles_raw)  # type: ignore[assignment]

        return AcademyMembership(
            membership_id=str(doc.get("membership_id") or doc["_id"]),
            academy_id=str(doc["academy_id"]),
            user_id=str(doc["user_id"]),
            roles=roles,
            status=str(doc.get("status", "active")),  # type: ignore[arg-type]
            invited_by=doc.get("invited_by"),  # type: ignore[arg-type]
            invited_at=doc.get("invited_at"),  # type: ignore[arg-type]
            accepted_at=doc.get("accepted_at"),  # type: ignore[arg-type]
            created_at=doc.get("created_at"),  # type: ignore[arg-type]
            updated_at=doc.get("updated_at"),  # type: ignore[arg-type]
        )

    def _to_platform_role(self, doc: dict[str, object]) -> PlatformRole:
        return PlatformRole(
            platform_role_id=str(doc.get("platform_role_id") or doc["_id"]),
            user_id=str(doc["user_id"]),
            role=str(doc["role"]),  # type: ignore[arg-type]
            status=str(doc.get("status", "active")),  # type: ignore[arg-type]
            granted_by=doc.get("granted_by"),  # type: ignore[arg-type]
            granted_at=doc.get("granted_at"),  # type: ignore[arg-type]
        )

    # ------------------------------------------------------------------
    # Membership operations
    # ------------------------------------------------------------------

    async def get_membership(
        self, academy_id: str, user_id: str
    ) -> AcademyMembership | None:
        """Return the membership row for (academy_id, user_id), any status.

        The caller is responsible for checking `.is_active()` — this method
        returns invited/suspended/removed memberships so the auth layer can
        produce a specific rejection reason rather than a generic 403.
        """
        doc = await self._memberships.find_one(
            {"academy_id": academy_id, "user_id": user_id}
        )
        return self._to_membership(doc) if doc else None

    async def list_memberships_for_user(
        self, user_id: str
    ) -> list[AcademyMembership]:
        """Return all membership rows across all academies for a user."""
        cursor = self._memberships.find({"user_id": user_id})
        return [self._to_membership(doc) async for doc in cursor]

    async def upsert_membership(
        self, membership: AcademyMembership
    ) -> AcademyMembership:
        """Create or update a membership. Idempotent on (academy_id, user_id)."""
        now = datetime.now(UTC)
        mid = membership.membership_id or new_ulid()
        set_fields: dict[str, object] = {
            "membership_id": mid,
            "roles": list(membership.roles),
            "status": membership.status,
            "updated_at": now,
        }
        if membership.accepted_at is not None:
            set_fields["accepted_at"] = membership.accepted_at

        doc = await self._memberships.find_one_and_update(
            {"academy_id": membership.academy_id, "user_id": membership.user_id},
            {
                "$set": set_fields,
                "$setOnInsert": {
                    "academy_id": membership.academy_id,
                    "user_id": membership.user_id,
                    "invited_by": membership.invited_by,
                    "invited_at": membership.invited_at,
                    "created_at": now,
                },
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        if doc is None:
            # mongomock may return None on upsert insert; re-fetch
            doc = await self._memberships.find_one(
                {"academy_id": membership.academy_id, "user_id": membership.user_id}
            )
        return self._to_membership(doc)

    # ------------------------------------------------------------------
    # Platform role operations
    # ------------------------------------------------------------------

    async def list_active_platform_roles(self, user_id: str) -> list[PlatformRole]:
        """Return only active platform role grants for a user."""
        cursor = self._platform_roles.find({"user_id": user_id, "status": "active"})
        return [self._to_platform_role(doc) async for doc in cursor]

    async def upsert_platform_role(self, platform_role: PlatformRole) -> PlatformRole:
        """Create or update a platform role grant. Idempotent on (user_id, role)."""
        now = datetime.now(UTC)
        prid = platform_role.platform_role_id or new_ulid()

        doc = await self._platform_roles.find_one_and_update(
            {"user_id": platform_role.user_id, "role": platform_role.role},
            {
                "$set": {
                    "platform_role_id": prid,
                    "status": platform_role.status,
                    "updated_at": now,
                },
                "$setOnInsert": {
                    "user_id": platform_role.user_id,
                    "role": platform_role.role,
                    "granted_by": platform_role.granted_by,
                    "granted_at": platform_role.granted_at,
                    "created_at": now,
                },
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        if doc is None:
            doc = await self._platform_roles.find_one(
                {"user_id": platform_role.user_id, "role": platform_role.role}
            )
        return self._to_platform_role(doc)
