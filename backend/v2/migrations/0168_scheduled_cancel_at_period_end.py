"""Scheduled ``cancel_at_period_end`` actions (issue #675).

A parent's ``end_of_period`` self-cancel no longer flips the enrollment to
``cancelled`` on the spot. It stamps ``enrollments.pending_cancellation_at``
and enqueues a ``scheduled_enrollment_actions`` row of the new type
``cancel_at_period_end`` that the hourly
``process_scheduled_cancellation_actions`` job runs at month end.

Two things in the existing schema would 500 that write:

1. Migration 0133's ``scheduled_enrollment_actions`` validator REQUIRES
   ``pause_request_id`` as a string. A cancellation has no pause request, so
   the field becomes optional / nullable and ``action_type`` becomes an
   explicit enum of the two known types. 0133's definition is corrected in
   place (single source of truth, same as 0165) and re-applied here.
2. Migration 0113's ``unique_pause_action`` index is unique on
   ``(academy_id, pause_request_id, action_type)``. Mongo indexes ``null`` as
   a value, so the SECOND enrollment in an academy to schedule a cancel would
   collide on ``(acad, null, "cancel_at_period_end")``. The index is rebuilt
   as a partial index over rows that actually carry a ``pause_request_id``,
   and a second partial unique index enforces "one PENDING cancellation per
   enrollment" — the key ``MongoScheduledEnrollmentActionRepository.add``
   upserts on for the new type.

``enrollments`` gains ``pending_cancellation_at`` /
``pending_cancellation_requested_at``; 0132's ``enrollments`` validator lists
properties without ``additionalProperties: false``, so no change is needed
there.

Does NOT run on boot in production (``V2_RUN_MIGRATIONS_ON_BOOT`` is false,
#629); apply it by hand right after the deploy, via
``fly ssh console -a courtmastr-academy-api`` and
``backend.v2.migrations.run_pending_migrations`` (same as 0165-0167). Until
it is applied, an end-of-period self-cancel fails with "Document failed
validation" and the parent sees an error — nothing is half-written, because
the scheduled action is the first write of the new flow.
"""

from __future__ import annotations

import importlib
import logging
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import OperationFailure

log = logging.getLogger(__name__)

version = "0168_scheduled_cancel_at_period_end"

COLLECTION = "scheduled_enrollment_actions"
PAUSE_INDEX = "unique_pause_action"
CANCEL_INDEX = "unique_pending_cancel_at_period_end"


async def _drop_index_if_present(collection: Any, name: str) -> None:
    try:
        await collection.drop_index(name)
    except OperationFailure as exc:
        # 27 = IndexNotFound: a fresh database never had the 0113 index.
        if exc.code != 27:
            raise
    except NotImplementedError:
        return


async def up(db: AsyncIOMotorDatabase[Any]) -> None:
    base = importlib.import_module(
        "backend.v2.migrations.0133_broader_validators_and_outbox_retry_lock"
    )
    validator = base.VALIDATORS[COLLECTION]
    schema = validator["$jsonSchema"]
    assert "pause_request_id" not in schema["required"], "0133 must not require pause_request_id"
    assert "null" in schema["properties"]["pause_request_id"]["bsonType"]
    assert "cancel_at_period_end" in schema["properties"]["action_type"]["enum"]
    await base._apply_validator(db, COLLECTION, validator)

    collection = db[COLLECTION]
    await _drop_index_if_present(collection, PAUSE_INDEX)
    await collection.create_index(
        [("academy_id", 1), ("pause_request_id", 1), ("action_type", 1)],
        unique=True,
        name=PAUSE_INDEX,
        partialFilterExpression={"pause_request_id": {"$type": "string"}},
    )
    await collection.create_index(
        [("academy_id", 1), ("enrollment_id", 1), ("action_type", 1)],
        unique=True,
        name=CANCEL_INDEX,
        partialFilterExpression={"status": "pending", "action_type": "cancel_at_period_end"},
    )
    log.info("0168: %s validator re-applied and partial unique indexes rebuilt", COLLECTION)
