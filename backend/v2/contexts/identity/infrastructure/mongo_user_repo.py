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
from pymongo.errors import DuplicateKeyError

from backend.v2.contexts.identity.application.use_cases.admin_directory import (
    AdminUserDetail,
    AdminUserSummary,
    CreateAdminUserCommand,
    UpdateAdminUserCommand,
)
from backend.v2.contexts.identity.domain.errors import (
    CannotRemoveLastRole,
    UserCreateFailed,
    UserEmailAlreadyExists,
    UserEmailUpdateFailed,
    UserOutsideAcademy,
)
from backend.v2.contexts.identity.domain.models import Role, User, normalize_email
from backend.v2.contexts.identity.infrastructure.firebase_admin_adapter import (
    get_firebase_admin_adapter,
)
from backend.v2.shared.ids import new_ulid


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
            normalized_roles = tuple(roles)
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
        secondary_role_filter: dict[str, object] = {
            "role": {"$ne": "admin"},
            "roles": {"$in": [role]},
        }
        if role == "admin":
            secondary_role_filter = {"role": {"$exists": False}, "roles": {"$in": [role]}}
        return {
            "$or": [
                {"role": role},
                {"role": {"$exists": False}, "roles": role},
                secondary_role_filter,
            ]
        }

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
        self, doc: dict[str, object], *, linked_student_count: int, session_count: int = 0
    ) -> AdminUserDetail:
        user = self._to_domain(doc)
        summary = self._to_admin_summary(doc)
        return AdminUserDetail(
            **summary.model_dump(),
            roles=user.roles,
            linked_student_count=linked_student_count,
            session_count=session_count,
            login_invite_sent_at=doc.get("login_invite_sent_at"),
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

    async def list_existing_user_ids(self, user_ids: list[str], *, academy_id: str) -> set[str]:
        """Which of ``user_ids`` (== parent_id, per this codebase's convention
        that a parent IS a User) already have a login account in this academy.

        Used by the Billing Setup admin page to tell "no account yet" apart
        from "account but no saved card".
        """
        if not user_ids:
            return set()
        object_ids = [ObjectId(value) for value in user_ids if ObjectId.is_valid(value)]
        aliases: list[dict[str, object]] = [
            {"user_id": {"$in": user_ids}},
            {"auth_uid": {"$in": user_ids}},
            {"firebase_uid": {"$in": user_ids}},
        ]
        if object_ids:
            aliases.append({"_id": {"$in": object_ids}})
        cursor = self.collection.find(
            {"$or": aliases},
            {"user_id": 1, "auth_uid": 1, "firebase_uid": 1},
        )
        wanted = set(user_ids)
        found: set[str] = set()
        async for doc in cursor:
            firebase_uid = doc.get("firebase_uid") or doc.get("auth_uid")
            if not firebase_uid:
                continue
            membership = await self._db["academy_memberships"].find_one(
                {
                    "academy_id": academy_id,
                    "user_id": str(firebase_uid),
                    "status": "active",
                    "roles": "parent",
                    "login_invite_pending": {"$ne": True},
                },
                {"_id": 1},
            )
            if membership is None:
                continue
            doc_aliases = {
                str(value)
                for value in (
                    doc.get("user_id"),
                    doc.get("auth_uid"),
                    doc.get("firebase_uid"),
                    doc.get("_id"),
                )
                if value
            }
            found.update(wanted & doc_aliases)
        return found

    async def get_billing_setup_parent(self, parent_id: str, *, academy_id: str) -> User | None:
        """Resolve a global user only through an active tenant parent membership."""
        doc = await self.collection.find_one(self._id_filter(parent_id))
        if doc is None:
            return None
        firebase_uid = doc.get("firebase_uid") or doc.get("auth_uid")
        if not firebase_uid:
            return None
        membership = await self._db["academy_memberships"].find_one(
            {
                "academy_id": academy_id,
                "user_id": str(firebase_uid),
                "status": "active",
                "roles": "parent",
            },
            {"_id": 1},
        )
        return self._to_domain(doc) if membership is not None else None

    async def ensure_parent_login(
        self,
        *,
        parent_id: str,
        email: str,
        display_name: str,
        academy_id: str,
        actor_id: str,
    ) -> str:
        """Provision a missing roster parent without changing ownership ids."""
        now = datetime.now(UTC)
        normalized_email = normalize_email(email)
        normalized_name = " ".join(display_name.split())
        existing = await self.collection.find_one(
            {
                "$or": [
                    self._id_filter(parent_id),
                    {"normalized_email": normalized_email},
                    {"email": {"$regex": f"^{re.escape(normalized_email)}$", "$options": "i"}},
                ]
            }
        )
        uid = (
            str(existing.get("firebase_uid") or existing.get("auth_uid") or existing.get("user_id"))
            if existing is not None
            else parent_id
        )

        try:
            firebase_uid, _firebase_created = await get_firebase_admin_adapter().ensure_user(
                uid=uid,
                email=normalized_email,
                display_name=normalized_name,
            )
        except Exception as exc:
            raise UserCreateFailed("could not provision Firebase parent login") from exc

        try:
            if existing is None:
                doc = {
                    "user_id": firebase_uid,
                    "auth_uid": firebase_uid,
                    "firebase_uid": firebase_uid,
                    "auth_provider": "firebase",
                    "email": normalized_email,
                    "normalized_email": normalized_email,
                    "display_name": normalized_name,
                    "role": "parent",
                    "roles": ["parent"],
                    "status": "active",
                    "is_active": True,
                    "academy_id": academy_id,
                    "created_at": now,
                    "updated_at": now,
                }
                try:
                    await self.collection.insert_one(doc)
                except DuplicateKeyError:
                    existing = await self.collection.find_one(
                        {
                            "$or": [
                                {"normalized_email": normalized_email},
                                {"firebase_uid": firebase_uid},
                            ]
                        }
                    )
                    if existing is None:
                        raise
            else:
                await self.collection.update_one(
                    {"_id": existing["_id"]},
                    {
                        "$set": {
                            "auth_uid": firebase_uid,
                            "firebase_uid": firebase_uid,
                            "auth_provider": "firebase",
                            "updated_at": now,
                        }
                    },
                )

            await self._db["academy_memberships"].update_one(
                {"academy_id": academy_id, "user_id": firebase_uid},
                {
                    "$set": {
                        "status": "active",
                        "login_invite_pending": True,
                        "updated_at": now,
                    },
                    "$addToSet": {"roles": "parent"},
                    "$setOnInsert": {
                        "membership_id": str(new_ulid()),
                        "academy_id": academy_id,
                        "user_id": firebase_uid,
                        "invited_by": actor_id,
                        "invited_at": now,
                        "created_at": now,
                    },
                },
                upsert=True,
            )
            await self._write_audit(
                academy_id=academy_id,
                actor_id=actor_id,
                action="parent.login_provisioned",
                entity_id=firebase_uid,
                reason="Billing Setup login invite",
                changed_keys=["auth_uid", "firebase_uid", "auth_provider"],
                before=existing or {},
                after={
                    "auth_uid": firebase_uid,
                    "firebase_uid": firebase_uid,
                    "auth_provider": "firebase",
                },
            )
        except Exception:
            # Do not roll back global identity records: a concurrent request may
            # own them. The pending marker keeps this row retryable until the
            # membership and invite workflow converges.
            raise
        return firebase_uid

    async def _require_member_of_academy(
        self, user_doc: dict[str, Any], *, academy_id: str
    ) -> None:
        """Raise unless this existing user already belongs to `academy_id`.

        Accepts either proof of membership: an `academy_memberships` row
        (the SaaS source of truth, any status — an invited-but-not-accepted
        member is still legitimately this academy's person), or the legacy
        single-tenant `users.academy_id` field for deployments that predate
        membership rows.
        """
        uid = str(
            user_doc.get("firebase_uid")
            or user_doc.get("auth_uid")
            or user_doc.get("user_id")
            or ""
        )
        if uid:
            membership = await self._db["academy_memberships"].find_one(
                {"academy_id": academy_id, "user_id": uid}, {"_id": 1}
            )
            if membership is not None:
                return
        if str(user_doc.get("academy_id") or "") == academy_id:
            return
        raise UserOutsideAcademy(
            "that email belongs to an account outside this academy; "
            "use a different email address"
        )

    async def ensure_student_login(
        self,
        *,
        student_id: str,
        email: str,
        display_name: str,
        academy_id: str,
        actor_id: str,
        reason: str = "student login invite",
    ) -> str:
        """Provision the Firebase identity + `student` membership for UIM12.

        Mirrors `ensure_parent_login`. Does NOT touch the enrollment-context
        `students` collection — the caller (composition adapter in
        `composition/admin.py`) stamps `Student.student_user_id` afterwards
        via `MongoStudentWriter.link_student_user`, which is where "one user
        per student per academy" is actually enforced. This method is safe
        to retry: it is idempotent on `(normalized_email, firebase_uid)`.

        The `users` lookup below is deliberately global (identity is not
        tenant-scoped — one person, one account, many academies), so an
        email may resolve to a user who belongs to a *different* academy.
        Silently reusing that account would grant a stranger — who already
        has a working password — an active `student` membership here and a
        link to this student's data. We refuse instead (review finding P2);
        the admin gets a 409 and has to use an email that is either unknown
        or already a member of this academy.
        """
        now = datetime.now(UTC)
        normalized_email = normalize_email(email)
        normalized_name = " ".join(display_name.split())
        existing = await self.collection.find_one(
            {
                "$or": [
                    {"normalized_email": normalized_email},
                    {"email": {"$regex": f"^{re.escape(normalized_email)}$", "$options": "i"}},
                ]
            }
        )
        if existing is not None:
            await self._require_member_of_academy(existing, academy_id=academy_id)
        uid = (
            str(existing.get("firebase_uid") or existing.get("auth_uid") or existing.get("user_id"))
            if existing is not None
            else f"student-{student_id}"
        )

        try:
            firebase_uid, _firebase_created = await get_firebase_admin_adapter().ensure_user(
                uid=uid,
                email=normalized_email,
                display_name=normalized_name,
            )
        except Exception as exc:
            raise UserCreateFailed("could not provision Firebase student login") from exc

        try:
            if existing is None:
                doc = {
                    "user_id": firebase_uid,
                    "auth_uid": firebase_uid,
                    "firebase_uid": firebase_uid,
                    "auth_provider": "firebase",
                    "email": normalized_email,
                    "normalized_email": normalized_email,
                    "display_name": normalized_name,
                    "role": "student",
                    "roles": ["student"],
                    "status": "active",
                    "is_active": True,
                    "academy_id": academy_id,
                    "created_at": now,
                    "updated_at": now,
                }
                try:
                    await self.collection.insert_one(doc)
                except DuplicateKeyError:
                    existing = await self.collection.find_one(
                        {
                            "$or": [
                                {"normalized_email": normalized_email},
                                {"firebase_uid": firebase_uid},
                            ]
                        }
                    )
                    if existing is None:
                        raise
            else:
                await self.collection.update_one(
                    {"_id": existing["_id"]},
                    {
                        "$set": {
                            "auth_uid": firebase_uid,
                            "firebase_uid": firebase_uid,
                            "auth_provider": "firebase",
                            "updated_at": now,
                        }
                    },
                )

            await self._db["academy_memberships"].update_one(
                {"academy_id": academy_id, "user_id": firebase_uid},
                {
                    "$set": {
                        "status": "active",
                        "login_invite_pending": True,
                        "updated_at": now,
                    },
                    "$addToSet": {"roles": "student"},
                    "$setOnInsert": {
                        "membership_id": str(new_ulid()),
                        "academy_id": academy_id,
                        "user_id": firebase_uid,
                        "invited_by": actor_id,
                        "invited_at": now,
                        "created_at": now,
                    },
                },
                upsert=True,
            )
            await self._write_audit(
                academy_id=academy_id,
                actor_id=actor_id,
                action="student.login_provisioned",
                entity_id=firebase_uid,
                reason=f"{reason} (student {student_id})",
                changed_keys=["auth_uid", "firebase_uid", "auth_provider"],
                before=existing or {},
                after={
                    "auth_uid": firebase_uid,
                    "firebase_uid": firebase_uid,
                    "auth_provider": "firebase",
                },
            )
        except Exception:
            # Do not roll back global identity records: a concurrent request may
            # own them. The pending marker keeps this row retryable until the
            # membership and invite workflow converges.
            raise
        return firebase_uid

    async def get_admin_user(self, user_id: str, *, academy_id: str) -> AdminUserDetail | None:
        doc = await self.collection.find_one({"academy_id": academy_id, **self._id_filter(user_id)})
        if doc is None:
            return None
        return await self._admin_detail_for_doc(doc, academy_id=academy_id)

    @staticmethod
    def _identity_aliases(doc: dict[str, object]) -> list[str]:
        """Every identifier this account might be keyed by in `academy_memberships`.

        `users.user_id` and `academy_memberships.user_id` are supposed to be
        the same value, but `ensure_parent_login`/`ensure_student_login`
        preserve a pre-existing roster `user_id` while keying the new
        membership row by the freshly-provisioned `firebase_uid` (see those
        methods below), so the two can legitimately diverge in either
        direction. Check every alias rather than betting on one field.
        """
        return [
            str(value)
            for value in (doc.get("user_id"), doc.get("auth_uid"), doc.get("firebase_uid"))
            if value
        ]

    async def _active_membership_for_doc(
        self, doc: dict[str, object], *, academy_id: str
    ) -> dict[str, object] | None:
        aliases = self._identity_aliases(doc)
        if not aliases:
            return None
        membership: dict[str, object] | None = await self._db["academy_memberships"].find_one(
            {"academy_id": academy_id, "user_id": {"$in": aliases}, "status": "active"}
        )
        return membership

    async def get_login_invite_user(
        self, user_id: str, *, academy_id: str
    ) -> AdminUserDetail | None:
        """Resolve a global invite target through its active tenant membership."""
        doc = await self.collection.find_one(self._id_filter(user_id))
        if doc is None:
            return None
        membership = await self._active_membership_for_doc(doc, academy_id=academy_id)
        if membership is None:
            return None
        return await self._admin_detail_for_doc(doc, academy_id=academy_id)

    async def _admin_detail_for_doc(
        self, doc: dict[str, object], *, academy_id: str
    ) -> AdminUserDetail:
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
        session_count = await self._db["sessions"].count_documents(
            {
                "academy_id": academy_id,
                "coach_id": {"$in": lookup_ids},
            }
        )
        return self._to_admin_detail(
            doc, linked_student_count=linked_student_count, session_count=session_count
        )

    async def record_login_invite(
        self, user_id: str, *, academy_id: str, sent_at: datetime
    ) -> None:
        doc = await self.collection.find_one(self._id_filter(user_id))
        aliases = self._identity_aliases(doc) if doc else []
        if not aliases:
            raise UserCreateFailed("login invite target has no active academy membership")
        result = await self._db["academy_memberships"].update_one(
            {"academy_id": academy_id, "user_id": {"$in": aliases}, "status": "active"},
            {
                "$set": {"login_invite_sent_at": sent_at, "updated_at": sent_at},
                "$unset": {"login_invite_pending": ""},
            },
        )
        if getattr(result, "matched_count", 0) != 1:
            raise UserCreateFailed("login invite target has no active academy membership")

    async def create_admin_user(
        self,
        command: CreateAdminUserCommand,
        *,
        academy_id: str,
    ) -> AdminUserDetail:
        now = datetime.now(UTC)
        email = normalize_email(str(command.email))
        display_name = " ".join(command.display_name.split())
        await self._ensure_email_available(email, exclude_user_id=None)

        uid = f"user_{new_ulid().lower()}"
        firebase_uid = await type(self)._create_firebase_user(
            uid=uid,
            email=email,
            display_name=display_name,
        )
        doc = {
            "user_id": firebase_uid,
            "auth_uid": firebase_uid,
            "firebase_uid": firebase_uid,
            "auth_provider": "firebase",
            "email": email,
            "normalized_email": email,
            "display_name": display_name,
            "phone": command.phone.strip() if command.phone else None,
            "role": command.role,
            "roles": [command.role],
            "status": "active",
            "is_active": True,
            "academy_id": academy_id,
            "created_at": now,
            "updated_at": now,
        }
        try:
            result = await self.collection.insert_one(doc)
            doc["_id"] = result.inserted_id
            await self._db["academy_memberships"].update_one(
                {"academy_id": academy_id, "user_id": firebase_uid},
                {
                    "$set": {
                        "roles": [command.role],
                        "status": "active",
                        "updated_at": now,
                    },
                    "$setOnInsert": {
                        "membership_id": str(new_ulid()),
                        "academy_id": academy_id,
                        "user_id": firebase_uid,
                        "invited_by": command.actor_id,
                        "invited_at": now,
                        "accepted_at": now,
                        "created_at": now,
                    },
                },
                upsert=True,
            )
            await self._write_audit(
                academy_id=academy_id,
                actor_id=command.actor_id,
                action="user.created",
                entity_id=firebase_uid,
                reason=command.reason,
                changed_keys=[
                    "email",
                    "display_name",
                    "phone",
                    "role",
                    "roles",
                    "status",
                ],
                before={},
                after=doc,
            )
        except Exception:
            await self.collection.delete_one({"user_id": firebase_uid})
            await self._db["academy_memberships"].delete_one(
                {"academy_id": academy_id, "user_id": firebase_uid}
            )
            await type(self)._delete_firebase_user(firebase_uid)
            raise
        created = await self.get_admin_user(firebase_uid, academy_id=academy_id)
        if created is None:
            raise UserCreateFailed("created user could not be loaded")
        return created

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
        email_change: tuple[str, str] | None = None
        if command.email is not None:
            email = normalize_email(str(command.email))
            await self._ensure_email_available(email, exclude_user_id=user_id)
            auth_uid = self._firebase_uid(before)
            if auth_uid:
                email_change = (auth_uid, email)
            set_doc["email"] = email
            set_doc["normalized_email"] = email
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
        if email_change is not None:
            try:
                await self._update_firebase_email(*email_change)
            except Exception:
                await self.collection.update_one(
                    {"_id": before["_id"]},
                    {
                        "$set": {
                            "email": before.get("email"),
                            "normalized_email": before.get("normalized_email")
                            or normalize_email(str(before.get("email") or "")),
                            "updated_at": before.get("updated_at", datetime.now(UTC)),
                        }
                    },
                )
                raise
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

    async def _ensure_email_available(
        self,
        email: str,
        *,
        exclude_user_id: str | None,
    ) -> None:
        query: dict[str, object] = {
            "$or": [
                {"normalized_email": email},
                {"email": {"$regex": f"^{re.escape(email)}$", "$options": "i"}},
            ]
        }
        if exclude_user_id is not None:
            query["$nor"] = [self._id_filter(exclude_user_id)]
        existing = await self.collection.find_one(query)
        if existing is not None:
            raise UserEmailAlreadyExists("email already belongs to another user", email=email)

    @staticmethod
    def _firebase_uid(doc: dict[str, object]) -> str | None:
        for key in ("auth_uid", "firebase_uid", "user_id"):
            value = doc.get(key)
            if value:
                return str(value)
        return None

    @staticmethod
    async def _create_firebase_user(*, uid: str, email: str, display_name: str) -> str:
        try:
            return await get_firebase_admin_adapter().create_user(
                uid=uid,
                email=email,
                display_name=display_name,
            )
        except Exception as exc:
            raise UserCreateFailed("could not create Firebase user") from exc

    @staticmethod
    async def _delete_firebase_user(uid: str) -> None:
        try:
            await get_firebase_admin_adapter().delete_user(uid)
        except Exception:
            return

    @staticmethod
    async def _update_firebase_email(auth_uid: str, email: str) -> None:
        try:
            await get_firebase_admin_adapter().update_user_email(auth_uid, email)
        except Exception as exc:
            raise UserEmailUpdateFailed("could not update Firebase email") from exc

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

    async def add_role(
        self,
        user_id: str,
        role: Role,
        *,
        academy_id: str,
        actor_id: str,
        reason: str,
    ) -> AdminUserDetail | None:
        return await self._modify_roles(
            user_id,
            role,
            adding=True,
            academy_id=academy_id,
            actor_id=actor_id,
            reason=reason,
        )

    async def remove_role(
        self,
        user_id: str,
        role: Role,
        *,
        academy_id: str,
        actor_id: str,
        reason: str,
    ) -> AdminUserDetail | None:
        return await self._modify_roles(
            user_id,
            role,
            adding=False,
            academy_id=academy_id,
            actor_id=actor_id,
            reason=reason,
        )

    async def _modify_roles(
        self,
        user_id: str,
        role: Role,
        *,
        adding: bool,
        academy_id: str,
        actor_id: str,
        reason: str,
    ) -> AdminUserDetail | None:
        now = datetime.now(UTC)
        before = await self.collection.find_one(
            {"academy_id": academy_id, **self._id_filter(user_id)}
        )
        if before is None:
            return None

        current = list(before.get("roles") or ([before["role"]] if before.get("role") else []))
        if adding:
            new_roles = current if role in current else [*current, role]
        else:
            new_roles = [r for r in current if r != role]
            if not new_roles:
                raise CannotRemoveLastRole(user_id)
        # Keep the legacy single `role` field meaningful: preserve it unless
        # it was the role being removed, in which case fall back to the first
        # remaining role.
        primary = before.get("role")
        if primary not in new_roles:
            primary = new_roles[0]

        doc = await self.collection.find_one_and_update(
            {"academy_id": academy_id, **self._id_filter(user_id)},
            {"$set": {"role": primary, "roles": new_roles, "updated_at": now}},
            return_document=ReturnDocument.AFTER,
        )
        if doc is None:
            return None

        resolved_user_id = self._to_domain(doc).user_id
        # Mirror into the SaaS source of truth (claims are built from this).
        membership_update: dict[str, Any] = (
            {"$addToSet": {"roles": role}} if adding else {"$pull": {"roles": role}}
        )
        membership_update["$set"] = {"updated_at": now}

        # When adding a role, upsert the membership row if it doesn't exist
        # (e.g., legacy parent accounts with no membership record).
        upsert_kwargs = {"upsert": True} if adding else {}
        if adding:
            membership_update["$setOnInsert"] = {
                "membership_id": str(new_ulid()),
                "academy_id": academy_id,
                "user_id": resolved_user_id,
                "invited_by": actor_id,
                "invited_at": now,
                "accepted_at": now,
                "created_at": now,
                "status": "active",
            }

        await self._db["academy_memberships"].update_one(
            {"academy_id": academy_id, "user_id": resolved_user_id},
            membership_update,
            **upsert_kwargs,
        )

        await self._write_audit(
            academy_id=academy_id,
            actor_id=actor_id,
            action="user.role_added" if adding else "user.role_removed",
            entity_id=resolved_user_id,
            reason=reason,
            changed_keys=["role", "roles"],
            before=before,
            after=doc,
        )
        return await self.get_admin_user(resolved_user_id, academy_id=academy_id)
