"""Mongo-backed UserRepository.

Identity lookup is the auth bootstrap step: it verifies a Firebase identity
against the app's Mongo user/role record before request tenant scope exists.
That makes this repository intentionally unscoped for reads; the resulting
``academy_id`` is what the auth middleware places into the tenant ContextVar.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any, cast

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
    RoleRevocationFailed,
    UserCreateFailed,
    UserEmailAlreadyExists,
    UserEmailUpdateFailed,
    UserOutsideAcademy,
)
from backend.v2.contexts.identity.domain.identity_aliases import (
    aliases_from_doc,
    identity_aliases,
    membership_match_rank,
)
from backend.v2.contexts.identity.domain.models import Role, User, normalize_email
from backend.v2.contexts.identity.infrastructure.firebase_admin_adapter import (
    get_firebase_admin_adapter,
)
from backend.v2.shared.ids import new_ulid
from backend.v2.shared.observability.ops_alerts import capture_message

_log = logging.getLogger(__name__)


# Relative privilege of the roles a replacement can set. Only the ORDER matters:
# it decides which of the two writes in `change_role` must land first, so that a
# partial failure can never leave effective access wider than the directory
# shows. `parent` and `student` are peers — neither grants staff access.
_ROLE_PRIVILEGE: dict[str, int] = {
    "student": 0,
    "parent": 0,
    "assistant_coach": 1,
    "coach": 2,
    "admin": 3,
    "owner": 4,
}


def _lowers_privilege(previous: list[str], role: str) -> bool:
    """True when the replacement lowers the account's privilege ceiling."""
    ceiling = max((_ROLE_PRIVILEGE.get(r, 0) for r in previous), default=0)
    return _ROLE_PRIVILEGE.get(role, 0) < ceiling


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
        raw_auth_uid = doc.get("auth_uid")
        raw_nemail = doc.get("normalized_email")
        raw_phone = doc.get("phone")
        raw_confirmed = doc.get("email_confirmed_at")

        return User(
            user_id=str(doc.get("user_id") or doc.get("auth_uid") or doc["_id"]),
            firebase_uid=str(raw_fuid) if raw_fuid else None,
            auth_uid=str(raw_auth_uid) if raw_auth_uid else None,
            email=str(doc["email"]),
            normalized_email=str(raw_nemail) if raw_nemail else None,
            display_name=str(doc.get("display_name") or doc.get("name") or doc["email"]),
            phone=str(raw_phone) if raw_phone else None,
            roles=normalized_roles,
            is_active=is_active,
            academy_id=str(doc.get("academy_id") or self._default_academy_id),
            email_confirmed_at=raw_confirmed if isinstance(raw_confirmed, datetime) else None,
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

    async def confirm_email(self, user_id: str) -> User | None:
        """Stamp ``email_confirmed_at`` — self-service confirmation only, never
        an address change. The parent profile route is the only caller."""
        doc = await self.collection.find_one_and_update(
            {"$or": [{"user_id": user_id}, {"auth_uid": user_id}, {"_id": user_id}]},
            {"$set": {"email_confirmed_at": datetime.now(UTC)}},
            return_document=ReturnDocument.AFTER,
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
        self,
        doc: dict[str, object],
        *,
        linked_student_count: int,
        session_count: int = 0,
        login_invite_sent_at: datetime | None = None,
    ) -> AdminUserDetail:
        user = self._to_domain(doc)
        summary = self._to_admin_summary(doc)
        return AdminUserDetail(
            **summary.model_dump(),
            roles=user.roles,
            linked_student_count=linked_student_count,
            session_count=session_count,
            # Passed in from the tenant's `academy_memberships` row, never read
            # off `doc`: `record_login_invite` only ever writes the timestamp
            # to the membership. Reading it here yielded None on every request,
            # so the admin page kept offering "Send login invite" after a
            # successful send -- and each re-send mints a new Firebase oobCode
            # that invalidates the link already emailed to the parent.
            login_invite_sent_at=login_invite_sent_at,
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
            "that email belongs to an account outside this academy; use a different email address"
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

        Thin wrapper over the shared `domain.identity_aliases` helper, which
        the membership repository and `load_auth_claims` also use so the
        invite path and the login path can never drift apart again.
        """
        return list(aliases_from_doc(doc))

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
        return await self._admin_detail_for_doc(doc, academy_id=academy_id, membership=membership)

    async def _admin_detail_for_doc(
        self,
        doc: dict[str, object],
        *,
        academy_id: str,
        membership: dict[str, object] | None = None,
    ) -> AdminUserDetail:
        """Assemble the admin detail view for a `users` doc.

        Pass ``membership`` when the caller has already resolved the active
        membership row, so we do not query `academy_memberships` twice.
        """
        if membership is None:
            membership = await self._active_membership_for_doc(doc, academy_id=academy_id)
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
            doc,
            linked_student_count=linked_student_count,
            session_count=session_count,
            login_invite_sent_at=cast(
                "datetime | None", (membership or {}).get("login_invite_sent_at")
            ),
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
            # Only touch Firebase when the address actually moves: the write
            # also clears `email_verified`, which locks password login until
            # a new set-password link is completed (#436). Re-submitting the
            # same address (a no-op edit, or a casing-only difference) must
            # not cost the user their verified state.
            previous_email = str(before.get("email") or before.get("normalized_email") or "")
            unchanged = bool(previous_email) and normalize_email(previous_email) == email
            await self._ensure_email_available(email, exclude_user_id=user_id)
            auth_uid = self._firebase_uid(before)
            if auth_uid and not unchanged:
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

        # Write order follows the DIRECTION of the change, so that a partial
        # failure can never leave effective access wider than the directory
        # claims. `academy_memberships` — not this `users` doc — is what
        # `LoadAuthClaims` turns into request claims.
        #
        # Narrowing (a demotion): revoke the membership FIRST. Ordered the other
        # way round, a membership write that throws leaves the directory showing
        # "parent" and the account still holding live admin claims — the exact
        # failure this branch exists to remove. Revoking first means a partial
        # failure leaves access at what the actor asked for or less, and a
        # revocation that cannot be written aborts instead of being reported as
        # a completed demotion.
        #
        # Widening (a promotion): write the directory FIRST, for the mirror
        # reason. Granting the membership first and then failing the users
        # update would hand out live admin claims the directory does not show —
        # fail-open, and invisible to anyone reading the admin UI.
        previous_roles = list(
            before.get("roles") or ([before["role"]] if before.get("role") else [])
        )
        # A *replacement* always drops the old role, so "lost a role" cannot tell
        # a demotion from a promotion — only the privilege ceiling can.
        narrowing = _lowers_privilege(previous_roles, role)

        if narrowing:
            await self._replace_membership_roles(before, role=role, academy_id=academy_id, now=now)

        doc = await self.collection.find_one_and_update(
            {"academy_id": academy_id, **self._id_filter(user_id)},
            {"$set": {"role": role, "roles": [role], "updated_at": now}},
            return_document=ReturnDocument.AFTER,
        )
        if not narrowing:
            await self._replace_membership_roles(before, role=role, academy_id=academy_id, now=now)
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

    def _membership_aliases(self, doc: dict[str, Any]) -> tuple[str, ...]:
        """The alias set `LoadAuthClaims` resolves this account's membership with.

        `aliases_from_doc` reads the three id *fields*; the claims path adds
        the domain-resolved `user_id`, which falls back to `str(_id)` for a
        legacy doc carrying neither `user_id` nor `auth_uid`. Revoking with the
        narrower set would walk straight past an `_id`-keyed membership row
        that auth can still see, and leave the old grant live.
        """
        return identity_aliases(self._to_domain(doc).user_id, *aliases_from_doc(doc))

    async def _membership_is_foreign(self, row: dict[str, Any], doc: dict[str, Any]) -> bool:
        """True when an alias-matched membership row is really another account's.

        Alias matching widens identity, and one account's `auth_uid` can be
        another account's primary `users.user_id` (roster ids and Firebase uids
        are minted by different paths and have collided before). Whoever holds
        the key as their *primary* `user_id` owns the row; an account that
        merely aliases it does not, and must not rewrite its roles.
        """
        key = str(row.get("user_id") or "")
        if not key or key == self._to_domain(doc).user_id:
            return False
        owner = await self.collection.find_one({"user_id": key, "_id": {"$ne": doc.get("_id")}})
        return owner is not None

    async def _replace_membership_roles(
        self,
        doc: dict[str, Any],
        *,
        role: Role,
        academy_id: str,
        now: datetime,
    ) -> None:
        """Mirror a role *replacement* into this academy's membership row(s).

        Resolution matches the read path exactly — the alias set
        `LoadAuthClaims` builds and the `membership_match_rank` ordering
        `get_membership` picks with — and then writes rows **by their own
        `_id`**, never by the alias filter. An uncapped alias-matched
        `update_many` would also flatten the roles of any other account whose
        primary `user_id` collides with one of these aliases.

        Every row this account owns is rewritten, not just the top-ranked one:
        a stale row left behind by `ensure_parent_login` becomes the row auth
        reads the moment the live one is removed, so a revocation that skipped
        it would only be deferred, not applied.

        The write result is checked, three ways:

        1. rows resolved and the update landed on them — done;
        2. rows resolved and the update did *not* land — raise
           `RoleRevocationFailed`, as `record_login_invite` does for its own
           `matched_count`. A lost write here is a demotion that did not
           happen, and must not be reported as one;
        3. nothing resolved — no raise. "No membership row at all" (nothing to
           revoke) and "row keyed outside every alias" are indistinguishable
           from here, but neither can keep a grant alive: `LoadAuthClaims`
           resolves through this same alias set, so a row it cannot reach
           grants nothing. A *narrowing* still logs and alerts, so a mis-keyed
           row is visible in ops instead of silently no-opping.
        """
        memberships = self._db["academy_memberships"]
        aliases = list(self._membership_aliases(doc))
        rows = [
            row
            async for row in memberships.find(
                {"academy_id": academy_id, "user_id": {"$in": aliases}}
            )
        ]

        resolved_user_id = self._to_domain(doc).user_id
        owned: list[dict[str, Any]] = []
        skipped_foreign: list[dict[str, Any]] = []
        for row in rows:
            if await self._membership_is_foreign(row, doc):
                skipped_foreign.append(row)
                _log.error(
                    "role change skipped a membership row owned by another account",
                    extra={
                        "academy_id": academy_id,
                        "user_id": resolved_user_id,
                        "membership_id": row.get("membership_id"),
                        "membership_user_id": row.get("user_id"),
                    },
                )
                capture_message(
                    "Identity alias collision on academy_memberships during role change "
                    f"for {resolved_user_id} in {academy_id}",
                    level="error",
                )
                continue
            owned.append(row)
        owned.sort(key=lambda row: membership_match_rank(row, resolved_user_id))

        previous = list(doc.get("roles") or ([doc["role"]] if doc.get("role") else []))
        # Any replacement drops the previous role, so an unwritten row can keep
        # serving it — that is what makes an unreachable row dangerous here,
        # independently of whether the change raises or lowers privilege.
        drops_a_role = bool(set(previous) - {role})

        if skipped_foreign and drops_a_role:
            # A skipped row is NOT the harmless case described above. It matched
            # the alias query, so `LoadAuthClaims` — which resolves through this
            # same alias set — can still read it and keep serving the old role.
            # Rewriting it is not an option either: under a collision it may
            # genuinely belong to the other account. So a narrowing that cannot
            # reach every alias-visible row fails closed and asks a human to
            # untangle the collision, rather than reporting a demotion that
            # leaves live admin claims behind it.
            raise RoleRevocationFailed(
                f"role revocation for {resolved_user_id} in {academy_id} could not claim "
                f"{len(skipped_foreign)} alias-matched membership row(s) owned by another "
                f"account (first {skipped_foreign[0].get('membership_id')}); "
                "auth can still resolve them, so the old grant would stay live"
            )

        if not owned:
            if drops_a_role:
                _log.warning(
                    "role change matched no membership row to revoke",
                    extra={
                        "academy_id": academy_id,
                        "user_id": resolved_user_id,
                        "aliases": aliases,
                        "previous_roles": previous,
                        "new_role": role,
                    },
                )
                capture_message(
                    f"Role narrowing for {resolved_user_id} in {academy_id} matched no "
                    "academy_memberships row",
                    level="warning",
                )
            return

        result = await memberships.update_many(
            {"_id": {"$in": [row["_id"] for row in owned]}},
            {"$set": {"roles": [role], "updated_at": now}},
        )
        if getattr(result, "matched_count", 0) != len(owned):
            # `owned` is ranked, so the row named here is the one auth reads.
            raise RoleRevocationFailed(
                f"role revocation for {resolved_user_id} in {academy_id} matched "
                f"{getattr(result, 'matched_count', 0)} of {len(owned)} membership rows "
                f"(primary {owned[0].get('membership_id')})"
            )

    async def _pull_membership_role(
        self,
        doc: dict[str, Any],
        *,
        role: Role,
        academy_id: str,
        now: datetime,
    ) -> None:
        """Revoke a single role from this academy's membership row(s).

        The removal twin of `_replace_membership_roles`, and load-bearing for
        the same reason: `DELETE /admin/users/{id}/roles/{role}` is the ONLY
        revocation the admin UI can perform (`change_role`, the endpoint the
        replacement path repairs, has no frontend caller), so this is the code
        path a real demotion actually takes.

        Before this, the mirror was a single `update_one` keyed on the exact
        resolved `user_id`, with no alias set and no result check. For exactly
        the population the replacement fix exists for — an account whose
        membership row is keyed by an alias (`auth_uid`/`firebase_uid`/`_id`)
        rather than the resolved `user_id` — it `$pull`ed nothing while the
        directory, the audit row and the UI all reported the role removed, and
        `LoadAuthClaims` (which resolves through the alias set) kept serving it.

        Resolution, ownership and the write check are identical to the
        replacement path; only the mutation differs (`$pull` one role instead
        of `$set` the whole array). A removal always drops a role, so the
        fail-closed branch is unconditional here rather than gated on
        `drops_a_role`.
        """
        memberships = self._db["academy_memberships"]
        aliases = list(self._membership_aliases(doc))
        rows = [
            row
            async for row in memberships.find(
                {"academy_id": academy_id, "user_id": {"$in": aliases}}
            )
        ]

        resolved_user_id = self._to_domain(doc).user_id
        owned: list[dict[str, Any]] = []
        skipped_foreign: list[dict[str, Any]] = []
        for row in rows:
            if await self._membership_is_foreign(row, doc):
                skipped_foreign.append(row)
                _log.error(
                    "role removal skipped a membership row owned by another account",
                    extra={
                        "academy_id": academy_id,
                        "user_id": resolved_user_id,
                        "membership_id": row.get("membership_id"),
                        "membership_user_id": row.get("user_id"),
                    },
                )
                capture_message(
                    "Identity alias collision on academy_memberships during role removal "
                    f"for {resolved_user_id} in {academy_id}",
                    level="error",
                )
                continue
            owned.append(row)
        owned.sort(key=lambda row: membership_match_rank(row, resolved_user_id))

        if skipped_foreign:
            raise RoleRevocationFailed(
                f"role removal for {resolved_user_id} in {academy_id} could not claim "
                f"{len(skipped_foreign)} alias-matched membership row(s) owned by another "
                f"account (first {skipped_foreign[0].get('membership_id')}); "
                "auth can still resolve them, so the old grant would stay live"
            )

        if not owned:
            _log.warning(
                "role removal matched no membership row to revoke",
                extra={
                    "academy_id": academy_id,
                    "user_id": resolved_user_id,
                    "aliases": aliases,
                    "removed_role": role,
                },
            )
            capture_message(
                f"Role removal for {resolved_user_id} in {academy_id} matched no "
                "academy_memberships row",
                level="warning",
            )
            return

        result = await memberships.update_many(
            {"_id": {"$in": [row["_id"] for row in owned]}},
            {"$pull": {"roles": role}, "$set": {"updated_at": now}},
        )
        if getattr(result, "matched_count", 0) != len(owned):
            raise RoleRevocationFailed(
                f"role removal for {resolved_user_id} in {academy_id} matched "
                f"{getattr(result, 'matched_count', 0)} of {len(owned)} membership rows "
                f"(primary {owned[0].get('membership_id')})"
            )

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

        # Write order follows the DIRECTION of the change, for exactly the
        # reasons spelled out on `change_role` above: `academy_memberships` —
        # not this `users` doc — is what `LoadAuthClaims` turns into request
        # claims, so a partial failure must never leave the membership wider
        # than the directory shows.
        #
        # `change_role` got that ordering; this function, the one the admin UI
        # can actually reach (`DELETE /admin/users/{id}/roles/{role}`), did
        # not. It wrote the directory first and mirrored afterwards, and
        # `_pull_membership_role` can raise — an alias-matched row owned by
        # another account, or a revocation write that did not land. Nothing
        # rolled the directory write back and the audit insert never ran, so
        # the account was listed as demoted, unaudited, and still holding live
        # admin claims, with no API-reachable remedy: a retry re-raises at the
        # same point forever, and the reconcile script withholds correction for
        # the alias-collision class (issue #591).
        if not adding:
            # Narrowing: revoke the membership FIRST, so a failure at any later
            # point can only leave effective access at what the actor asked for
            # or narrower. The revocation resolves through the full alias set
            # and checks its write, because this is the only revocation the
            # admin UI can perform and an exact-`user_id` `$pull` silently
            # no-ops on an alias-keyed row while reporting success everywhere.
            #
            # It is handed the BEFORE doc, exactly as `_replace_membership_roles`
            # is on the narrowing branch of `change_role`. That is safe because
            # it reads nothing but identity: `_membership_aliases` reads
            # `user_id`/`auth_uid`/`firebase_uid` (via `aliases_from_doc`) plus
            # the `_to_domain` fallback to `_id`, and `_membership_is_foreign`
            # reads `_to_domain(...).user_id` and `_id`. The directory `$set`
            # below touches only `role`, `roles` and `updated_at`, so before and
            # after resolve to the same aliases and the same membership rows.
            await self._pull_membership_role(before, role=role, academy_id=academy_id, now=now)

        # NOT fixed here: two admins removing two *different* roles still race.
        # Both read `roles`, both clear the last-role guard against their own
        # stale snapshot, and this `$set` is last-write-wins, while the two
        # membership `$pull`s compose to `roles: []` (issue #591, second race).
        # A compare-and-set on this write cannot close it, because the
        # membership `$pull` above has already run by the time we get here — the
        # CAS would refuse *after* the harm, not instead of it. Closing it needs
        # the guard on the `$pull` itself, or an admission gate that runs before
        # it; neither is demonstrable on mongomock. Left as-is deliberately.
        #
        # Widening writes the directory FIRST for the mirror-image reason:
        # granting the membership and then failing the `users` update would hand
        # out live claims the directory does not show — fail-open, and invisible
        # to anyone reading the admin UI. So the directory write sits between
        # the two membership branches and each direction gets its safe order.
        doc = await self.collection.find_one_and_update(
            {"academy_id": academy_id, **self._id_filter(user_id)},
            {"$set": {"role": primary, "roles": new_roles, "updated_at": now}},
            return_document=ReturnDocument.AFTER,
        )
        if doc is None:
            return None

        resolved_user_id = self._to_domain(doc).user_id
        if adding:
            # The additive path keeps the exact-id upsert: granting through a
            # row auth cannot reach is inert, not dangerous, and the upsert is
            # what creates the row for legacy accounts that have none.
            await self._db["academy_memberships"].update_one(
                {"academy_id": academy_id, "user_id": resolved_user_id},
                {
                    "$addToSet": {"roles": role},
                    "$set": {"updated_at": now},
                    "$setOnInsert": {
                        "membership_id": str(new_ulid()),
                        "academy_id": academy_id,
                        "user_id": resolved_user_id,
                        "invited_by": actor_id,
                        "invited_at": now,
                        "accepted_at": now,
                        "created_at": now,
                        "status": "active",
                    },
                },
                upsert=True,
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
