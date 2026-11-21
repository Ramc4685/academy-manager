"""Scope the evening-win and report-card claim ids per academy (#849).

0213 and 0214 copied the pre-#849 shape: a global unique index on the bare
``digest_id``. Every write filters ``{academy_id, digest_id}``
(``MongoParentDigestSendRepository``), so uniqueness belongs to that pair,
exactly as 0189 did for the coach and parent digests.

Pre-flight both collections first and raise with the offenders: a duplicate
pair means the data needs a human, and the old indexes are left in place.
Then create the per-academy index before dropping the global one, so
uniqueness is never absent. The partial filter is ``$gt ""`` (never
``$type``) so the planner can serve the scoped lookup.
"""

from __future__ import annotations

import logging
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0244_win_report_card_send_ids_per_academy"

log = logging.getLogger(__name__)

#: (collection, old global index, new per-academy index)
TARGETS: list[tuple[str, str, str]] = [
    ("parent_win_sends", "parent_win_send_id_unique", "parent_win_send_id_per_academy_uq"),
    (
        "parent_report_card_sends",
        "parent_report_card_send_id_unique",
        "parent_report_card_send_id_per_academy_uq",
    ),
]


async def _duplicate_pairs(collection) -> list[dict[str, Any]]:  # type: ignore[no-untyped-def]
    cursor = collection.aggregate(
        [
            {"$match": {"digest_id": {"$gt": ""}}},
            {
                "$group": {
                    "_id": {"academy_id": "$academy_id", "id": "$digest_id"},
                    "count": {"$sum": 1},
                }
            },
            {"$match": {"count": {"$gt": 1}}},
            {"$limit": 20},
        ]
    )
    return [doc async for doc in cursor]


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    problems: list[str] = []
    for collection, _old, new_index in TARGETS:
        duplicates = await _duplicate_pairs(db[collection])
        if duplicates:
            offenders = ", ".join(
                f"{row['_id'].get('academy_id')!r}/{row['_id'].get('id')!r} x{row['count']}"
                for row in duplicates
            )
            problems.append(
                f"{collection} has duplicate (academy_id, digest_id) pairs, so "
                f"{new_index} cannot be created (up to 20 shown): {offenders}"
            )
    if problems:
        raise RuntimeError(
            "0244 aborted before changing any index. Deduplicate these first: "
            + "; ".join(problems)
            + ". The old global indexes have been left in place."
        )

    for collection, old_index, new_index in TARGETS:
        coll = db[collection]
        await coll.create_index(
            [("academy_id", 1), ("digest_id", 1)],
            unique=True,
            partialFilterExpression={"digest_id": {"$gt": ""}},
            name=new_index,
        )
        if old_index in await coll.index_information():
            await coll.drop_index(old_index)
            log.info("0244: dropped globally-unique %s in favour of %s", old_index, new_index)
