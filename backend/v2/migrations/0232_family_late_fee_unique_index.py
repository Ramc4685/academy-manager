"""One automated late fee per family per billing month (L8).

``ApplyLateFees`` charges a family once per billing month: a late fee on any
sibling's invoice for that period suppresses the rest. The check is a read of
the family's lines followed by a write, so two overlapping passes could each
charge a different sibling. The policy line's ``source_id`` is
``"{parent_id}:{period}"``; this index makes it unique per academy, so the
second write is refused and the pass repairs that invoice's totals.

Lines the policy wrote before this release carry ``source_id == invoice_id``,
which is already unique per invoice (0181), so the build cannot meet a
duplicate. The partial filter uses ``$gt: ""``, never ``$type``: the planner
ignores ``$type`` partial indexes for equality lookups. A ``DuplicateKeyError``
is logged with its remediation and re-raised, so the migration fails loudly
instead of shipping code that relies on an index that is not there.

Production applies this through the deploy pipeline's Migrate Production step,
before the code that writes the new source_id serves traffic.
"""

from __future__ import annotations

import logging

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ASCENDING
from pymongo.errors import DuplicateKeyError

log = logging.getLogger(__name__)

version = "0232_family_late_fee_unique_index"

COLLECTION = "invoice_lines"
INDEX_NAME = "late_fee_policy_family_period_unique"

#: Mirrors ``LATE_FEE_SOURCE_TYPE`` in
#: ``contexts/billing/application/use_cases/apply_late_fees.py``.
LATE_FEE_SOURCE_TYPE = "late_fee_policy"


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    try:
        await db[COLLECTION].create_index(
            [("academy_id", ASCENDING), ("source_type", ASCENDING), ("source_id", ASCENDING)],
            unique=True,
            name=INDEX_NAME,
            partialFilterExpression={
                "source_type": LATE_FEE_SOURCE_TYPE,
                "source_id": {"$gt": ""},
            },
            background=True,
        )
    except DuplicateKeyError:
        log.warning(
            "migration_index_skipped_duplicates_present",
            extra={
                "collection": COLLECTION,
                "index": INDEX_NAME,
                "remediation": (
                    "two automated late-fee lines share one source_id; delete the "
                    "surplus line or re-key its source_id (a credit leaves the "
                    "duplicate in place), then re-run this migration"
                ),
            },
        )
        raise
