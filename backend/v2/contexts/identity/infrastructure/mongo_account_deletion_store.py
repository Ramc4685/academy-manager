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

from datetime import UTC, datetime
from typing import Any

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
from backend.v2.shared.ids import new_ulid


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
