"""Platform-scoped lookup: Stripe connected account id -> owning academy.

Every academy other than the house academy is charged with DIRECT charges on
its own connected account, so Stripe delivers that academy's payment events
as Connect events: the top-level ``account`` names the account they happened
on, and that account is the only trustworthy tenant marker on them. The one
``/webhooks/stripe`` endpoint is served by the boot academy's handler, which
therefore has to find the owner of an account it does not own.

``MongoConnectedAccountRepository`` cannot do that by design: it is
tenant-scoped, so it only ever resolves the CURRENT academy's own account.
This reader is the deliberate, narrow exception. It is NOT a
``TenantScopedRepository``; it reads one field (``academy_id``) of one row by
the exact ``stripe_account_id``, which the unique index from migration 0139
(``academy_connected_accounts_stripe_account``) maps to at most one academy.
It never writes, and it never returns anything but the owner's academy id.

It is listed in ``APPROVED_CROSS_TENANT_EXCEPTIONS`` in
``tests/test_no_raw_tenant_mongo_access.py``; keep it read-only.
"""

from __future__ import annotations

from typing import Any


class MongoConnectedAccountDirectory:
    """Read-only, cross-academy ``stripe_account_id -> academy_id`` lookup."""

    def __init__(self, db: Any) -> None:  # AsyncIOMotorDatabase
        self._db = db

    async def owner_academy_id(self, stripe_account_id: str) -> str | None:
        """The academy that owns ``stripe_account_id``, or None when no academy
        does. A disconnected account still resolves to its owner: refunds and
        disputes on it keep arriving after an owner disconnect."""
        if not stripe_account_id:
            return None
        doc = await self._db["academy_connected_accounts"].find_one(
            {"stripe_account_id": stripe_account_id},
            projection={"_id": 0, "academy_id": 1},
        )
        if not doc:
            return None
        owner = doc.get("academy_id")
        return str(owner) if owner else None
