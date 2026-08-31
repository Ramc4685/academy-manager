"""Indexes for the #549 checkout-orphan work.

Two additions:

* ``onboarding_applications`` — ``get_by_payment_id`` is the ONLY handle
  ``checkout.session.completed`` has back to an application, and it now matches
  the archived ``superseded_payment_ids`` as well as the live ``payment_id``.
  Neither field was indexed, so that lookup collection-scanned on every payment
  webhook; the ``$or`` makes an index union possible, which needs both legs
  indexed to be worth anything.

* ``unretired_checkout_sessions`` — the reconciliation worklist of superseded
  Checkout Sessions that stayed payable because Stripe could not be reached.
  Keyed by session id (one row per session, upserted on repeat failures) and
  read oldest-first by whatever sweeps it.
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0157_checkout_orphan_reconciliation_indexes"


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    apps = db["onboarding_applications"]
    await apps.create_index(
        [("academy_id", 1), ("payment_id", 1)],
        name="academy_payment_id",
        partialFilterExpression={"payment_id": {"$type": "string"}},
    )
    await apps.create_index(
        [("academy_id", 1), ("superseded_payment_ids", 1)],
        name="academy_superseded_payment_ids",
    )

    unretired = db["unretired_checkout_sessions"]
    await unretired.create_index(
        [("academy_id", 1), ("checkout_session_id", 1)],
        unique=True,
        name="academy_checkout_session_unique",
    )
    await unretired.create_index(
        [("academy_id", 1), ("first_seen_at", 1)],
        name="academy_oldest_first",
    )
