"""Mongo repository for ``crm_inquiry_ack_throttle`` (migration 0218).

The per-inbox half of the inquiry acknowledgement claim: one row per academy,
canonical mailbox and UTC day under a unique index, so claiming is a single
insert and of any number of concurrent submissions for variants of one inbox
exactly one wins. A claim
is an upsert, so a sequential repeat loses even without the index. The per-contact half stays on ``crm_contacts``
(``MongoCrmContactRepository.try_claim_acknowledgement``).
"""

from __future__ import annotations

from datetime import UTC, datetime

from pymongo.errors import DuplicateKeyError

from backend.v2.shared.tenancy import TenantScopedRepository


class MongoInquiryAckThrottleRepository(TenantScopedRepository):
    collection_name = "crm_inquiry_ack_throttle"

    async def try_claim(self, mailbox: str, *, at: datetime) -> bool:
        """Claim this inbox's one acknowledgement for ``at``'s UTC day."""
        # Upsert, not insert: a repeat claim loses even before the unique index
        # exists; the index (migration 0218) closes the concurrent-upsert race.
        try:
            result = await self._update_one(
                {"mailbox": mailbox, "day": _day(at)},
                {"$setOnInsert": {"claimed_at": at}},
                upsert=True,
            )
        except DuplicateKeyError:
            return False
        return result.upserted_id is not None

    async def release(self, mailbox: str, *, at: datetime) -> None:
        """Give the claim made with the same ``at`` back (nothing was sent)."""
        await self._delete_one({"mailbox": mailbox, "day": _day(at)})

    async def count_since(self, since: datetime) -> int:
        """Claims this academy holds from ``since`` on (the hourly cap)."""
        return await self._count({"claimed_at": {"$gte": since}})


def _day(at: datetime) -> str:
    return at.astimezone(UTC).date().isoformat()
