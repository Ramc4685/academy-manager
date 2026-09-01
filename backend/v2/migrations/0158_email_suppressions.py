"""Email suppression list + provider webhook event log (issue #556).

Neither collection is tenant-scoped, and that is the point: the Resend sender
domain is shared by every academy, so a hard bounce seen under one tenant must
stop every tenant from mailing the same address. ``email_provider_events`` is
the Stripe-style idempotency log for the inbound webhook.
"""

from __future__ import annotations

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0158_email_suppressions"

SUPPRESSIONS = "email_suppressions"
PROVIDER_EVENTS = "email_provider_events"


async def up(db: AsyncIOMotorDatabase[Any]) -> None:
    suppressions = db[SUPPRESSIONS]
    # The address IS the identity: upserts key on it, so a repeat bounce bumps
    # last_seen_at and escalates the reason instead of growing a second row.
    await suppressions.create_index(
        "email",
        unique=True,
        name="email_suppressions_email_unique",
    )
    # Admin list: "most recent bounces first", optionally narrowed by reason.
    await suppressions.create_index(
        [("reason", 1), ("last_seen_at", -1)],
        name="email_suppressions_reason_recent",
    )

    events = db[PROVIDER_EVENTS]
    # The duplicate-key error on this index is the webhook's idempotency guard.
    await events.create_index(
        "event_id",
        unique=True,
        name="email_provider_events_event_id_unique",
    )
    await events.create_index(
        [("received_at", -1)],
        name="email_provider_events_recent",
    )
