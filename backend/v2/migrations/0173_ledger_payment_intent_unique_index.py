"""Partial unique index on ``ledger_payments.stripe_payment_intent_id`` (#679).

Every settlement path — ``handle_webhook_event``, the reconciler, the
legacy-charge link — decides "have we already recorded this money?" by
looking the payment intent up in ``ledger_payments``, yet only application
code stood behind that check. A replayed webhook for the same intent could
record a second ledger payment and, on an already-settled invoice, land it
as spendable parent credit. Every neighbouring idempotency key already has
a partial unique index (0128 for ``ledger_idempotency_key`` and
``payment_id``, 0130 for the allocation and attempt keys); this closes the
one gap.

The partial filter is load-bearing, not cosmetic: manual payments (cash,
cheque, Zelle) carry no payment intent, and a plain unique index would
allow only one of them per academy. Same shape 0128 already uses.

Duplicates may already exist in production — they are exactly what the bug
produced. Creating a unique index over them fails, so a ``DuplicateKeyError``
is logged and the index is skipped rather than crashing boot. Run
``backend/scripts/ledger_payment_intent_duplicate_audit.py`` first: it lists
the offending groups with their allocations and credits so they can be
reconciled by hand, after which this migration is re-run (delete its row
from ``v2_migrations``) to build the index.

Production does NOT run migrations on boot (``V2_RUN_MIGRATIONS_ON_BOOT``
is false there, #629): apply with ``run_pending_migrations`` by hand.
"""

from __future__ import annotations

import logging

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import DuplicateKeyError

log = logging.getLogger(__name__)

version = "0173_ledger_payment_intent_unique_index"

COLLECTION = "ledger_payments"
INDEX_NAME = "academy_ledger_payment_intent_unique"


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    try:
        await db[COLLECTION].create_index(
            [("academy_id", 1), ("stripe_payment_intent_id", 1)],
            unique=True,
            name=INDEX_NAME,
            partialFilterExpression={"stripe_payment_intent_id": {"$type": "string"}},
            background=True,
        )
    except DuplicateKeyError:
        log.warning(
            "migration_index_skipped_duplicates_present",
            extra={
                "collection": COLLECTION,
                "index": INDEX_NAME,
                "remediation": (
                    "run backend/scripts/ledger_payment_intent_duplicate_audit.py, "
                    "reconcile the duplicate payments, then re-run this migration"
                ),
            },
        )
