"""Per-parent calendar-feed link version (tenant-scoped).

Only a counter is stored: the link itself is an HMAC over it
(``application/calendar_feed.py``), so a leaked database never yields a
working link and "Reset link" is one ``$inc``.
"""

from __future__ import annotations

from backend.v2.shared.tenancy import TenantScopedRepository


# Never delete rows here: a missing row reads as version 0, which would
# bring a parent's original (reset) link back to life.
class MongoCalendarFeedLinkRepository(TenantScopedRepository):
    collection_name = "calendar_feed_links"

    async def version_for(self, parent_id: str) -> int:
        doc = await self._find_one({"parent_id": parent_id})
        return int((doc or {}).get("version") or 0)

    async def bump(self, parent_id: str) -> int:
        doc = await self._find_one_and_update(
            {"parent_id": parent_id}, {"$inc": {"version": 1}}, upsert=True
        )
        return int((doc or {}).get("version") or 0)
