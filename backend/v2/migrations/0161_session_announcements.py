"""Index for session-scoped announcement reads (#614).

Session announcements are stored in the existing ``messages`` collection, so
this migration adds an index and nothing else — there is no data migration and
none is needed. The new fields (``scope_id``, ``urgency``, ``deleted_at``) are
read through ``doc.get`` defaults, and the visibility predicate matches
``scope_type: {"$ne": "session"}`` for the academy-wide branch, which in Mongo
also matches a missing or null field. Every message written before #614
therefore behaves exactly as it did.

Two reads need serving:

* the parent/coach inbox clause ``{kind, scope_type, scope_id: {$in: [...]}}``,
  which runs on the most-polled endpoint in the product;
* the per-session history ``{kind, scope_type, scope_id}`` sorted by
  ``created_at`` descending.

One compound index ``(academy_id, scope_type, scope_id, created_at desc)``
covers both. ``academy_id`` leads because every query is tenant-scoped by
``TenantScopedRepository``. The academy-wide announcement clause is still
served by ``kind_timeline`` from migration 0060.
"""

from __future__ import annotations

import logging
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING

version = "0161_session_announcements"

log = logging.getLogger(__name__)

_INDEX_NAME = "session_announcement_timeline"


async def up(db: AsyncIOMotorDatabase[Any]) -> None:
    await db["messages"].create_index(
        [
            ("academy_id", ASCENDING),
            ("scope_type", ASCENDING),
            ("scope_id", ASCENDING),
            ("created_at", DESCENDING),
        ],
        name=_INDEX_NAME,
    )
    log.info("Created index %s on messages", _INDEX_NAME)
