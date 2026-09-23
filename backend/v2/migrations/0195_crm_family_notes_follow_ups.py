"""Create the indexes for ``family_notes`` and ``family_follow_ups`` (People CRM Phase 4a).

Team notes and follow-ups on a family record (docs/design/people-crm/
engineering-spec.md §5; contract in ``backend/v2/contexts/crm/README.md``).
New collections, no data to move: Mongo creates each on the first
``create_index``.

Every index leads with ``academy_id`` (#849). The two unique indexes make a
note or follow-up id unique per academy, so a duplicate id is rejected by the
store, not by a read-then-insert. The lookup indexes serve the family record's
lists (``parent_id`` newest first), one assignee's queue ("My follow-ups",
``assignee_user_id`` + ``status`` + ``due_on``) and the whole team's queue
(``status`` + ``due_on``). None is partial, so there is no ``$type`` /
``$exists`` filter to trip the planner (#878).

No ``$jsonSchema`` validator, as with 0192: the shape is new and a dormant
validator rejects writes anywhere (#657). Add one in a later migration once
the Phase 4 fields (``pinned``, ``student_id``, ``source``) have settled.

Idempotent: ``create_index`` with the same name and spec is a no-op.
"""

from __future__ import annotations

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0195_crm_family_notes_follow_ups"

#: (collection, name, keys, options). Exposed so the unit test pins the shapes.
INDEXES: list[tuple[str, str, list[tuple[str, int]], dict[str, Any]]] = [
    (
        "family_notes",
        "family_notes_academy_note_unique",
        [("academy_id", 1), ("note_id", 1)],
        {"unique": True},
    ),
    (
        "family_notes",
        "family_notes_academy_parent_created",
        [("academy_id", 1), ("parent_id", 1), ("created_at", -1)],
        {},
    ),
    (
        "family_follow_ups",
        "family_follow_ups_academy_follow_up_unique",
        [("academy_id", 1), ("follow_up_id", 1)],
        {"unique": True},
    ),
    (
        "family_follow_ups",
        "family_follow_ups_academy_parent_created",
        [("academy_id", 1), ("parent_id", 1), ("created_at", -1)],
        {},
    ),
    (
        "family_follow_ups",
        "family_follow_ups_academy_assignee_status_due",
        [("academy_id", 1), ("assignee_user_id", 1), ("status", 1), ("due_on", 1)],
        {},
    ),
    (
        "family_follow_ups",
        "family_follow_ups_academy_status_due",
        [("academy_id", 1), ("status", 1), ("due_on", 1)],
        {},
    ),
]


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    for collection, name, keys, options in INDEXES:
        await db[collection].create_index(keys, name=name, **options)
