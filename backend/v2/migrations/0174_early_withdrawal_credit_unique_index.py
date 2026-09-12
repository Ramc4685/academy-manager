"""Partial unique index on approved early-withdrawal credits (#690).

``RecordWithdrawalDecision`` decides "has this enrollment already been
credited?" with a check-then-create: it reads
``find_active_for_enrollment(enrollment_id, type="EARLY_WITHDRAWAL_CREDIT")``
and, seeing nothing, inserts an APPROVED credit. PR #684 made the withdraw
path the single writer, but single-writer is not the same as atomic — two
requests for the same enrollment (a double-click, a retry after a timeout,
two admins) can both pass the read before either insert lands, and the
family ends up with two spendable credits. That is real money out:
``balance_for_parent`` sums every APPROVED credit with balance remaining.

Same defect class as 0173 (#679) and the same shape as 0168's
``credit_source_unique``: the invariant belongs in the store.

The partial filter is load-bearing, not cosmetic. ``account_credit_ledger``
also holds MANUAL_CREDIT and OVERPAYMENT rows, and those may legitimately
repeat for one enrollment; pinning the filter to the exact key space this
feature owns — ``type == "EARLY_WITHDRAWAL_CREDIT"`` AND
``status == "APPROVED"`` — is what keeps them, and REJECTED/VOIDED
withdrawal credits, unconstrained. A re-credit after a void stays possible.

Duplicates may already exist in production — they are exactly what the race
produced. Creating a unique index over them fails, so a ``DuplicateKeyError``
is logged and the index is skipped rather than crashing boot. Run
``backend/scripts/withdrawal_credit_duplicate_audit.py`` first: it lists the
offending enrollments with each credit's remaining balance and applications
so they can be reconciled by hand, after which this migration is re-run
(delete its row from ``v2_migrations``) to build the index.

Production does NOT run migrations on boot (``V2_RUN_MIGRATIONS_ON_BOOT``
is false there, #629): apply with ``run_pending_migrations`` by hand.
"""

from __future__ import annotations

import logging

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ASCENDING
from pymongo.errors import DuplicateKeyError

log = logging.getLogger(__name__)

version = "0174_early_withdrawal_credit_unique_index"

COLLECTION = "account_credit_ledger"
INDEX_NAME = "early_withdrawal_credit_unique"

#: Mirrors the ``type``/``status`` literals written by
#: ``RecordWithdrawalDecision``. Migrations import no context code, so the
#: values are repeated here; a contract test pins the two together.
EARLY_WITHDRAWAL_CREDIT_TYPE = "EARLY_WITHDRAWAL_CREDIT"
APPROVED_STATUS = "APPROVED"


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    try:
        await db[COLLECTION].create_index(
            [("academy_id", ASCENDING), ("enrollment_id", ASCENDING), ("type", ASCENDING)],
            unique=True,
            name=INDEX_NAME,
            partialFilterExpression={
                "type": EARLY_WITHDRAWAL_CREDIT_TYPE,
                "status": APPROVED_STATUS,
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
                    "run backend/scripts/withdrawal_credit_duplicate_audit.py, "
                    "void the surplus credits, then re-run this migration"
                ),
            },
        )
