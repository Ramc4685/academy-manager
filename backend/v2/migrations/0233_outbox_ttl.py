"""Expire finished outbox rows (G:jobs_data_infra:8).

``outbox_events`` and ``event_handler_runs`` only grew: every processed event
and every succeeded handler run stayed forever under the dispatcher's
once-a-second poll. TTL indexes now remove processed outbox rows 400 days after
they finished and succeeded handler runs after 90 days.

A processed outbox row is also a producer-side exactly-once guard: webhook
handling (``_append_outbox_once``) and ``record_payment_dispute`` insert events
under deterministic ids, so a replayed webhook or a ``charge.dispute.updated``
for a dispute that is still open months later dedupes against the old row
instead of emailing the family twice. 400 days matches ``event_audit`` (0166)
and outlives any dispute or admin replay window.

Both indexes are partial, so only finished rows can expire: an outbox row is
eligible only once ``status == "processed"`` (pending, retry, processing and
dead-lettered rows are kept), and a handler run only once
``status == "succeeded"`` (retrying and failed runs are kept). A succeeded run
is the dispatcher's idempotency record for its event; it is only consulted
while that event is still being dispatched, which ends long before 90 days.

The partial filters have no predicate the claim query can satisfy, so the
planner never picks them for ``_claim_next_event`` (checked with explain in
tests/contract/test_outbox_ttl_real_mongo.py). Idempotent.
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0233_outbox_ttl"

OUTBOX_TTL_SECONDS = 400 * 24 * 60 * 60
HANDLER_RUNS_TTL_SECONDS = 90 * 24 * 60 * 60


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    await db["outbox_events"].create_index(
        "processed_at",
        expireAfterSeconds=OUTBOX_TTL_SECONDS,
        partialFilterExpression={"status": "processed"},
        name="outbox_processed_ttl",
    )
    await db["event_handler_runs"].create_index(
        "completed_at",
        expireAfterSeconds=HANDLER_RUNS_TTL_SECONDS,
        partialFilterExpression={"status": "succeeded"},
        name="event_handler_runs_succeeded_ttl",
    )
