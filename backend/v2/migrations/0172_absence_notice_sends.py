"""Absence-notice send claims (issue #616).

Adds the claim collection behind ``composition/absence_notifications.py``:
one row per (notice, audience) for the staff alert and the parent
confirmation that now fire when an absence notice is submitted. Unique on
``(academy_id, notice_id, audience)``. The claim itself
(``digest_claim.claim_digest_send``) is already safe without this index —
the index is what keeps the collection from growing near-duplicate rows
under a stuck or retried request, exactly as 0170 did for the hold notices.

No data change and no validator change: ``absence_notices`` is untouched.

Production does NOT run migrations on boot (``V2_RUN_MIGRATIONS_ON_BOOT`` is
false there, #629): apply with ``run_pending_migrations`` by hand after
deploy. Until then the adapter still sends exactly once per notice; only
the index is missing.
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0172_absence_notice_sends"


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    await db["absence_notice_sends"].create_index(
        [("academy_id", 1), ("notice_id", 1), ("audience", 1)],
        unique=True,
        name="absence_notice_sends_key_unique",
    )
