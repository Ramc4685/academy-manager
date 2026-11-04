"""MongoDB implementation of ``MarkedWithin24hReader`` (#471).

Per-coach compliance: share of a coach's past occurrences whose attendance
was recorded within 24h of the occurrence's ``end_at``. Paying coach =
``actual_coach_id`` when set, else ``scheduled_coach_id`` — the same rule
``MonthlyCoachOccurrenceReaderAdapter`` uses, so compliance % and payout
hours agree on which coach owns an occurrence.

Occurrences past their 24h marking deadline (``end_at + 24h``) count in
the denominator even when nobody has marked attendance at all — those are
non-compliant, not excluded. Only occurrences that have not yet reached
their 24h deadline are excluded from both numerator and denominator,
since those genuinely cannot be judged yet.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

_OCCURRENCE_COLLECTION = "session_occurrences"
_ATTENDANCE_COLLECTION = "attendance"


def _month_bounds(period: str) -> tuple[datetime, datetime]:
    """Parse a ``YYYY-MM`` period string into UTC ``[start, end)`` bounds."""
    year, month = (int(part) for part in period.split("-"))
    start = datetime(year, month, 1, tzinfo=UTC)
    last_day = calendar.monthrange(year, month)[1]
    end = start + timedelta(days=last_day)
    return start, end


@dataclass(frozen=True)
class _ComplianceRow:
    coach_id: str
    marked_within_24h_count: int
    total_marked_count: int


class MongoComplianceReader:
    """Aggregates ``session_occurrences`` + ``attendance`` per coach per period."""

    def __init__(self, db: object) -> None:
        self._occurrences = db[_OCCURRENCE_COLLECTION]  # type: ignore[index]
        self._attendance = db[_ATTENDANCE_COLLECTION]  # type: ignore[index]

    async def compliance_for_periods(
        self, *, academy_id: str, periods: list[str]
    ) -> list[_ComplianceRow]:
        if not periods:
            return []

        now = datetime.now(tz=UTC)
        counts: dict[str, list[int]] = {}  # coach_id -> [within_24h, total]

        for period in periods:
            period_start, period_end = _month_bounds(period)
            match: dict[str, Any] = {
                "academy_id": academy_id,
                "start_at": {"$gte": period_start, "$lt": period_end},
                "end_at": {"$lt": now},
                "status": {"$ne": "cancelled"},
            }
            cursor = self._occurrences.find(
                match,
                {
                    "occurrence_id": 1,
                    "end_at": 1,
                    "scheduled_coach_id": 1,
                    "actual_coach_id": 1,
                },
            )
            async for occ in cursor:
                coach_id = occ.get("actual_coach_id") or occ.get("scheduled_coach_id")
                if not coach_id:
                    continue
                occurrence_id = occ["occurrence_id"]

                end_at = occ["end_at"]
                if not isinstance(end_at, datetime):
                    end_at = datetime.fromisoformat(str(end_at))
                if end_at.tzinfo is None:
                    end_at = end_at.replace(tzinfo=UTC)
                deadline = end_at + timedelta(hours=24)

                earliest = await self._attendance.find(
                    {"academy_id": academy_id, "occurrence_id": occurrence_id},
                    {"marked_at": 1},
                    sort=[("marked_at", 1)],
                    limit=1,
                ).to_list(length=1)
                if not earliest:
                    if deadline >= now:
                        # Deadline hasn't passed yet — genuinely can't be judged.
                        continue
                    # Deadline passed and still unmarked — counts as non-compliant.
                    bucket = counts.setdefault(str(coach_id), [0, 0])
                    bucket[1] += 1
                    continue

                marked_at = earliest[0]["marked_at"]
                if not isinstance(marked_at, datetime):
                    marked_at = datetime.fromisoformat(str(marked_at))
                if marked_at.tzinfo is None:
                    marked_at = marked_at.replace(tzinfo=UTC)

                bucket = counts.setdefault(str(coach_id), [0, 0])
                bucket[1] += 1
                if marked_at <= deadline:
                    bucket[0] += 1

        return [
            _ComplianceRow(
                coach_id=coach_id, marked_within_24h_count=within, total_marked_count=total
            )
            for coach_id, (within, total) in counts.items()
        ]
