"""Constrain ``enrollments.status`` to the enrollment status enum (#642).

``EnrollmentWriter.update_status(enrollment_id, status: str)`` takes a bare
``str`` and writes it. ``enrollments.status`` has never been enum-constrained:
migration 0132 declares it an unconstrained ``{"bsonType": "string"}``, and
0171 went out of its way to record that neither it nor
``enrollment_events.event_type`` is enum-guarded. So a misspelled or invented
status lands in the collection and is then missing from every reader at once —
each one filters on ``$in`` over the statuses it knows, and a value none of
them list simply never matches. That is invisible: the student does not error,
they disappear.

This migration makes the vocabulary a rule at rest, sourced from the SAME
frozenset the application reads (``domain/models.py``'s
``STORED_ENROLLMENT_STATUSES``) rather than a second hand-typed list, so the
two cannot drift the way #657's dormant validator drifted from its writers.

``__deleting__`` is in the enum on purpose. ``delete_if_status`` CAS-stamps it
on the row in the instant before the hard delete, so it is a value that really
reaches the collection; omitting it would turn every hard delete into a
validator write error — precisely the #657 failure mode, reproduced by a
migration meant to prevent it.

TOLERATING WHAT IS ALREADY THERE, which is the whole reason this is safe to
run against production:

* ``validationLevel: "moderate"`` (the level 0132 already uses for every
  collection it guards) validates inserts and updates to documents that
  ALREADY satisfy the validator, and leaves existing non-conforming documents
  alone. Rows carrying a status this enum does not list — and rows with no
  ``status`` field at all, which every reader treats as ``active`` — keep
  being updatable. A ``strict`` level here would brick writes to exactly the
  legacy rows #642 is about.
* The enum carries BOTH spellings of each renamed terminal status
  ("withdrawn"/"dropped", "cancelled"/"deleted"). 0171's data rewrite has not
  necessarily been applied in production — it is a hand-applied,
  apply-after-soak migration — so legacy spellings must stay valid.
* "paused" stays valid. It is not renamed to "held" (see
  ``domain/models.py``); legacy paused rows are retired by attrition.

This is a ``collMod``, which REPLACES the validator wholesale rather than
merging into it, so 0132's ``required`` list and the other ``enrollments``
properties are restated below verbatim. Dropping them would silently retire
the guard that every row carries an ``academy_id``. A contract test pins both
halves (``v2/tests/contract/test_enrollment_status_validator_migration.py``).

Production does NOT run migrations on boot (``V2_RUN_MIGRATIONS_ON_BOOT`` is
false there, #629): apply with ``run_pending_migrations`` by hand. There is no
data rewrite and no index build, so it is fast and idempotent — the enum is
sorted, so a re-run submits a byte-identical validator.

No ``down()``: ``runner.py`` has no rollback concept and none of the 80-odd
migrations here define one. Reverting means a follow-up migration that
restates 0132's unconstrained ``{"bsonType": "string"}``.
"""

from __future__ import annotations

import logging
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import CollectionInvalid, OperationFailure

log = logging.getLogger(__name__)

version = "0175_enrollment_status_enum_validator"

COLLECTION = "enrollments"

#: Mirrors ``domain/models.py``'s ``STORED_ENROLLMENT_STATUSES`` — the
#: vocabulary plus ``__deleting__``. Spelled out rather than imported,
#: deliberately: a migration is an append-only record of what was applied,
#: and importing live domain code would let a future vocabulary change
#: retroactively alter what this already-applied migration means. No other
#: migration in this package imports context code either. The two are pinned
#: together by ``test_enrollment_status_validator_migration.py``, which fails
#: the build if the domain gains a status this enum does not list — the
#: drift-detection half of the bargain, without the time-travel.
STATUS_ENUM = [
    "__deleting__",
    "active",
    "cancelled",
    "deleted",
    "dropped",
    "held",
    "paused",
    "reclaim_pending",
    "withdrawn",
]

#: MongoDB's "collection does not exist" error code. A fresh database has no
#: ``enrollments`` collection until the first write, and migrations run at
#: boot, so this has to be survivable rather than fatal.
_NAMESPACE_NOT_FOUND = 26

#: Restated from migration 0132 — collMod replaces the validator, it does not
#: merge. Only ``status`` differs from 0132's version of this schema.
VALIDATOR: dict[str, Any] = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["academy_id", "enrollment_id", "student_id", "session_id", "status"],
        "properties": {
            "academy_id": {"bsonType": "string"},
            "enrollment_id": {"bsonType": "string"},
            "student_id": {"bsonType": "string"},
            "session_id": {"bsonType": "string"},
            "parent_id": {"bsonType": ["string", "null"]},
            "status": {
                "bsonType": "string",
                "enum": STATUS_ENUM,
            },
        },
    }
}


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    try:
        await db.command(
            {
                "collMod": COLLECTION,
                "validator": VALIDATOR,
                "validationLevel": "moderate",
                "validationAction": "error",
            }
        )
    except NotImplementedError:
        # mongomock-motor in tests: no collMod support, nothing to guard.
        return
    except OperationFailure as exc:
        if exc.code != _NAMESPACE_NOT_FOUND:
            raise
        try:
            await db.create_collection(
                COLLECTION,
                validator=VALIDATOR,
                validationLevel="moderate",
                validationAction="error",
            )
        except CollectionInvalid:
            # Raced with another booting instance that created it first.
            log.info("enrollments_collection_already_created", extra={"migration": version})
