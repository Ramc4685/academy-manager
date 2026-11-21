"""Payout period versions and one line per occurrence per line set (L7 part 2).

Every payout period write is a compare-and-set on ``version``. Periods stored
before #1192 have no ``version``; this backfills ``0`` so the write filter can
match the field exactly.

A period's lines are one set per ``lines_version`` stamp, and the calculator
emits one line per occurrence. Before #1192 a recompute deleted and reinserted
lines with no guard, so two racing recomputes could leave an occurrence twice
in one set (paid twice). The unique index makes that a database rule. The
migration checks first and, on duplicates, raises naming them instead of
failing on an opaque DuplicateKeyError or silently picking a survivor: which
copy is right is a payroll decision. Missing ``lines_version`` (legacy lines
only; every write now stamps its set) indexes as null, the same set the
readers match.

Idempotent: the backfill only touches documents without a version and the
index spec is unchanged on a re-run.
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ASCENDING

version = "0239_payout_period_versions"

INDEX_NAME = "payout_period_lines_set_occurrence_unique"
_KEY = ("academy_id", "period_id", "lines_version", "occurrence_id")


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    duplicates = await (
        db.payout_period_lines.aggregate(
            [
                {
                    "$group": {
                        "_id": {field: f"${field}" for field in _KEY},
                        "count": {"$sum": 1},
                    }
                },
                {"$match": {"count": {"$gt": 1}}},
                {"$limit": 20},
            ]
        )
    ).to_list(None)
    if duplicates:
        named = ", ".join(
            "/".join(str(d["_id"].get(field)) for field in _KEY) + f" x{d['count']}"
            for d in duplicates
        )
        raise RuntimeError(
            "payout_period_lines has the same occurrence more than once in one line set "
            f"(academy/period/lines_version/occurrence): {named}. Decide which line is right, "
            "delete the others, recompute the period, then re-run this migration."
        )
    await db.payout_period_lines.create_index(
        [(field, ASCENDING) for field in _KEY], unique=True, name=INDEX_NAME
    )
    await db.payout_periods.update_many({"version": None}, {"$set": {"version": 0}})
