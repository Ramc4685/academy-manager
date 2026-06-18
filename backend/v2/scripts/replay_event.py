"""Replay a dead-letter event by ID.

Usage::

    python -m backend.v2.scripts.replay_event <event_id>

Per docs/event-rules.md. Reads from ``dead_letter_events``, re-enqueues to
``outbox_events`` with a new event_id and a ``replayed_from`` reference, and
marks the dead-letter row resolved by replay.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient

from backend.v2.shared.config import get_settings
from backend.v2.shared.ids import new_ulid


async def _replay(event_id: str) -> None:
    settings = get_settings()
    client = AsyncIOMotorClient(settings.mongo_url)
    db = client[settings.mongo_db]
    try:
        new_event_id = await _replay_dead_letter(db, event_id)
        print(f"Replayed {event_id} as {new_event_id}")
    finally:
        client.close()


async def _replay_dead_letter(db: Any, event_id: str, *, new_event_id: str | None = None) -> str:
    dead = await db["dead_letter_events"].find_one({"event_id": event_id})
    if dead is None:
        raise LookupError(f"No dead-letter event found with event_id={event_id!r}")
    replay_event_id = new_event_id or str(new_ulid())
    now = datetime.now(UTC)
    new_doc = _replayed_outbox_doc(
        dead["event"],
        original_event_id=event_id,
        new_event_id=replay_event_id,
        now=now,
    )
    await db["outbox_events"].insert_one(new_doc)
    await db["dead_letter_events"].update_one(
        {"event_id": event_id},
        {
            "$set": {
                "replayed": True,
                "resolved": True,
                "replayed_at": now,
                "resolved_at": now,
                "replayed_as": replay_event_id,
                "resolution": "replayed_to_outbox",
            }
        },
    )
    return replay_event_id


def _replayed_outbox_doc(
    original: dict[str, Any],
    *,
    original_event_id: str,
    new_event_id: str,
    now: datetime,
) -> dict[str, Any]:
    new_doc = {
        **original,
        "event_id": new_event_id,
        "payload": _payload_with_event_id(original.get("payload"), new_event_id),
        "processed": False,
        "replayed_from": original_event_id,
        "status": "pending",
        "attempt_count": 0,
        "next_retry_at": now,
        "locked_until": None,
        "lock_owner": None,
        "last_error": None,
        "created_at": now,
        "updated_at": now,
    }
    new_doc.pop("_id", None)
    new_doc.pop("processed_at", None)
    return new_doc


def _payload_with_event_id(payload: object, new_event_id: str) -> object:
    if not isinstance(payload, dict):
        return payload
    cloned = dict(payload)
    if "event_id" in cloned:
        cloned["event_id"] = new_event_id
    return cloned


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python -m backend.v2.scripts.replay_event <event_id>", file=sys.stderr)
        sys.exit(2)
    try:
        asyncio.run(_replay(sys.argv[1]))
    except LookupError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
