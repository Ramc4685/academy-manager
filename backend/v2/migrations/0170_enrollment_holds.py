"""Enrollment holds + departure policy (issue #697).

No change to the ``enrollments`` collection's own $jsonSchema validator: its
``status`` field has always been an unconstrained ``bsonType: "string"``
(migration 0132), so ``held``/``reclaim_pending`` and the seven new hold
fields need no schema widening — the #657/#658 failure mode (a dormant enum
that 500s in production) does not apply here. Likewise ``enrollment_events``'
``event_type`` is an unconstrained string (0133).

This migration only adds collections and indexes:

* ``enrollment_departure_policies`` — one doc per academy, unique on
  ``academy_id``.
* ``enrollment_hold_notice_sends`` — the claim collection for both hold
  emails (reclaim notice + monthly reminder), unique on
  ``(academy_id, enrollment_id, notice_key)`` per the departures design
  contract §4.4. The claim (``digest_claim.claim_digest_send``) is already
  safe without this index; the index is what keeps the collection from
  growing an unbounded number of near-duplicate rows under a stuck job.
* A compound index on ``enrollments`` backing the reclaim CAS's
  deterministic sort (contract §3.4):
  ``(academy_id, session_id, status, hold_started_at, enrollment_id)``.
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0170_enrollment_holds"


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    await db["enrollment_departure_policies"].create_index(
        "academy_id",
        unique=True,
        name="enrollment_departure_policies_academy_id_unique",
    )
    await db["enrollment_hold_notice_sends"].create_index(
        [("academy_id", 1), ("enrollment_id", 1), ("notice_key", 1)],
        unique=True,
        name="enrollment_hold_notice_sends_key_unique",
    )
    await db["enrollments"].create_index(
        [
            ("academy_id", 1),
            ("session_id", 1),
            ("status", 1),
            ("hold_started_at", 1),
            ("enrollment_id", 1),
        ],
        name="enrollments_hold_reclaim_order",
    )
