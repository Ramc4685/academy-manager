"""Waiver lineage keys: several waivers can be live at once (Settings Phase 6).

A waiver is now a *lineage*: every version of "the same" waiver shares a
``lineage_key``. Publishing a version supersedes only the live rows of its own
lineage, so a Liability waiver and a Photo consent waiver stay live together.

Two changes, both idempotent and safe to re-run:

1. **Backfill.** Every ``waiver_templates`` row without a ``lineage_key`` gets
   ``"legacy"``. That is the one lineage all of an academy's pre-existing
   templates form (they used to replace each other, so they already were one
   waiver). Readers also fall back to ``"legacy"`` for a row that has no key, so
   this backfill is belt and braces, not a requirement for correctness. No other
   field is touched: assignment (``required`` / ``scope`` / ``program_ids``)
   reads its default at read time from ``assigned_to_registration``.

2. **Version uniqueness per waiver, not per academy.** The unique index
   ``waiver_templates_academy_version_unique`` on ``(academy_id, version)`` made
   "1" of a second waiver collide with "1" of the first. It becomes
   ``waiver_templates_academy_lineage_version_unique`` on ``(academy_id,
   lineage_key, version)``. It is partial on ``version > ""`` (a string), which
   also lets more than one *draft* (no version yet) exist, as the old index
   could not. The new index is created BEFORE the old one is dropped, so
   uniqueness is never absent. Every existing row is in the legacy lineage, so
   any set of rows the old index accepted the new one accepts too.

The index leads with ``academy_id`` (#849). The partial filter uses ``$gt: ""``
rather than ``$type`` (#878); nothing reads it with ``$or``.
"""

from __future__ import annotations

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import OperationFailure

version = "0211_waiver_lineage_keys"

LEGACY_LINEAGE_KEY = "legacy"
OLD_INDEX = "waiver_templates_academy_version_unique"
NEW_INDEX = "waiver_templates_academy_lineage_version_unique"
NEW_INDEX_KEYS: list[tuple[str, int]] = [("academy_id", 1), ("lineage_key", 1), ("version", 1)]
NEW_INDEX_OPTIONS: dict[str, Any] = {
    "unique": True,
    "partialFilterExpression": {"version": {"$gt": ""}},
}


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    templates = db["waiver_templates"]
    # ``None`` matches both a missing key and an explicit null.
    await templates.update_many(
        {"lineage_key": None}, {"$set": {"lineage_key": LEGACY_LINEAGE_KEY}}
    )
    await templates.create_index(NEW_INDEX_KEYS, name=NEW_INDEX, **NEW_INDEX_OPTIONS)
    try:
        await templates.drop_index(OLD_INDEX)
    except OperationFailure as exc:
        # 27 = IndexNotFound: already dropped (a re-run) or never created.
        if exc.code != 27:
            raise
