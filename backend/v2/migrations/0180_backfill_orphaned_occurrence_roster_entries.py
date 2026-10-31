"""Backfill: delete orphaned ``occurrence_roster_entries`` rows (issue #694).

Make-up and trial approvals write a one-time roster row keyed only to an
``occurrence_id`` — they hold no standing enrollment on the session. Before
this issue's fix, two gaps let those rows outlive the occurrence they were
written for:

- Whole-session cancel (``CancelSession``) only swept enrolled students'
  rows; a make-up/trial student was never in that set.
- ``maintain_session_occurrences`` soft-cancels or hard-deletes
  ``session_occurrences`` rows (single-date cancel, or a schedule/time edit
  that regenerates the deterministic ``occurrence_id``) without ever
  touching ``occurrence_roster_entries``.

Both write paths are fixed going forward; this is the one-off data-only
cleanup for rows already stranded. A row is orphaned if its
``occurrence_id`` no longer resolves to a ``session_occurrences`` document,
or resolves to one whose ``status`` is ``"cancelled"``. Tenant-scoped: the
lookup and delete both key on the entry's own ``academy_id``.

Production does NOT run migrations on boot (``V2_RUN_MIGRATIONS_ON_BOOT`` is
false there, #629): apply with ``run_pending_migrations`` by hand after
deploy.
"""

from __future__ import annotations

import logging
from collections import defaultdict

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0180_backfill_orphaned_occurrence_roster_entries"

log = logging.getLogger(__name__)


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    entries = [
        doc
        async for doc in db["occurrence_roster_entries"].find(
            {}, {"_id": 0, "entry_id": 1, "academy_id": 1, "occurrence_id": 1}
        )
    ]
    scanned = len(entries)
    if not entries:
        log.info("occurrence_roster_backfill: scanned=0 deleted=0")
        return

    # occurrence_id -> status, grouped by tenant so a lookup never crosses
    # academies.
    wanted: dict[str, set[str]] = defaultdict(set)
    for doc in entries:
        wanted[str(doc.get("academy_id") or "")].add(str(doc.get("occurrence_id") or ""))

    status_by_occurrence: dict[tuple[str, str], str] = {}
    for academy_id, occurrence_ids in wanted.items():
        cursor = db["session_occurrences"].find(
            {"academy_id": academy_id, "occurrence_id": {"$in": sorted(occurrence_ids)}},
            {"_id": 0, "occurrence_id": 1, "status": 1},
        )
        async for row in cursor:
            key = (academy_id, str(row.get("occurrence_id") or ""))
            status_by_occurrence[key] = str(row.get("status") or "scheduled")

    orphan_ids_by_academy: dict[str, list[str]] = defaultdict(list)
    for doc in entries:
        academy_id = str(doc.get("academy_id") or "")
        occurrence_id = str(doc.get("occurrence_id") or "")
        status = status_by_occurrence.get((academy_id, occurrence_id))
        if status is None or status == "cancelled":
            orphan_ids_by_academy[academy_id].append(str(doc["entry_id"]))

    deleted = 0
    for academy_id, entry_ids in orphan_ids_by_academy.items():
        result = await db["occurrence_roster_entries"].delete_many(
            {"academy_id": academy_id, "entry_id": {"$in": entry_ids}}
        )
        deleted += int(result.deleted_count)

    log.info("occurrence_roster_backfill: scanned=%d deleted=%d", scanned, deleted)
