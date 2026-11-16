"""Automatic sibling discount decisions (L9 C1).

``sibling_discount_decisions`` is insert-once: the monthly resolver records
whether an enrollment-month gets the sibling discount the first time it
prices that month, and every later pricing of the month (retries, orphan
recovery, admin "Bill this month") reuses the row, even after the setting or
the family changes.

* ``sibling_decision_enrollment_period_unique``: one decision per enrollment
  per billing month; the resolver's lookup key, and the refusal that makes
  two concurrent runs converge on one decision.
* ``students.parent_user_children``: (academy_id, parent_user_id), the twin of
  0010's ``parent_children``, so the resolver's sibling lookup by either
  parent field is an index seek. Not partial: the lookup is an ``$in`` of
  equalities, which a ``$type`` partial index would not serve (#878).

No validator (none needed; #657). Idempotent.
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0237_sibling_discount_decisions"


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    await db["sibling_discount_decisions"].create_index(
        [("academy_id", 1), ("enrollment_id", 1), ("period", 1)],
        unique=True,
        name="sibling_decision_enrollment_period_unique",
    )
    await db["students"].create_index(
        [("academy_id", 1), ("parent_user_id", 1)],
        name="parent_user_children",
    )
