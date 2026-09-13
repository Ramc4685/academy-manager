"""Admit the level-up review claim statuses at rest (#548).

Issue #548: approve ran the certificate, the level advance and the skill
seeding BEFORE any write guarded the recommendation row, so a reject that
committed a millisecond later left the recommendation REJECTED while the
student held a certificate for a level they had just been refused. The fix is
a claim: the reviewer compare-and-sets ``RECOMMENDED -> APPROVING`` (or
``REJECTING``) and stamps ``claimed_at`` before touching anything, so the
second reviewer loses the claim instead of racing past a half-applied
approval.

Two things therefore have to be true of the collection itself:

* ``level_up_recommendations.status`` carries a ``$jsonSchema`` enum
  (migration 0133) that lists only the six settled statuses. Writing
  ``APPROVING`` against it is a write error — the dormant-validator failure
  mode of #657, where the application grew a value the collection had never
  been told about. This migration adds the two claim statuses, and
  ``claimed_at`` alongside them.
* ``recs_active_unique`` (migration 0122) is the partial unique index that
  stops two live recommendations for the same student and level. Its filter
  lists ``RECOMMENDED``/``APPROVED``, so a claimed row would silently drop
  OUT of the index for as long as the claim is held — exactly the window in
  which a duplicate must not be created. The filter is widened to the same
  vocabulary the repository's readers use.

Partial-index filters cannot be edited in place, so the index is dropped and
rebuilt. That is safe here: the widened filter only ever covers MORE
documents, and no production row can carry a claim status yet (this migration
is what first makes them writable), so the rebuild cannot collide.

TOLERATING WHAT IS ALREADY THERE, the reason this is safe against production:

* ``validationLevel: "moderate"`` — the level 0133 already uses — validates
  inserts and updates to documents that ALREADY satisfy the validator and
  leaves existing non-conforming documents alone.
* This is a ``collMod``, which REPLACES the validator rather than merging
  into it, so 0133's ``required`` list and every other
  ``level_up_recommendations`` property is restated below verbatim. Dropping
  them would silently retire the guard that every row carries an
  ``academy_id``.
* Purely additive: two new enum values and one new optional field. Every
  existing row and every older reader is unaffected.

Production does NOT run migrations on boot (``V2_RUN_MIGRATIONS_ON_BOOT`` is
false there, #629): apply with ``run_pending_migrations`` by hand. There is no
data rewrite; the index rebuild is over a small collection.

No ``down()``: ``runner.py`` has no rollback concept and none of the migrations
here define one.
"""

from __future__ import annotations

import logging
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import CollectionInvalid, OperationFailure

log = logging.getLogger(__name__)

version = "0176_level_up_claim_statuses"

COLLECTION = "level_up_recommendations"
ACTIVE_INDEX = "recs_active_unique"

#: Mirrors ``student_progress/domain/models.py``'s ``LevelUpStatus``. Spelled
#: out rather than imported, deliberately: a migration is an append-only
#: record of what was applied, and importing live domain code would let a
#: future vocabulary change retroactively alter what this already-applied
#: migration means. No other migration in this package imports context code
#: either. ``test_0176_level_up_claim_statuses.py`` fails the build if the two
#: drift — the drift detection without the time travel.
STATUS_ENUM = [
    "APPROVED",
    "APPROVING",
    "COMPLETED",
    "NOT_READY",
    "READY",
    "RECOMMENDED",
    "REJECTED",
    "REJECTING",
]

#: Mirrors ``ACTIVE_LEVEL_UP_STATUSES``: a recommendation awaiting a decision,
#: one whose review is in flight, or one already approved, each holds the
#: student's slot for that level.
ACTIVE_STATUSES = ["APPROVED", "APPROVING", "RECOMMENDED", "REJECTING"]

#: MongoDB's "collection does not exist" error code. A fresh database has no
#: ``level_up_recommendations`` collection until the first write, and
#: migrations run at boot in the other environments, so this has to be
#: survivable rather than fatal.
_NAMESPACE_NOT_FOUND = 26

#: MongoDB's "index not found" error code, for the drop half of the rebuild.
_INDEX_NOT_FOUND = 27

#: Restated from migration 0133 — collMod replaces the validator, it does not
#: merge. Only ``status`` and the new ``claimed_at`` differ from 0133's
#: version of this schema.
VALIDATOR: dict[str, Any] = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": [
            "rec_id",
            "academy_id",
            "student_id",
            "from_level_id",
            "to_level_id",
            "program_id",
            "status",
            "recommended_by",
            "recommended_at",
        ],
        "properties": {
            "rec_id": {"bsonType": "string"},
            "academy_id": {"bsonType": "string"},
            "student_id": {"bsonType": "string"},
            "from_level_id": {"bsonType": "string"},
            "to_level_id": {"bsonType": "string"},
            "program_id": {"bsonType": "string"},
            "status": {"enum": STATUS_ENUM},
            "recommended_by": {"bsonType": "string"},
            "recommended_at": {"bsonType": "date"},
            "reviewed_by": {"bsonType": ["string", "null"]},
            "reviewed_at": {"bsonType": ["date", "null"]},
            "rejection_reason": {"bsonType": ["string", "null"]},
            # The claim lease clock (#548): set with APPROVING/REJECTING,
            # cleared when the claim is released.
            "claimed_at": {"bsonType": ["date", "null"]},
        },
    }
}


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    await _apply_validator(db)
    await _rebuild_active_unique_index(db)


async def _apply_validator(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
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
            log.info("level_up_collection_already_created", extra={"migration": version})


async def _rebuild_active_unique_index(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    """Widen ``recs_active_unique``'s partial filter to cover claimed rows.

    A partial filter cannot be edited in place, and re-creating an index under
    an existing name with different options is an error, so the old index is
    dropped first. Missing either way is fine: a fresh database has neither
    the collection nor the index, and a re-run finds the widened one already
    in place.
    """
    recs = db[COLLECTION]
    try:
        await recs.drop_index(ACTIVE_INDEX)
    except NotImplementedError:
        # mongomock-motor in tests: no partial index enforcement to restore.
        return
    except OperationFailure as exc:
        if exc.code not in (_INDEX_NOT_FOUND, _NAMESPACE_NOT_FOUND):
            raise
    await recs.create_index(
        [("academy_id", 1), ("student_id", 1), ("from_level_id", 1)],
        unique=True,
        name=ACTIVE_INDEX,
        partialFilterExpression={"status": {"$in": ACTIVE_STATUSES}},
    )
