"""MongoDB implementation of ``AttendanceSnapshotReader``.

Reads the ``session_attendance_snapshots`` collection — the same
collection written by ``MongoSessionAttendanceSnapshotRepository`` —
but does so without the tenant-scoped base class because the reader
filters by ``academy_id`` explicitly and spans multiple periods in one
query.  This mirrors the approach taken by ``MongoApplicationFunnelReader``.

The reader returns one ``SessionAttendanceSnapshot`` per matching
document.  Aggregation across sessions is the responsibility of the
use case layer; this class stays thin.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.v2.contexts.finance.domain.reporting_snapshots import SessionAttendanceSnapshot

_COLLECTION = "session_attendance_snapshots"


class MongoAttendanceSnapshotReader:
    """Read ``SessionAttendanceSnapshot`` records filtered by academy and periods.

    Args:
        db: An ``AsyncIOMotorDatabase`` (or mongomock-motor equivalent).
    """

    def __init__(self, db: object) -> None:
        # Typed as ``object`` to avoid a hard import of motor at module
        # level; callers pass in the real thing.
        self._col = db[_COLLECTION]  # type: ignore[index]

    async def list_snapshots_for_periods(
        self,
        *,
        academy_id: str,
        periods: list[str],
    ) -> list[SessionAttendanceSnapshot]:
        """Return all snapshots for the given academy within the given periods.

        Args:
            academy_id: Filter to this academy only.
            periods: List of opaque period strings.  An empty list returns
                an empty result immediately without hitting Mongo.

        Returns:
            List of ``SessionAttendanceSnapshot`` instances (unordered).
            Periods with no data simply contribute nothing to the list.
        """
        if not periods:
            return []

        cursor = self._col.find({"academy_id": academy_id, "period": {"$in": periods}})
        results: list[SessionAttendanceSnapshot] = []
        async for doc in cursor:
            results.append(self._from_doc(doc))
        return results

    @staticmethod
    def _from_doc(doc: dict[str, Any]) -> SessionAttendanceSnapshot:
        return SessionAttendanceSnapshot(
            academy_id=str(doc["academy_id"]),
            session_id=str(doc["session_id"]),
            period=str(doc["period"]),
            scheduled_count=int(doc["scheduled_count"]),
            completed_count=int(doc["completed_count"]),
            no_show_count=int(doc["no_show_count"]),
            computed_at=doc["computed_at"]
            if isinstance(doc["computed_at"], datetime)
            else datetime.fromisoformat(str(doc["computed_at"])),
        )
