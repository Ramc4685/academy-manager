"""Grant ``owner`` to every existing ``admin`` membership.

The owner/admin split (spec ``2026-09-04-role-model-and-screens-design.md``)
moves money governance — refunds, credits, pricing, payouts, financial
reports, audit, granting admin/owner — behind ``require_owner``. Before it,
``admin`` could do all of that, so every admin membership that exists at
deploy time is made an owner too: nobody loses access, and the split applies
to admins invited from now on.

Writes the ``academy_memberships`` row first (that is what ``LoadAuthClaims``
turns into request claims) and then mirrors ``owner`` into the legacy
``users`` doc for the same user in the same academy, matching how
``MongoUserRepository._modify_roles`` dual-writes a role grant. A ``users``
doc that only carries the legacy single ``role`` field gets its ``roles``
list materialised so ``admin`` is not lost. Idempotent: a membership that
already holds ``owner`` is skipped, and ``$addToSet`` can never duplicate.

Does NOT run on boot in production (``V2_RUN_MIGRATIONS_ON_BOOT`` is false,
#629); apply it by hand before or right after the deploy that ships the
split, or existing admins lose their money screens until it runs.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase

log = logging.getLogger(__name__)

version = "0165_grant_owner_to_existing_admins"

_ADMINS_WITHOUT_OWNER = {"$and": [{"roles": "admin"}, {"roles": {"$ne": "owner"}}]}


def _user_filter(academy_id: str, user_id: str) -> dict[str, Any]:
    """Same alias set ``MongoUserRepository._id_filter`` resolves a user by."""
    ids: list[object] = [user_id]
    if ObjectId.is_valid(user_id):
        ids.append(ObjectId(user_id))
    return {
        "academy_id": academy_id,
        "$or": [
            {"user_id": user_id},
            {"auth_uid": user_id},
            {"firebase_uid": user_id},
            {"_id": {"$in": ids}},
        ],
    }


async def _mirror_owner_into_users(
    users: AsyncIOMotorCollection[Any], *, academy_id: str, user_id: str, now: datetime
) -> int:
    mirrored = 0
    async for doc in users.find(_user_filter(academy_id, user_id)):
        roles = list(doc.get("roles") or ([doc["role"]] if doc.get("role") else []))
        if "owner" in roles:
            continue
        roles.append("owner")
        result = await users.update_one(
            {"_id": doc["_id"]}, {"$set": {"roles": roles, "updated_at": now}}
        )
        mirrored += result.modified_count
    return mirrored


async def up(db: AsyncIOMotorDatabase[Any]) -> None:
    now = datetime.now(UTC)
    memberships = db["academy_memberships"]
    users = db["users"]

    granted = 0
    mirrored = 0
    async for membership in memberships.find(_ADMINS_WITHOUT_OWNER):
        result = await memberships.update_one(
            {"_id": membership["_id"]},
            {"$addToSet": {"roles": "owner"}, "$set": {"updated_at": now}},
        )
        granted += result.modified_count
        academy_id = membership.get("academy_id")
        user_id = membership.get("user_id")
        if not academy_id or not user_id:
            log.warning(
                "0165: membership %s has no academy_id/user_id; users doc not mirrored",
                membership.get("membership_id") or membership["_id"],
            )
            continue
        mirrored += await _mirror_owner_into_users(
            users, academy_id=academy_id, user_id=user_id, now=now
        )

    log.info(
        "0165: granted owner to %d admin membership(s); mirrored into %d users doc(s)",
        granted,
        mirrored,
    )
