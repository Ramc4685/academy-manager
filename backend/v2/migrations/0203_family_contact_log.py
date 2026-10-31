"""Indexes for ``family_contact_log``, the staff-logged contacts of the family
Messages tab (People CRM Phase 6, roadmap L4c).

A staff member logs a WhatsApp, SMS or email sent from their own app (the
``wa.me`` / ``sms:`` / ``mailto:`` handoff), a call, or a talk in person. The
Messages tab reads one family's rows newest first, and a ``not_logged``
handoff is completed by its ``log_id``:

* ``family_contact_log_academy_log_id_unique``: ``(academy_id, log_id)``,
  unique; the id lookup of "complete this log" and a guard against a reused id.
* ``family_contact_log_academy_parent_created``: ``(academy_id, parent_id,
  created_at desc)``; the family thread read.

Both lead with ``academy_id`` (#849); no partial filter; nothing queries it
with ``$or``. New, empty collection: no data is read or changed. Idempotent:
``create_index`` with the same name and spec is a no-op.
"""

from __future__ import annotations

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0203_family_contact_log"

#: (collection, name, keys, options). Exposed so the unit test pins the shape.
INDEXES: list[tuple[str, str, list[tuple[str, int]], dict[str, Any]]] = [
    (
        "family_contact_log",
        "family_contact_log_academy_log_id_unique",
        [("academy_id", 1), ("log_id", 1)],
        {"unique": True},
    ),
    (
        "family_contact_log",
        "family_contact_log_academy_parent_created",
        [("academy_id", 1), ("parent_id", 1), ("created_at", -1)],
        {},
    ),
]


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    for collection, name, keys, options in INDEXES:
        await db[collection].create_index(keys, name=name, **options)
