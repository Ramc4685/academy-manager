"""MongoDB implementation of ``HeldClassReader``.

Attendance trends and coach utilisation read the class dates themselves
(``session_occurrences``) instead of snapshot collections nothing wrote, and
classify them with ``backend.v2.shared.reporting_definitions`` — the same
held-class, attendance-by-class-date and month rules month close uses, so the
three agree for any month.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from backend.v2.shared.reporting_definitions import (
    as_utc,
    attendance_for_classes_filter,
    class_state,
    month_window,
)
from backend.v2.shared.time import academy_timezone_lookup, resolve_reporting_timezone

_FOUR_DP = Decimal("0.0001")


@dataclass(frozen=True)
class _ClassCounts:
    period: str
    scheduled_count: int
    completed_count: int
    no_show_count: int
    cancelled_count: int


@dataclass(frozen=True)
class _CoachHours:
    coach_id: str
    period: str
    hours: Decimal
    payout_minor: int


class MongoHeldClassReader:
    def __init__(self, db: Any, *, clock: Any = None) -> None:
        self._db = db
        self._clock = clock or (lambda: datetime.now(UTC))

    async def _windows(
        self, academy_id: str, periods: list[str]
    ) -> list[tuple[str, datetime, datetime]]:
        zone = await resolve_reporting_timezone(academy_timezone_lookup(self._db), academy_id)
        return [(period, *month_window(period, zone)) for period in periods]

    def _occurrences(self, academy_id: str, start: datetime, end: datetime) -> Any:
        return self._db["session_occurrences"].find(
            {"academy_id": academy_id, "start_at": {"$gte": start, "$lt": end}},
            {
                "occurrence_id": 1,
                "status": 1,
                "start_at": 1,
                "end_at": 1,
                "scheduled_coach_id": 1,
                "actual_coach_id": 1,
                "assistant_coach_ids": 1,
            },
        )

    async def class_counts_for_periods(
        self, *, academy_id: str, periods: list[str]
    ) -> list[_ClassCounts]:
        now = self._clock()
        rows: list[_ClassCounts] = []
        for period, start, end in await self._windows(academy_id, periods):
            held = upcoming = cancelled = 0
            class_ids: list[str] = []
            async for occurrence in self._occurrences(academy_id, start, end):
                state = class_state(occurrence, now=now)
                if state == "cancelled":
                    cancelled += 1
                    continue
                if state == "held":
                    held += 1
                else:
                    upcoming += 1
                if occurrence.get("occurrence_id"):
                    class_ids.append(str(occurrence["occurrence_id"]))
            no_show = 0
            if class_ids:
                no_show = await self._db["attendance"].count_documents(
                    {
                        "academy_id": academy_id,
                        **attendance_for_classes_filter(class_ids),
                        "status": "absent",
                    }
                )
            rows.append(
                _ClassCounts(
                    period=period,
                    scheduled_count=held + upcoming,
                    completed_count=held,
                    no_show_count=no_show,
                    cancelled_count=cancelled,
                )
            )
        return rows

    async def coach_hours_for_periods(
        self, *, academy_id: str, periods: list[str]
    ) -> list[_CoachHours]:
        now = self._clock()
        rows: list[_CoachHours] = []
        for period, start, end in await self._windows(academy_id, periods):
            minutes: dict[str, Decimal] = {}
            async for occurrence in self._occurrences(academy_id, start, end):
                if class_state(occurrence, now=now) != "held":
                    continue
                began, ended = as_utc(occurrence.get("start_at")), as_utc(occurrence.get("end_at"))
                if began is None or ended is None or ended <= began:
                    continue
                length = Decimal((ended - began).total_seconds()) / Decimal(60)
                # Paying coach (actual, else scheduled) plus assistants: the
                # same people payroll pays for this class.
                lead = occurrence.get("actual_coach_id") or occurrence.get("scheduled_coach_id")
                coaches = {
                    str(c) for c in [lead, *(occurrence.get("assistant_coach_ids") or [])] if c
                }
                for coach_id in coaches:
                    minutes[coach_id] = minutes.get(coach_id, Decimal(0)) + length
            payout: dict[str, int] = {}
            async for doc in self._db["payout_periods"].find(
                # Approved or paid only: a draft is not a payout yet.
                {
                    "academy_id": academy_id,
                    "period_start": {"$gte": start, "$lt": end},
                    "status": {"$in": ["approved", "paid"]},
                },
                {"coach_id": 1, "total_minor": 1},
            ):
                coach_id = str(doc.get("coach_id") or "")
                if coach_id:
                    payout[coach_id] = payout.get(coach_id, 0) + int(doc.get("total_minor") or 0)
            for coach_id in sorted(set(minutes) | set(payout)):
                rows.append(
                    _CoachHours(
                        coach_id=coach_id,
                        period=period,
                        hours=(minutes.get(coach_id, Decimal(0)) / Decimal(60)).quantize(_FOUR_DP),
                        payout_minor=payout.get(coach_id, 0),
                    )
                )
        return rows
