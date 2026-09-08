"""Indexes and validator for cancelling a single class date (issue #671).

Three changes, all additive:

1. ``account_credit_ledger`` gets a UNIQUE partial index on
   ``(academy_id, source_type, source_id)``. That pair is the idempotency key
   for a class-cancellation credit (``source_id = "<occurrence>:<enrollment>"``)
   — without the index, two admins clicking "Cancel this date" at the same
   instant both pass the pre-read and both credit the family.

   The partial filter is pinned to ``source_type == "occurrence_cancellation"``
   — the key space this feature introduces — and NOT to "any string
   source_type". OVERPAYMENT credits already carry a string ``source_type``
   with ``source_id`` = a payment id or an allocation id, written by a
   non-atomic check-then-insert (``mongo_payment_repo.record_manual_payment``),
   so prod may already hold duplicates: a broader filter would make this
   migration abort on ``DuplicateKeyError`` — taking the two changes below
   with it and never building the index the cancellation path depends on —
   and would turn that pre-existing race into a 500 on a money path.
2. ``session_occurrence_overrides`` gets a UNIQUE index on
   ``(academy_id, session_id, occurrence_id)``. The generator reads at most one
   overlay row per date; the writer upserts on exactly this key.
3. ``session_occurrences`` re-applies its 0133 validator, which now declares
   ``cancelled_at``/``cancelled_by``. The 0133 schemas set no
   ``additionalProperties: false``, so this is documentation rather than a
   fix — but keeping the declared schema complete is what stops the next
   field addition from being the one that 500s in prod (#657).

Safe to re-run: index creation is idempotent, ``collMod`` is a replace.
"""

from __future__ import annotations

import importlib

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ASCENDING

version = "0168_occurrence_cancellation"

#: Mirrors ``backend.v2.contexts.billing.domain.credits
#: .CLASS_CANCELLATION_SOURCE_TYPE``. Migrations import no context code, so the
#: value is repeated here; a contract test pins the two together.
CLASS_CANCELLATION_SOURCE_TYPE = "occurrence_cancellation"


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    await db["account_credit_ledger"].create_index(
        [("academy_id", ASCENDING), ("source_type", ASCENDING), ("source_id", ASCENDING)],
        name="credit_source_unique",
        unique=True,
        partialFilterExpression={"source_type": CLASS_CANCELLATION_SOURCE_TYPE},
    )
    await db["session_occurrence_overrides"].create_index(
        [("academy_id", ASCENDING), ("session_id", ASCENDING), ("occurrence_id", ASCENDING)],
        name="override_occurrence_unique",
        unique=True,
    )

    base = importlib.import_module(
        "backend.v2.migrations.0133_broader_validators_and_outbox_retry_lock"
    )
    validator = base.VALIDATORS["session_occurrences"]
    properties = validator["$jsonSchema"]["properties"]
    assert "cancelled_at" in properties, "0133 session_occurrences must declare cancelled_at"
    assert "cancelled_by" in properties, "0133 session_occurrences must declare cancelled_by"
    await base._apply_validator(db, "session_occurrences", validator)
