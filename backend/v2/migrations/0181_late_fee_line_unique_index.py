"""Partial unique index on policy-written late-fee lines (#552).

``ApplyLateFees`` decides "has this invoice already been charged a late fee?"
with a check-then-add: it reads the invoice's lines, sees no ``late_fee`` row
and appends one. Two scheduler ticks overlapping on the same academy (a slow
run and the next interval, or two app instances) can both pass the read before
either write lands, and the family is billed the fee twice. Same defect class
as 0173/0174: the invariant belongs in the store.

The partial filter is load-bearing. ``invoice_lines`` holds tuition, discount
and ad-hoc lines that legitimately repeat on one invoice, and operators have
been adding late fees BY HAND for years (that is the manual workaround this
issue replaces) — some invoices may already carry two. Pinning the filter to
``source_type == "late_fee_policy"``, a value only this automation writes,
constrains exactly the key space the policy owns and leaves every hand-entered
line, past or future, unconstrained.

Because no document can carry that source_type before this release, the index
build cannot meet a pre-existing duplicate. A ``DuplicateKeyError`` is still
caught rather than crashing boot, mirroring 0174.

Production does NOT run migrations on boot (``V2_RUN_MIGRATIONS_ON_BOOT`` is
false there, #629): apply with ``run_pending_migrations`` by hand.
"""

from __future__ import annotations

import logging

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ASCENDING
from pymongo.errors import DuplicateKeyError

log = logging.getLogger(__name__)

version = "0181_late_fee_line_unique_index"

COLLECTION = "invoice_lines"
INDEX_NAME = "late_fee_policy_line_unique"

#: Mirrors ``LATE_FEE_SOURCE_TYPE`` in
#: ``contexts/billing/application/use_cases/apply_late_fees.py``. Migrations
#: import no context code, so the value is repeated here.
LATE_FEE_SOURCE_TYPE = "late_fee_policy"


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    try:
        await db[COLLECTION].create_index(
            [("academy_id", ASCENDING), ("invoice_id", ASCENDING), ("source_type", ASCENDING)],
            unique=True,
            name=INDEX_NAME,
            partialFilterExpression={"source_type": LATE_FEE_SOURCE_TYPE},
            background=True,
        )
    except DuplicateKeyError:
        log.warning(
            "migration_index_skipped_duplicates_present",
            extra={
                "collection": COLLECTION,
                "index": INDEX_NAME,
                "remediation": (
                    "two automated late-fee lines exist on one invoice; credit the "
                    "surplus line, then re-run this migration"
                ),
            },
        )
