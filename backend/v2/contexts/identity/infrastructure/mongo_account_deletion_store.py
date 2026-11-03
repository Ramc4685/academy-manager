"""Mongo side of a self-service account deletion request (mobile M5, D1).

``account_deletion_requests`` is global, like ``users``: one Firebase account
spans academies and so does its deletion. Unique on ``user_id`` (migration
0216) so a double tap stores one request. Every read of tenant-owned data
(``session_occurrences``, ``audit_logs``) names its ``academy_id``.

Identity is matched through the full alias set (see
``domain/identity_aliases``): one Firebase account may back a separate
``users`` doc per academy, keyed by different ids, and a membership left on a
stale alias would keep that academy's door open.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from backend.v2.contexts.identity.domain.account_deletion import (
    AccountDeletionRequest,
    AccountMembership,
    DeletableAccount,
)
from backend.v2.contexts.identity.domain.identity_aliases import (
    aliases_from_doc,
    identity_aliases,
)
from backend.v2.contexts.identity.infrastructure.mongo_verification_email_cooldown import (
    _key as _cooldown_key,
)
from backend.v2.shared.ids import new_ulid

DELETED_NAME = "Deleted user"


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _to_request(doc: dict[str, Any]) -> AccountDeletionRequest:
    return AccountDeletionRequest(
        request_id=doc["request_id"],
        user_id=doc["user_id"],
        auth_uid=doc.get("auth_uid"),
        email=doc.get("email") or "",
        aliases=tuple(doc.get("aliases") or ()),
        academy_ids=tuple(doc.get("academy_ids") or ()),
        requested_at=_aware(doc["requested_at"]),
        execute_after=_aware(doc["execute_after"]),
        status=doc.get("status", "scheduled"),
    )


def _placeholder_email(request_id: str) -> str:
    # Unique per account (users.email may be indexed) and undeliverable (.invalid).
    return f"deleted+{request_id.lower()}@deleted.invalid"


class MongoAccountDeletionStore:
    def __init__(self, db: Any) -> None:
        self._db = db
        self._requests = db["account_deletion_requests"]

    async def load_account(self, *, user_id: str, email: str) -> DeletableAccount:
        docs = await (
            self._db["users"]
            .find(
                {
                    "$or": [
                        {"user_id": user_id},
                        {"auth_uid": user_id},
                        {"firebase_uid": user_id},
                        {"email": email},
                    ]
                }
            )
            .to_list(None)
        )
        aliases = identity_aliases(
            user_id, *(a for doc in docs for a in (*aliases_from_doc(doc), doc.get("_id")))
        )
        auth_uid = next(
            (str(doc[key]) for doc in docs for key in ("auth_uid", "firebase_uid") if doc.get(key)),
            user_id,
        )
        cursor = self._db["academy_memberships"].find({"user_id": {"$in": list(aliases)}})
        memberships = tuple(
            [
                AccountMembership(
                    academy_id=str(doc["academy_id"]),
                    roles=tuple(
                        [doc["roles"]]
                        if isinstance(doc.get("roles"), str)
                        else doc.get("roles") or ()
                    ),
                    status=str(doc.get("status", "active")),
                )
                async for doc in cursor
            ]
        )
        return DeletableAccount(
            user_id=user_id,
            auth_uid=auth_uid,
            email=email,
            aliases=aliases,
            memberships=memberships,
        )

    async def find_request(self, aliases: tuple[str, ...]) -> AccountDeletionRequest | None:
        doc = await self._requests.find_one({"user_id": {"$in": list(aliases)}})
        return _to_request(doc) if doc else None

    async def create_request(self, request: AccountDeletionRequest) -> AccountDeletionRequest:
        try:
            await self._requests.insert_one(
                {
                    "request_id": request.request_id,
                    "user_id": request.user_id,
                    "auth_uid": request.auth_uid,
                    "email": request.email,
                    "aliases": list(request.aliases),
                    "academy_ids": list(request.academy_ids),
                    "requested_at": request.requested_at,
                    "execute_after": request.execute_after,
                    "status": request.status,
                }
            )
        except DuplicateKeyError:
            existing = await self.find_request((request.user_id,))
            if existing is None:  # pragma: no cover - the key we collided on exists
                raise
            return existing
        return request

    async def other_active_owner_exists(self, *, academy_id: str, aliases: tuple[str, ...]) -> bool:
        return bool(
            await self._db["academy_memberships"].count_documents(
                {
                    "academy_id": academy_id,
                    "status": "active",
                    "roles": "owner",
                    "user_id": {"$nin": list(aliases)},
                },
                limit=1,
            )
        )

    async def upcoming_coaching_count(self, *, academy_id: str, aliases: tuple[str, ...]) -> int:
        # Same shape as MongoUserRepository._assert_no_future_coaching_work:
        # materialised occurrences carry the real dates; cancelled ones orphan nothing.
        ids = list(aliases)
        return int(
            await self._db["session_occurrences"].count_documents(
                {
                    "academy_id": academy_id,
                    "start_at": {"$gte": datetime.now(UTC)},
                    "status": {"$nin": ["cancelled", "completed"]},
                    "$or": [
                        {"scheduled_coach_id": {"$in": ids}},
                        {"actual_coach_id": {"$in": ids}},
                        {"assistant_coach_ids": {"$in": ids}},
                    ],
                }
            )
        )

    async def remove_memberships(self, *, aliases: tuple[str, ...], now: datetime) -> None:
        await self._db["academy_memberships"].update_many(
            {"user_id": {"$in": list(aliases)}, "status": {"$ne": "removed"}},
            {"$set": {"status": "removed", "updated_at": now}},
        )

    async def record_audit(
        self, *, academy_id: str, request: AccountDeletionRequest, roles: tuple[str, ...]
    ) -> None:
        await self._db["audit_logs"].insert_one(
            {
                "audit_id": str(new_ulid()),
                "academy_id": academy_id,
                "actor_id": request.user_id,
                "action": "user.deletion_requested",
                "entity_type": "user",
                "entity_id": request.user_id,
                "reason": "self-service account deletion",
                "created_at": request.requested_at,
                "metadata": {
                    "request_id": request.request_id,
                    "roles": list(roles),
                    "execute_after": request.execute_after,
                },
            }
        )

    # --- D3: carrying the deletion out ---

    async def due_requests(self, *, now: datetime, limit: int) -> list[AccountDeletionRequest]:
        cursor = (
            self._requests.find({"status": "scheduled", "execute_after": {"$lte": now}})
            .sort("execute_after", 1)
            .limit(limit)
        )
        return [_to_request(doc) async for doc in cursor]

    async def anonymise_identity(self, request: AccountDeletionRequest, *, now: datetime) -> None:
        ids = list(request.aliases)
        who: list[dict[str, Any]] = [
            {"user_id": {"$in": ids}},
            {"auth_uid": {"$in": ids}},
            {"firebase_uid": {"$in": ids}},
        ]
        if request.email:
            who += [{"email": request.email}, {"normalized_email": request.email.strip().lower()}]
        await self._db["users"].update_many(
            {"$or": who},
            {
                "$set": {
                    "display_name": DELETED_NAME,
                    "name": DELETED_NAME,
                    "full_name": DELETED_NAME,
                    "email": _placeholder_email(request.request_id),
                    "phone": None,
                    "status": "deleted",
                    "global_status": "deleted",
                    "is_active": False,
                    "deleted_at": now,
                    "updated_at": now,
                },
                # Unset, not overwritten: the sparse unique index allows many absent values.
                "$unset": {
                    "normalized_email": "",
                    "first_name": "",
                    "last_name": "",
                    "photo_url": "",
                },
            },
        )
        await self._db["parent_magic_links"].delete_many({"user_id": {"$in": ids}})
        await self._db["login_attempts"].delete_many({"user_id": {"$in": ids}})
        if request.email:
            await self._db["verification_email_cooldowns"].delete_many(
                {"_id": _cooldown_key(request.email)}
            )
        for academy_id in request.academy_ids:
            # Fixed id: a retry after a later failure rewrites, never duplicates.
            await self._db["audit_logs"].update_one(
                {"audit_id": f"deletion-completed-{request.request_id}-{academy_id}"},
                {
                    "$setOnInsert": {
                        "academy_id": academy_id,
                        "actor_id": "system:account-deletion",
                        "action": "user.deletion_completed",
                        "entity_type": "user",
                        "entity_id": request.user_id,
                        "reason": "self-service account deletion",
                        "created_at": now,
                        "metadata": {"request_id": request.request_id},
                    }
                },
                upsert=True,
            )

    async def mark_completed(self, request_id: str, *, now: datetime) -> None:
        # The address was kept only so the person could be reached during the
        # grace window; the ids stay so admins can trace what was erased.
        await self._requests.update_one(
            {"request_id": request_id},
            {
                "$set": {"status": "completed", "completed_at": now},
                "$unset": {"email": "", "last_error": ""},
            },
        )

    async def record_failure(
        self, request_id: str, *, step: str, error: str, now: datetime
    ) -> None:
        # Back off (1h doubling, capped at a day) so a request that keeps
        # failing stops filling every batch and starving the rest of the queue.
        doc = await self._requests.find_one_and_update(
            {"request_id": request_id},
            {
                "$set": {"last_error": {"step": step, "error": error[:500], "at": now}},
                "$inc": {"attempts": 1},
            },
            projection={"attempts": 1},
            return_document=ReturnDocument.AFTER,
        )
        attempts = int((doc or {}).get("attempts") or 1)
        delay = timedelta(hours=2 ** min(attempts - 1, 5))  # 2**5 h > a day: cap reached
        await self._requests.update_one(
            {"request_id": request_id},
            {"$set": {"execute_after": now + min(delay, timedelta(days=1))}},
        )

    async def has_active_account(self, *, academy_id: str, emails: list[str]) -> bool:
        """Whether any of ``emails`` signs in to ``academy_id`` (another guardian)."""
        normalized = sorted({e.strip().lower() for e in emails if e.strip()})
        if not normalized:
            return False
        users = await (
            self._db["users"]
            .find(
                {
                    "$or": [{"normalized_email": {"$in": normalized}}, {"email": {"$in": emails}}],
                    "status": {"$ne": "deleted"},
                }
            )
            .to_list(None)
        )
        ids = [a for doc in users for a in aliases_from_doc(doc)]
        return bool(
            ids
            and await self._db["academy_memberships"].count_documents(
                {"academy_id": academy_id, "user_id": {"$in": ids}, "status": "active"},
                limit=1,
            )
        )
