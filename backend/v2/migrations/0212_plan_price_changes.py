"""Indexes for ``plan_price_changes`` (Settings overhaul Phase 6 PR 26).

A plan price change the owner scheduled from a future month. Four indexes:

* ``plan_price_changes_academy_pending_plan_unique``: ``(academy_id,
  pending_plan_id)``, unique, partial on ``pending_plan_id`` ``$gt ""``.
  ``pending_plan_id`` is set only while a change is ``scheduled`` and unset
  when it is applied or cancelled, so this is "one pending change per plan"
  held by the database under two concurrent applies. ``$gt ""``, never
  ``$type`` (the planner ignores ``$type`` partial indexes for equality).
* ``plan_price_changes_academy_session_status``: ``(academy_id, session_ids,
  status)`` (multikey); the lookup every charge path makes for "does a
  change cover this class".
* ``plan_price_changes_academy_change_unique``: ``(academy_id, change_id)``,
  unique; cancel and the scheduler's writes go by change id.
* ``plan_price_changes_academy_edit_sessions``: ``(academy_id,
  edit.session_ids)`` (multikey); the other half of a registration quote's
  fence read (a class an open owner edit is about to add to a change).

All lead with ``academy_id`` (#849). New, empty collection: no data is read
or changed. Idempotent: ``create_index`` with the same name and spec is a
no-op, so re-running is safe.
"""

from __future__ import annotations

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0212_plan_price_changes"

#: (collection, name, keys, options). Exposed so the unit test pins the shape.
INDEXES: list[tuple[str, str, list[tuple[str, int]], dict[str, Any]]] = [
    (
        "plan_price_changes",
        "plan_price_changes_academy_pending_plan_unique",
        [("academy_id", 1), ("pending_plan_id", 1)],
        {"unique": True, "partialFilterExpression": {"pending_plan_id": {"$gt": ""}}},
    ),
    (
        "plan_price_changes",
        "plan_price_changes_academy_session_status",
        [("academy_id", 1), ("session_ids", 1), ("status", 1)],
        {},
    ),
    (
        "plan_price_changes",
        "plan_price_changes_academy_change_unique",
        [("academy_id", 1), ("change_id", 1)],
        {"unique": True},
    ),
    (
        "plan_price_changes",
        "plan_price_changes_academy_edit_sessions",
        [("academy_id", 1), ("edit.session_ids", 1)],
        {},
    ),
]


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    for collection, name, keys, options in INDEXES:
        await db[collection].create_index(keys, name=name, **options)
