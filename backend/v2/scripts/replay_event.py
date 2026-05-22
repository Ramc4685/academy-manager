"""Replay a dead-letter event by ID.

Usage::

    python -m backend.v2.scripts.replay_event <event_id>

Per docs/event-rules.md. Reads from ``dead_letter_events``, re-enqueues to
``outbox_events`` with a new event_id and a ``replayed_from`` reference, and
marks the dead-letter row as ``replayed``.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime

from motor.motor_asyncio import AsyncIOMotorClient

from backend.v2.shared.config import get_settings
from backend.v2.shared.ids import new_ulid


async def _replay(event_id: str) -> None:
    settings = get_settings()
    client = AsyncIOMotorClient(settings.mongo_url)
    db = client[settings.mongo_db]
    try:
        dead = await db["dead_letter_events"].find_one({"event_id": event_id})
        if dead is None:
            print(f"No dead-letter event found with event_id={event_id!r}", file=sys.stderr)
            sys.exit(2)
        original = dead["event"]
        new_event_id = str(new_ulid())
        new_doc = {
            **original,
            "event_id": new_event_id,
            "processed": False,
            "replayed_from": event_id,
            "created_at": datetime.now(UTC),
        }
        new_doc.pop("processed_at", None)
        await db["outbox_events"].insert_one(new_doc)
        await db["dead_letter_events"].update_one(
            {"event_id": event_id},
            {
                "$set": {
                    "replayed": True,
                    "replayed_at": datetime.now(UTC),
                    "replayed_as": new_event_id,
                }
            },
        )
        print(f"Replayed {event_id} as {new_event_id}")
    finally:
        client.close()


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python -m backend.v2.scripts.replay_event <event_id>", file=sys.stderr)
        sys.exit(2)
    asyncio.run(_replay(sys.argv[1]))


if __name__ == "__main__":
    main()
