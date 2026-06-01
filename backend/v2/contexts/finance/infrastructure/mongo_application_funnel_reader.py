"""MongoDB implementation of ``ApplicationFunnelReader``.

Reads the ``onboarding_applications`` collection — the same collection
written by the onboarding context's ``MongoApplicationRepository`` — but
does so without importing that context.  This keeps the finance context
properly isolated while still being able to answer cross-context
analytical queries.

The reader uses a Mongo aggregation pipeline::

    $match  academy_id + optional created_at window
    $group  by status, $sum: 1
    project {_id: 0, status: "$_id", count: 1}

No domain objects are constructed; the result is a plain
``dict[str, int]`` mapping status strings to counts.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

_PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


class MongoApplicationFunnelReader:
    """Aggregate-query reader over ``onboarding_applications``.

    Args:
        db: An ``AsyncIOMotorDatabase`` (or mongomock-motor equivalent).
    """

    def __init__(self, db: object) -> None:
        # Typed as ``object`` to avoid a hard import of motor at the
        # module level; callers pass in the real thing.
        self._col = db["onboarding_applications"]  # type: ignore[index]

    async def get_funnel_counts(self, academy_id: str, period: str | None) -> dict[str, int]:
        """Return ``{status: count}`` for all matching applications.

        Args:
            academy_id: Filter to this academy only.
            period: Optional ``YYYY-MM`` string.  When given, only
                documents whose ``created_at`` falls within that
                calendar month (UTC) are counted.

        Returns:
            Mapping of raw status strings to integer counts.  Statuses
            with zero documents are omitted.  Returns an empty dict
            when no documents match.
        """
        match_stage: dict[str, object] = {"academy_id": academy_id}

        if period is not None:
            if not _PERIOD_RE.fullmatch(period):
                raise ValueError(f"period must be YYYY-MM, got {period!r}")
            year, month = int(period[:4]), int(period[5:])
            start = datetime(year, month, 1, tzinfo=UTC)
            if month == 12:
                end = datetime(year + 1, 1, 1, tzinfo=UTC)
            else:
                end = datetime(year, month + 1, 1, tzinfo=UTC)
            match_stage["created_at"] = {"$gte": start, "$lt": end}

        pipeline = [
            {"$match": match_stage},
            {"$group": {"_id": "$status", "count": {"$sum": 1}}},
            {"$project": {"_id": 0, "status": "$_id", "count": 1}},
        ]

        cursor = self._col.aggregate(pipeline)
        result: dict[str, int] = {}
        async for doc in cursor:
            result[doc["status"]] = int(doc["count"])
        return result
