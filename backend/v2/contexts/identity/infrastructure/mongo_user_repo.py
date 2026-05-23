"""Mongo-backed UserRepository.

Identity lookup is the auth bootstrap step: it verifies a Firebase identity
against the app's Mongo user/role record before request tenant scope exists.
That makes this repository intentionally unscoped for reads; the resulting
``academy_id`` is what the auth middleware places into the tenant ContextVar.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from bson import ObjectId
from pymongo import ReturnDocument

from backend.v2.contexts.identity.application.use_cases.admin_directory import (
    AdminUserDetail,
    AdminUserSummary,
    UpdateAdminUserCommand,
)
from backend.v2.contexts.identity.domain.models import Role, User


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
        elif isinstance(roles, list | tuple):
            normalized_roles = tuple(roles)  # type: ignore[assignment]
        elif isinstance(legacy_role, str):
            normalized_roles = (legacy_role,)  # type: ignore[assignment]
        else:
            normalized_roles = ()

        status = doc.get("status")
        is_active = bool(doc.get("is_active", status != "inactive" and status != "disabled"))

        raw_fuid = doc.get("firebase_uid") or doc.get("auth_uid")
        raw_nemail = doc.get("normalized_email")

        return User(
            user_id=str(doc.get("user_id") or doc.get("auth_uid") or doc["_id"]),
            firebase_uid=str(raw_fuid) if raw_fuid else None,
            email=str(doc["email"]),
            normalized_email=str(raw_nemail) if raw_nemail else None,
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

    async def get_by_firebase_uid(self, firebase_uid: str) -> User | None:
        doc = await self.collection.find_one(
            {"$or": [{"firebase_uid": firebase_uid}, {"auth_uid": firebase_uid}]}
        )
        return self._to_domain(doc) if doc else None

    async def get_by_id(self, user_id: str) -> User | None:
        doc = await self.collection.find_one(
            {"$or": [{"user_id": user_id}, {"auth_uid": user_id}, {"_id": user_id}]}
        )
        return self._to_domain(doc) if doc else None

    async def ensure_parent_user(
        self,
        *,
        email: str,
        display_name: str,
        firebase_uid: str,
        academy_id: str,
    ) -> User:
        """Insert or update the parent ``User`` row for ``(email, firebase_uid)``.

        ``academy_id`` is the resolved tenant the request was made
        against. It is written to ``User.academy_id`` ONLY on first
        insert. For an existing user, the original ``academy_id`` is
        preserved; multi-tenant access is carried by ``AcademyMembership``
        rows the calling use case writes separately.

        Fixes #81 — previously this method always wrote
        ``self._default_academy_id``, dropping every SaaS-mode parent
        into ``default-academy``.
        """
        existing = await self.collection.find_one(
            {"email": {"$regex": f"^{re.escape(email)}$", "$options": "i"}}
        )
        now = datetime.now(UTC)
        if existing:
            roles = set(self._to_domain(existing).roles)
            roles.add("parent")
            await self.collection.update_one(
                {"_id": existing["_id"]},
                {
                    "$set": {
                        "display_name": display_name,
                        "roles": sorted(roles),
                        "role": existing.get("role") or "parent",
                        "auth_provider": existing.get("auth_provider") or "firebase",
                        "auth_uid": existing.get("auth_uid") or firebase_uid,
                        "firebase_uid": existing.get("firebase_uid") or firebase_uid,
                        "is_active": existing.get("is_active", True),
                        "status": existing.get("status") or "active",
                        "updated_at": now,
                    }
                },
            )
            updated = await self.collection.find_one({"_id": existing["_id"]})
            assert updated is not None
            return self._to_domain(updated)

        doc = {
            "user_id": firebase_uid,
            "auth_uid": firebase_uid,
            "firebase_uid": firebase_uid,
            "auth_provider": "firebase",
            "email": email,
            "display_name": display_name,
            "roles": ["parent"],
            "role": "parent",
            "status": "active",
            "is_active": True,
            "academy_id": academy_id,
            "created_at": now,
            "updated_at": now,
        }
        result = await self.collection.insert_one(doc)
        doc["_id"] = result.inserted_id
        return self._to_domain(doc)

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
            phone=str(doc.get("phone")) if doc.get("phone") is not None else None,
        )

    def _to_admin_detail(
        self, doc: dict[str, object], *, linked_student_count: int
    ) -> AdminUserDetail:
        user = self._to_domain(doc)
        summary = self._to_admin_summary(doc)
        return AdminUserDetail(
            **summary.model_dump(),
            roles=user.roles,
            linked_student_count=linked_student_count,
        )

    @staticmethod
    def _id_filter(user_id: str) -> dict[str, object]:
        ids: list[object] = [user_id]
        if ObjectId.is_valid(user_id):
            ids.append(ObjectId(user_id))
        return {
            "$or": [
                {"user_id": user_id},
                {"auth_uid": user_id},
                {"firebase_uid": user_id},
                {"_id": {"$in": ids}},
            ]
        }

    async def list_users(
        self, role: Role | None = None, academy_id: str | None = None
    ) -> list[AdminUserSummary]:
        query: dict[str, object] = {"academy_id": academy_id or self._default_academy_id}
        if role:
            query = {"$and": [query, self._role_filter(role)]}
        cursor = self.collection.find(query).sort([("role", 1), ("display_name", 1), ("email", 1)])
        return [self._to_admin_summary(doc) async for doc in cursor]

    async def get_admin_user(self, user_id: str, *, academy_id: str) -> AdminUserDetail | None:
        doc = await self.collection.find_one({"academy_id": academy_id, **self._id_filter(user_id)})
        if doc is None:
            return None
        lookup_ids = [
            str(value)
            for value in (
                doc.get("user_id"),
                doc.get("auth_uid"),
                doc.get("firebase_uid"),
                doc.get("_id"),
            )
            if value
        ]
        linked_student_count = await self._db["students"].count_documents(
            {
                "academy_id": academy_id,
                "$or": [
                    {"parent_id": {"$in": lookup_ids}},
                    {"parent_user_id": {"$in": lookup_ids}},
                ],
            }
        )
        return self._to_admin_detail(doc, linked_student_count=linked_student_count)

    async def update_admin_user(
        self,
        user_id: str,
        command: UpdateAdminUserCommand,
        *,
        academy_id: str,
    ) -> AdminUserDetail | None:
        before = await self.collection.find_one(
            {"academy_id": academy_id, **self._id_filter(user_id)}
        )
        if before is None:
            return None
        set_doc: dict[str, object] = {"updated_at": datetime.now(UTC)}
        if command.display_name is not None:
            set_doc["display_name"] = " ".join(command.display_name.split())
        if command.phone is not None:
            set_doc["phone"] = command.phone.strip() or None
        if command.status is not None:
            set_doc["status"] = command.status
            set_doc["is_active"] = command.status == "active"
        changed = [
            key
            for key, value in set_doc.items()
            if key != "updated_at" and before.get(key) != value
        ]
        doc = await self.collection.find_one_and_update(
            {"academy_id": academy_id, **self._id_filter(user_id)},
            {"$set": set_doc},
            return_document=ReturnDocument.AFTER,
        )
        if doc is None:
            return None
        if changed:
            await self._write_audit(
                academy_id=academy_id,
                actor_id=command.actor_id,
                action="user.edited",
                entity_id=self._to_domain(doc).user_id,
                reason=command.reason,
                changed_keys=changed,
                before=before,
                after=doc,
            )
        return await self.get_admin_user(self._to_domain(doc).user_id, academy_id=academy_id)

    async def change_role(
        self,
        user_id: str,
        role: Role,
        *,
        academy_id: str,
        actor_id: str,
        reason: str,
    ) -> AdminUserSummary | None:
        now = datetime.now(UTC)
        before = await self.collection.find_one(
            {"academy_id": academy_id, **self._id_filter(user_id)}
        )
        if before is None:
            return None
        doc = await self.collection.find_one_and_update(
            {"academy_id": academy_id, **self._id_filter(user_id)},
            {"$set": {"role": role, "roles": [role], "updated_at": now}},
            return_document=ReturnDocument.AFTER,
        )
        if doc is not None:
            await self._write_audit(
                academy_id=academy_id,
                actor_id=actor_id,
                action="user.role_changed",
                entity_id=self._to_domain(doc).user_id,
                reason=reason,
                changed_keys=["role", "roles"],
                before=before,
                after=doc,
            )
        return self._to_admin_summary(doc) if doc else None

    async def _write_audit(
        self,
        *,
        academy_id: str,
        actor_id: str,
        action: str,
        entity_id: str,
        reason: str,
        changed_keys: list[str],
        before: dict[str, Any],
        after: dict[str, Any],
    ) -> None:
        from backend.v2.shared.ids import new_ulid

        def pick(doc: dict[str, Any]) -> dict[str, Any]:
            return {key: doc.get(key) for key in changed_keys}

        await self._db["audit_logs"].insert_one(
            {
                "audit_id": str(new_ulid()),
                "academy_id": academy_id,
                "actor_id": actor_id,
                "action": action,
                "entity_type": "user",
                "entity_id": entity_id,
                "reason": reason,
                "changed_keys": changed_keys,
                "before": pick(before),
                "after": pick(after),
                "created_at": datetime.now(UTC),
            }
        )
