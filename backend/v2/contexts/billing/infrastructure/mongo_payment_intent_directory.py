"""Platform-scoped lookup: Stripe PaymentIntent id -> the academies that recorded it.

A dispute on a PLATFORM charge (the house academy, or a legacy destination
charge) arrives with no ``account`` and no ``metadata.academy_id``: Stripe
puts no metadata on a dispute. In ``multi_academy`` mode ingest has no tenant
marker for it, so it used to be quarantined as unattributed (#982). The
disputed PaymentIntent is the one link back to a tenant: the ledger payment
that recorded it.

Like ``MongoConnectedAccountDirectory`` this is a deliberate, narrow exception
to tenant scoping: ingest runs before any tenant scope exists. It reads only
``academy_id`` and ``stripe_account_id`` of the ``ledger_payments`` rows with
the exact ``stripe_payment_intent_id`` (index from migration 0245), returns at
most a few rows so the caller can see ambiguity, and never writes.

Listed in ``APPROVED_CROSS_TENANT_EXCEPTIONS`` in
``tests/test_no_raw_tenant_mongo_access.py``; keep it read-only.
"""

from __future__ import annotations

from typing import Any


class MongoPaymentIntentDirectory:
    """Read-only, cross-academy ``stripe_payment_intent_id -> owners`` lookup."""

    def __init__(self, db: Any) -> None:  # AsyncIOMotorDatabase
        self._db = db

    async def owners_of_payment_intent(
        self, stripe_payment_intent_id: str
    ) -> list[tuple[str, str | None]]:
        """``(academy_id, stripe_account_id)`` of up to three ledger payments
        recording the intent; empty when none does."""
        if not stripe_payment_intent_id:
            return []
        cursor = (
            self._db["ledger_payments"]
            .find(
                {"stripe_payment_intent_id": stripe_payment_intent_id},
                projection={"_id": 0, "academy_id": 1, "stripe_account_id": 1},
            )
            .limit(3)
        )
        return [
            (str(doc.get("academy_id") or ""), doc.get("stripe_account_id") or None)
            async for doc in cursor
        ]
