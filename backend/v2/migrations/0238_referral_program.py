"""Referral programme (L9 C2).

``referral_codes`` (one stable code per parent per academy):

* ``referral_code_parent_unique``: (academy_id, parent_id), so a parent is
  minted one code even when two first views race.
* ``referral_code_unique``: (academy_id, referral_code), the lookup that turns
  an attribution code into the referring parent, and the refusal that makes a
  collision mint another code.

``referrals`` (one row per referred family):

* ``referral_referred_parent_unique``: (academy_id, referred_parent_id), so a
  family is recorded once whichever source (website inquiry or registration)
  or run sees it first.
* ``referral_reward_slot_unique``: (academy_id, reward_key), the referrer's
  yearly reward slots ``"<parent>:<year>:<n>"``, n in 1..cap, so concurrent
  grants cannot pass the yearly cap.
* ``referral_status_created``: the daily sweep's pending read and the admin
  list.
* ``referral_referrer``: a referrer's slots this year and rewards earned.

Every unique index is partial on ``{"<field>": {"$gt": ""}}``, never
``$type`` (#878), so its equality lookups are index seeks. Before building a
unique index the migration looks for existing duplicates and raises naming
them instead of letting the build fail half-way or skipping it. Idempotent.
"""

from __future__ import annotations

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0238_referral_program"

#: (collection, index name, key fields, the field the partial filter is on)
_UNIQUE: tuple[tuple[str, str, tuple[str, ...], str], ...] = (
    ("referral_codes", "referral_code_parent_unique", ("academy_id", "parent_id"), "parent_id"),
    ("referral_codes", "referral_code_unique", ("academy_id", "referral_code"), "referral_code"),
    (
        "referrals",
        "referral_referred_parent_unique",
        ("academy_id", "referred_parent_id"),
        "referred_parent_id",
    ),
    ("referrals", "referral_reward_slot_unique", ("academy_id", "reward_key"), "reward_key"),
)


async def _duplicates(db: Any, collection: str, keys: tuple[str, ...], field: str) -> list[Any]:
    pipeline = [
        {"$match": {field: {"$gt": ""}}},
        {"$group": {"_id": {k: f"${k}" for k in keys}, "n": {"$sum": 1}}},
        {"$match": {"n": {"$gt": 1}}},
        {"$limit": 5},
    ]
    return [row["_id"] async for row in db[collection].aggregate(pipeline)]


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    for collection, name, keys, field in _UNIQUE:
        clashes = await _duplicates(db, collection, keys, field)
        if clashes:
            raise RuntimeError(
                f"0238: {collection} already holds duplicate {list(keys)} values, "
                f"so {name} cannot be built: {clashes}"
            )
        await db[collection].create_index(
            [(key, 1) for key in keys],
            unique=True,
            partialFilterExpression={field: {"$gt": ""}},
            name=name,
        )
    await db["referrals"].create_index(
        [("academy_id", 1), ("status", 1), ("created_at", 1)],
        name="referral_status_created",
    )
    await db["referrals"].create_index(
        [("academy_id", 1), ("referrer_parent_id", 1), ("reward_year", 1)],
        name="referral_referrer",
    )
