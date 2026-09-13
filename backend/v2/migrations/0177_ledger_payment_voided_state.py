"""Allow ``voided`` on ``ledger_payments.status`` and index it (#619).

Admins can now void a test/erroneous payment instead of leaving it on the
books forever. The status is a NEW value, and 0132 pinned this collection's
status to a five-value enum — a dormant validator exactly like #657's, which
would reject every void write with ``schemaRulesNotSatisfied`` long after the
code that needs it shipped. So the vocabulary has to be widened at rest before
the feature can work in production.

``collMod`` REPLACES a validator rather than merging into it, so 0132's
``required`` list and every other ``ledger_payments`` property is restated
below verbatim. Only ``status`` differs. The new void columns
(``void_reason``/``voided_at``/``voided_by``) are deliberately NOT added to the
schema: 0132 does not enumerate every optional field either, and an
unlisted property is unconstrained rather than forbidden (there is no
``additionalProperties: false``), so no backfill is needed — absent means
"never voided", which is what every reader already assumes.

``validationLevel: "moderate"`` (0132's level) keeps existing non-conforming
rows updatable, so this is safe to apply to production as it stands.

The index is the read side: the payments list and every report now filter
``status`` on ``ledger_payments``, and the "show voided" view selects on it
directly. ``(academy_id, status, created_at)`` serves both the tenant scope and
the newest-first sort the admin list uses.

Production does NOT run migrations on boot (``V2_RUN_MIGRATIONS_ON_BOOT`` is
false there, #629): apply with ``run_pending_migrations`` by hand. There is no
data rewrite, and the index build is background, so it is fast and idempotent.
"""

from __future__ import annotations

import logging
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import CollectionInvalid, OperationFailure

log = logging.getLogger(__name__)

version = "0177_ledger_payment_voided_state"

COLLECTION = "ledger_payments"
INDEX_NAME = "academy_ledger_payment_status_created"

MONEY = ["int", "long", "double", "decimal"]
OPT_DATE = ["date", "null"]
OPT_STRING = ["string", "null"]

#: Mirrors ``domain/ledger.py``'s ``LedgerPaymentStatus``. Spelled out rather
#: than imported for the reason 0175 gives: a migration is an append-only
#: record of what was applied, and no migration in this package imports
#: context code.
STATUS_ENUM = [
    "failed",
    "partially_refunded",
    "pending",
    "refunded",
    "succeeded",
    "voided",
]

#: MongoDB's "collection does not exist" error code — a fresh database has no
#: ``ledger_payments`` until the first write.
_NAMESPACE_NOT_FOUND = 26

#: Restated from migration 0132; only ``status`` differs.
VALIDATOR: dict[str, Any] = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": [
            "payment_id",
            "academy_id",
            "parent_id",
            "amount_cents",
            "unapplied_amount_cents",
            "currency",
            "status",
            "created_at",
            "updated_at",
        ],
        "properties": {
            "payment_id": {"bsonType": "string"},
            "academy_id": {"bsonType": "string"},
            "parent_id": {"bsonType": "string"},
            "amount_cents": {"bsonType": MONEY},
            "unapplied_amount_cents": {"bsonType": MONEY},
            "currency": {"bsonType": "string"},
            "status": {"enum": STATUS_ENUM},
            "payment_method": {"bsonType": OPT_STRING},
            "stripe_payment_intent_id": {"bsonType": OPT_STRING},
            "stripe_invoice_id": {"bsonType": OPT_STRING},
            "paid_at": {"bsonType": OPT_DATE},
            "created_at": {"bsonType": "date"},
            "updated_at": {"bsonType": "date"},
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
        pass
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
            log.info("ledger_payments_collection_already_created", extra={"migration": version})

    await db[COLLECTION].create_index(
        [("academy_id", 1), ("status", 1), ("created_at", -1)],
        name=INDEX_NAME,
        background=True,
    )
