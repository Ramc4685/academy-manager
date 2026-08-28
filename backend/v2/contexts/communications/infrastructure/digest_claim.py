"""Shared retry-claim rule for the coach and parent digest repositories.

The two digest collections are deliberate near-duplicates (different recipient
field, different collection), but the rule that decides *when a failed send may
be tried again* is a correctness invariant, not per-collection detail — it is
what keeps "retry a failure" from becoming "send twice". It lives here once so
neither repository can drift from it (issue #435).

The re-claim is a single conditional ``find_one_and_update``:

* it matches **only** ``status == "failed"`` — a ``sent`` row can never be
  re-claimed (no duplicate email), and an in-flight ``queued`` row is left
  alone (a crashed mid-send run stays visible rather than being re-sent);
* it skips rows marked ``retryable: false`` — a recipient with no e-mail
  address cannot be helped by trying again, and retrying would cost three plan
  generations a day forever;
* it matches only rows with attempts remaining, so a permanently broken
  recipient stops after ``MAX_DIGEST_SEND_ATTEMPTS`` instead of burning an
  attempt every hour for the rest of the day;
* being one atomic update, two concurrent scheduler ticks cannot both win it.

Rows written before migration 0153 carry no ``attempt_count``; the migration
backfills them, and ``_from_doc`` defaults a missing value to 1 so a partially
migrated database degrades to "one retry allowed", never to a crash.
"""

from __future__ import annotations

from typing import Any

from pymongo import ReturnDocument

from backend.v2.contexts.communications.domain.models import (
    MAX_DIGEST_SEND_ATTEMPTS,
    DigestSendStatus,
)


async def reclaim_failed_send(
    collection: Any,
    *,
    academy_id: str,
    recipient_field: str,
    recipient_id: str,
    digest_date: str,
) -> dict[str, Any] | None:
    """Re-queue a failed digest row for another attempt.

    Returns the updated document, or ``None`` when there is nothing retryable
    (the row is sent, still queued, skipped, or out of attempts).
    """
    doc: dict[str, Any] | None = await collection.find_one_and_update(
        {
            "academy_id": academy_id,
            recipient_field: recipient_id,
            "digest_date": digest_date,
            "status": str(DigestSendStatus.FAILED),
            "attempt_count": {"$lt": MAX_DIGEST_SEND_ATTEMPTS},
            # `$ne: False` and not `True`: rows predating the field are retryable.
            "retryable": {"$ne": False},
        },
        {
            "$set": {
                "status": str(DigestSendStatus.QUEUED),
                "failed_reason": None,
                "provider_message_id": None,
            },
            "$inc": {"attempt_count": 1},
        },
        return_document=ReturnDocument.AFTER,
    )
    return doc
