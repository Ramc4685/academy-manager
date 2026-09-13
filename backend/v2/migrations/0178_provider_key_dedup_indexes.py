"""Index the provider-key fields the revenue dedup looks payments up by (#526).

Both money reports de-duplicate legacy ``payments`` against ``ledger_payments``
by six interchangeable provider keys. The reports dashboard now looks that
collision up by key instead of streaming the whole payment history, and the
revenue-by-month CSV export runs batched ``$or`` queries over the same six
fields — neither is bounded unless every branch of the ``$or`` is indexed,
because Mongo falls back to a collection scan for an ``$or`` whose branches
are not all index-backed.

Four of the six are already covered on each collection (0030/0091/0126 on
``payments``, 0128/0130/0173 on ``ledger_payments``). This adds the stragglers:
``invoice_id`` and ``invoice_number`` on both, plus
``stripe_checkout_session_id`` on ``ledger_payments``.

None of these are unique — an invoice is settled by many payments, and the
ledger deliberately allows several rows against one invoice. The partial
filter keeps the index off the (many) rows that carry no such key, exactly as
the neighbouring indexes do.

Production does NOT run migrations on boot (``V2_RUN_MIGRATIONS_ON_BOOT`` is
false there, #629): apply with ``run_pending_migrations`` by hand. The builds
are ``background=True`` because ``payments`` is large and old.
"""

from __future__ import annotations

import logging

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import OperationFailure

log = logging.getLogger(__name__)

version = "0178_provider_key_dedup_indexes"

#: ``(collection, field, index name)`` — the provider-key lookups that had no
#: supporting index before this migration.
INDEXES: tuple[tuple[str, str, str], ...] = (
    ("ledger_payments", "invoice_id", "academy_ledger_payment_invoice"),
    ("ledger_payments", "invoice_number", "academy_ledger_payment_invoice_number"),
    (
        "ledger_payments",
        "stripe_checkout_session_id",
        "academy_ledger_payment_checkout_session",
    ),
    ("payments", "invoice_id", "academy_payment_invoice"),
    ("payments", "invoice_number", "academy_payment_invoice_number"),
)


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    for collection, field, name in INDEXES:
        try:
            await db[collection].create_index(
                [("academy_id", 1), (field, 1)],
                name=name,
                partialFilterExpression={field: {"$type": "string"}},
                background=True,
            )
        except OperationFailure:
            # An equivalent index already exists under another name. The
            # lookup is served either way, so this is not worth failing boot.
            log.warning(
                "migration_index_skipped_conflict",
                extra={"collection": collection, "index": name, "field": field},
            )
