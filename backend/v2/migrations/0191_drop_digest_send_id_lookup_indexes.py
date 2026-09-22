"""Drop the stopgap ``digest_id`` lookup indexes on the digest-send collections (#880).

Migration 0189 re-keyed ``coach_digest_sends.digest_id`` and
``parent_digest_sends.digest_id`` from globally unique to unique per academy
(``*_digest_send_id_per_academy_uq`` on ``(academy_id, digest_id)``). At the
time ``mark_sent`` / ``mark_failed`` / ``mark_skipped_empty`` updated by a
bare ``digest_id``, which a compound index led by ``academy_id`` cannot serve,
so 0189 also kept a plain non-unique ``digest_id`` index on each collection
(``coach_digest_send_id_lookup``, ``parent_digest_send_id_lookup``).

Issue #880 scoped those three updates to ``{"academy_id": ..., "digest_id":
...}``, the shape the per-academy unique index serves: its partial filter is
``{"digest_id": {"$gt": ""}}``, which the planner bounds for an equality
lookup (0188 / #878), and ``test_partial_index_planner_usability`` asks a real
``mongod`` for exactly this lookup on both collections. The plain indexes are
therefore redundant and are dropped here.

Apply only AFTER the #880 code fix is deployed: with the old code still
running, dropping these would make every mark_* call a collection scan on
these two collections. Re-running is a no-op; an absent index is skipped.
"""

from __future__ import annotations

import logging

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0191_drop_digest_send_id_lookup_indexes"

log = logging.getLogger(__name__)

#: collection -> (stopgap index dropped here, per-academy index that now serves the lookup)
TARGETS: dict[str, tuple[str, str]] = {
    "coach_digest_sends": ("coach_digest_send_id_lookup", "coach_digest_send_id_per_academy_uq"),
    "parent_digest_sends": (
        "parent_digest_send_id_lookup",
        "parent_digest_send_id_per_academy_uq",
    ),
}


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    # Deploy-order note: this migration cannot tell whether the #880 code that
    # updates by (academy_id, digest_id) is already running; it only checks
    # that the per-academy index exists. The "code first, then 0191" order is
    # enforced by the release note / manual apply step, not by this function.
    for collection, (stopgap, per_academy) in TARGETS.items():
        coll = db[collection]
        existing = await coll.index_information()
        if per_academy not in existing:
            # 0189 has not run here; there is nothing for the lookup to fall
            # back on, so leave the stopgap in place rather than unindex it.
            log.warning("0191: %s missing on %s; keeping %s", per_academy, collection, stopgap)
            continue
        if stopgap in existing:
            await coll.drop_index(stopgap)
            log.info(
                "0191: dropped %s on %s; %s serves the lookup", stopgap, collection, per_academy
            )
