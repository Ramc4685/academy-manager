"""Indexes for ``crm_inquiry_ack_throttle``, the per-inbox inquiry
acknowledgement claim (AI strategy Phase 1 #2, security follow-up).

One row per ``(academy_id, mailbox, day)``: ``mailbox`` is the canonical inbox
(``shared.comms.mailbox.canonical_mailbox``: no ``+tag``, Gmail dots folded) and
``day`` the UTC ``YYYY-MM-DD`` of the claim. Two indexes:

* ``crm_inquiry_ack_throttle_academy_mailbox_day_unique``: the claim itself.
  The insert that succeeds owns the day's acknowledgement for that inbox; a
  concurrent or later one gets DuplicateKeyError and sends nothing.
* ``crm_inquiry_ack_throttle_claimed_ttl``: TTL on ``claimed_at``, 7 days. A
  row only matters on its own day (and for the past hour's per-academy
  count), so addresses are not kept longer than that.

New, empty collection: no data is read or changed. Idempotent:
``create_index`` with the same name and spec is a no-op.
"""

from __future__ import annotations

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0218_crm_inquiry_ack_throttle"

TTL_SECONDS = 7 * 24 * 60 * 60

#: (collection, name, keys, options). Exposed so tests can pin the shape.
INDEXES: list[tuple[str, str, list[tuple[str, int]], dict[str, Any]]] = [
    (
        "crm_inquiry_ack_throttle",
        "crm_inquiry_ack_throttle_academy_mailbox_day_unique",
        [("academy_id", 1), ("mailbox", 1), ("day", 1)],
        {"unique": True},
    ),
    (
        "crm_inquiry_ack_throttle",
        "crm_inquiry_ack_throttle_claimed_ttl",
        [("claimed_at", 1)],
        {"expireAfterSeconds": TTL_SECONDS},
    ),
]


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    for collection, name, keys, options in INDEXES:
        await db[collection].create_index(keys, name=name, **options)
