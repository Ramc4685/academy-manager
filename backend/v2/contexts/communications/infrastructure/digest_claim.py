"""Shared claim rule for the coach and parent digest repositories.

The two digest collections are deliberate near-duplicates (different recipient
field, different collection), but the rule that decides *whether a recipient
may be sent to at all today* and *when a failed send may be tried again* is a
correctness invariant, not per-collection detail — it is what keeps "retry a
failure" from becoming "send twice". It lives here once so neither repository
can drift from it (issue #435).

``claim_digest_send`` is the entry point. It looks the existing row up BEFORE
inserting, so the no-duplicate-email invariant does not depend on the unique
``(academy_id, recipient, digest_date)`` index existing. Until 2026-09-02 the
claim was insert-first and relied on ``DuplicateKeyError`` alone; production
had never built the indexes from migrations 0125/0148, so every hourly tick
after the digest hour (``>=`` since PR #558) inserted a fresh QUEUED row and
every coach and parent was e-mailed once an hour for the rest of the day.

The lookup alone is not a claim under concurrency: two callers that interleave
between the lookup and the insert both miss and both insert. With the unique
index present the second insert raises ``DuplicateKeyError`` and loses. Without
it, ``claim_digest_send`` verifies AFTER inserting that its row is the only one
for the key, and withdraws its own row when it is not. A caller therefore holds
the claim only if it observed itself alone after its own insert, and two callers
can never both observe that — so at most one sends. The cost when both observe
the collision is that both withdraw and nobody sends on that tick; the next
hourly tick finds no row and claims normally. In practice the scheduler's
``job_lease`` (``main.py``) already keeps two digest runs from overlapping; the
verify step is what makes the claim itself safe for any caller, index or not.

The re-claim is a single conditional ``find_one_and_update``:

* it matches ``status == "failed"``, or ``status == "queued"`` on a row whose
  claim is older than ``STALE_QUEUED_AFTER``. A ``sent`` or ``skipped`` row can
  never be re-claimed (no duplicate email) — that is the invariant this module
  exists to hold.

  The stale-``queued`` arm closes the second half of the original finding
  (#542). ``try_claim`` inserts the QUEUED row *before* sending, so a crash,
  OOM-kill or deploy between the insert and ``mark_sent``/``mark_failed``
  leaves a row that is neither retryable (it is not ``failed``) nor releasable
  — it holds the unique ``(academy_id, recipient, digest_date)`` claim for that
  date forever, and that recipient silently gets nothing.

  Staleness, not mere ``queued``-ness, is the test: a freshly queued row may be
  an in-flight send in the current run, and stealing it would double-send. The
  cutoff is deliberately longer than the digest jobs' 10-minute ``job_lease``
  (``send_coach_daily_digests`` / ``send_parent_daily_digests`` in ``main.py``),
  so a run still holding its lease can never have its own claim taken. A row
  that keeps crashing mid-send is re-claimed on later ticks but still bounded
  by ``MAX_DIGEST_SEND_ATTEMPTS``;
* it skips rows marked ``retryable: false`` — a recipient with no e-mail
  address cannot be helped by trying again, and retrying would cost three plan
  generations a day forever;
* it matches only rows with attempts remaining, so a permanently broken
  recipient stops after ``MAX_DIGEST_SEND_ATTEMPTS`` instead of burning an
  attempt every hour for the rest of the day;
* being one atomic update, two concurrent scheduler ticks cannot both win it.

Rows written before migration 0154 carry no ``attempt_count``; the migration
backfills them, and ``_from_doc`` defaults a missing value to 1 so a partially
migrated database degrades to "one retry allowed", never to a crash.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from backend.v2.contexts.communications.domain.models import (
    MAX_DIGEST_SEND_ATTEMPTS,
    DigestSendStatus,
)

#: How long a ``queued`` row must sit untouched before a later tick may treat
#: it as abandoned rather than in flight. Must stay comfortably above the
#: digest jobs' 10-minute ``job_lease`` so a run holding its lease can never
#: have its own claim stolen out from under it.
STALE_QUEUED_AFTER = timedelta(minutes=15)


async def reclaim_retryable_send(
    collection: Any,
    *,
    academy_id: str,
    recipient_field: str,
    recipient_id: str,
    digest_date: str,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Re-queue a retryable digest row for another attempt.

    Retryable means ``failed``, or ``queued`` and abandoned (older than
    ``STALE_QUEUED_AFTER``). Returns the updated document, or ``None`` when
    there is nothing to retry — the row is sent, skipped, freshly queued (an
    in-flight send), marked non-retryable, or out of attempts.
    """
    moment = now or datetime.now(UTC)
    doc: dict[str, Any] | None = await collection.find_one_and_update(
        {
            "academy_id": academy_id,
            recipient_field: recipient_id,
            "digest_date": digest_date,
            "attempt_count": {"$lt": MAX_DIGEST_SEND_ATTEMPTS},
            # `$ne: False` and not `True`: rows predating the field are retryable.
            "retryable": {"$ne": False},
            # Never `sent`, never `skipped` — the no-duplicate-email invariant.
            "$or": [
                {"status": str(DigestSendStatus.FAILED)},
                {
                    "status": str(DigestSendStatus.QUEUED),
                    "created_at": {"$lt": moment - STALE_QUEUED_AFTER},
                },
            ],
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


async def claim_digest_send(
    collection: Any,
    *,
    doc: dict[str, Any],
    academy_id: str,
    recipient_field: str,
    recipient_id: str,
    digest_date: str,
) -> dict[str, Any] | None:
    """Claim today's send for one recipient; return the row that holds the claim.

    ``doc`` is the fully built QUEUED row to insert if no row exists yet. The
    lookup is an exact match on ``digest_date``: admin test sends are stored
    under a synthetic ``"<date>#test:<ulid>"`` and must not block (or be
    mistaken for) the day's real claim.

    Returns the inserted row, the re-queued row from
    :func:`reclaim_retryable_send`, or ``None`` when the recipient is already
    sent, skipped, in flight, non-retryable or out of attempts — or when this
    caller lost a concurrent claim for the same key.

    Safe without the unique index: after a successful insert the caller checks
    that its row is the only one for ``key`` and withdraws it otherwise (see the
    module docstring for why that is sufficient). With the index present the
    losing insert raises ``DuplicateKeyError`` instead and the check is a
    one-row indexed count.
    """
    key = {
        "academy_id": academy_id,
        recipient_field: recipient_id,
        "digest_date": digest_date,
    }
    existing = await collection.find_one(key, projection={"_id": 1})
    if existing is None:
        try:
            inserted = await collection.insert_one(doc)
        except DuplicateKeyError:
            # Lost the race to a concurrent claim (unique index present); fall
            # through and let the conditional re-claim decide, exactly as if
            # the lookup had found the row.
            pass
        else:
            if await collection.count_documents(key) == 1:
                return doc
            # A concurrent claim also missed on the lookup and inserted (no
            # unique index to stop it). Only a caller that saw itself alone
            # may send; this one did not, so it withdraws its own row — never
            # the other's — and falls through to the re-claim, which will
            # refuse the survivor's fresh QUEUED row.
            await collection.delete_one({"_id": inserted.inserted_id})
    return await reclaim_retryable_send(
        collection,
        academy_id=academy_id,
        recipient_field=recipient_field,
        recipient_id=recipient_id,
        digest_date=digest_date,
    )
