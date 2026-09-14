"""Admin ``admin_drop_at_period_end`` scheduled actions (issue #820).

An admin "drop at end of period" now stamps ``enrollments
.pending_cancellation_at`` and enqueues a ``scheduled_enrollment_actions`` row
of the new type ``admin_drop_at_period_end``, which the hourly
``process_scheduled_cancellation_actions`` job replays through
``WithdrawEnrollment`` once the academy-local month has ended.

Two things in the existing schema would reject that write:

1. Migration 0133's ``scheduled_enrollment_actions`` validator pins
   ``action_type`` to an enum of the two pre-#820 types. 0133's definition is
   corrected in place (single source of truth, same as 0165/0169) and
   re-applied here, along with the four admin-decision fields the row carries
   (``outcome``, ``actor_id``, ``reason``, ``reason_code``) so they are typed
   rather than merely tolerated.
2. Migration 0169's ``unique_pending_cancel_at_period_end`` partial index only
   covers ``action_type: "cancel_at_period_end"``, so "one PENDING action per
   enrollment" would not be enforced for the new type. A sibling partial
   unique index is added for it — the key
   ``MongoScheduledEnrollmentActionRepository.add`` upserts on.

``enrollments`` needs no change: the admin path reuses 0169's
``pending_cancellation_at`` / ``pending_cancellation_requested_at`` fields.

Does NOT run on boot in production (``V2_RUN_MIGRATIONS_ON_BOOT`` is false,
#629); apply it by hand right after the deploy via ``fly ssh console -a
courtmastr-academy-api`` and ``backend.v2.migrations.run_pending_migrations``.
Until it is applied, scheduling an admin drop at period end fails with
"Document failed validation" and the admin sees an error — nothing is
half-written, because the enrollment marker and the action are written in that
order and the action is what the validator rejects. (Re-run the path after
applying: a marker with no action behind it is cleared by the admin's "Cancel
scheduled drop".)
"""

from __future__ import annotations

import importlib
import logging
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

log = logging.getLogger(__name__)

version = "0182_admin_drop_at_period_end"

COLLECTION = "scheduled_enrollment_actions"
ADMIN_DROP_INDEX = "unique_pending_admin_drop_at_period_end"


async def up(db: AsyncIOMotorDatabase[Any]) -> None:
    base = importlib.import_module(
        "backend.v2.migrations.0133_broader_validators_and_outbox_retry_lock"
    )
    validator = base.VALIDATORS[COLLECTION]
    schema = validator["$jsonSchema"]
    assert "admin_drop_at_period_end" in schema["properties"]["action_type"]["enum"], (
        "0133 must list the #820 action type"
    )
    assert "outcome" in schema["properties"], "0133 must type the #820 decision fields"
    await base._apply_validator(db, COLLECTION, validator)

    await db[COLLECTION].create_index(
        [("academy_id", 1), ("enrollment_id", 1), ("action_type", 1)],
        unique=True,
        name=ADMIN_DROP_INDEX,
        partialFilterExpression={"status": "pending", "action_type": "admin_drop_at_period_end"},
    )
    log.info("0182: %s validator re-applied and %s created", COLLECTION, ADMIN_DROP_INDEX)
