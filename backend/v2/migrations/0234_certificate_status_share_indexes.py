"""Certificate status, one issued certificate per level, share tokens (L5 part B).

1. Backfills ``status: "issued"`` on every certificate without one. Reads
   already treat a missing status as issued; the backfill is what lets the
   partial index below see the old rows.
2. Pre-flights duplicate issued certificates for the same
   ``(academy_id, student_id, program_id, level_id)``. If any exist it aborts
   before creating an index, naming the offenders, as 0189 does: revoke the
   extra certificate (``status: "revoked"``) and deploy again.
3. ``certs_one_issued_per_level_uq``: unique on that key, partial on
   ``{status: "issued"}``, so a revoked certificate never blocks the fresh
   one a re-earned level issues.
4. ``certs_share_token_per_academy_uq``: unique ``(academy_id, share_token)``,
   partial on ``{share_token: {"$gt": ""}}`` (not ``$type``: the planner
   ignores ``$type`` partials for equality lookups, see 0188). The public
   share lookup resolves the academy from the request host first, then looks
   the token up within it, so this key is tenant-first like every other.

Re-running is a no-op.
"""

from __future__ import annotations

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0234_certificate_status_share_indexes"

ONE_ISSUED_INDEX = "certs_one_issued_per_level_uq"
SHARE_TOKEN_INDEX = "certs_share_token_per_academy_uq"
LEVEL_KEY = ("academy_id", "student_id", "program_id", "level_id")


async def _duplicate_issued(certs: Any) -> list[dict[str, Any]]:
    cursor = certs.aggregate(
        [
            {"$match": {"status": "issued"}},
            {
                "$group": {
                    "_id": {field: f"${field}" for field in LEVEL_KEY},
                    "count": {"$sum": 1},
                    "cert_numbers": {"$push": "$cert_number"},
                }
            },
            {"$match": {"count": {"$gt": 1}}},
            {"$limit": 20},
        ]
    )
    return [doc async for doc in cursor]


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    certs = db["skill_certificates"]
    await certs.update_many({"status": {"$exists": False}}, {"$set": {"status": "issued"}})

    duplicates = await _duplicate_issued(certs)
    if duplicates:
        offenders = "; ".join(
            "/".join(str(row["_id"].get(field)) for field in LEVEL_KEY)
            + f": {', '.join(map(str, row['cert_numbers']))}"
            for row in duplicates
        )
        raise RuntimeError(
            "0234 aborted before creating any index: these students hold more than one "
            f"issued certificate for the same level (up to 20 shown): {offenders}. "
            "Revoke the extras (set status to 'revoked') and deploy again."
        )

    await certs.create_index(
        [(field, 1) for field in LEVEL_KEY],
        unique=True,
        partialFilterExpression={"status": "issued"},
        name=ONE_ISSUED_INDEX,
    )
    await certs.create_index(
        [("academy_id", 1), ("share_token", 1)],
        unique=True,
        partialFilterExpression={"share_token": {"$gt": ""}},
        name=SHARE_TOKEN_INDEX,
    )
