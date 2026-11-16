"""Website guest trial bookings (L9 A6-1).

A family can book a dated trial from the public page with no account: the
``trial_requests`` row carries ``contact_id`` (the CRM contact) instead of
``parent_user_id`` and a ``guest_slot`` seat number on its assigned date.

* ``trial_requests_guest_slot_unique``: one guest per seat number per class
  date. The booking inserts with the lowest free number and moves to the next
  on a duplicate, so two concurrent bookings of the last seat leave one row.
  Partial on ``{"guest_slot": {"$gte": 1}}``: account trials and guests whose
  date was cancelled (slot cleared) are not in it. Lookups of an occurrence's
  guests repeat that filter so the planner can use the index (#878).
* ``trial_requests_contact``: a mailbox's active guest bookings and the
  academy's daily guest count. Partial on ``{"contact_id": {"$gt": ""}}``.

No validator on ``trial_requests`` (none exists; #657). Idempotent.
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0236_trial_guest_bookings"


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    await db["trial_requests"].create_index(
        [("academy_id", 1), ("assigned_occurrence_id", 1), ("guest_slot", 1)],
        unique=True,
        partialFilterExpression={"guest_slot": {"$gte": 1}},
        name="trial_requests_guest_slot_unique",
    )
    await db["trial_requests"].create_index(
        [("academy_id", 1), ("contact_id", 1), ("created_at", -1)],
        partialFilterExpression={"contact_id": {"$gt": ""}},
        name="trial_requests_contact",
    )
