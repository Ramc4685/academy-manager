"""Read models feeding coach payout computation.

Extracted verbatim from ``composition/admin.py`` (audit item MT1). These are
the read side of the payout flow: they turn raw ``session_occurrences``,
``coach_attendance`` and ``coach_rates`` documents into the domain shapes
``ComputeCoachPayout`` consumes. The write side of ``coach_rates`` lives in
``mongo_coach_rate_repo`` alongside them.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.v2.contexts.coaching.domain.payout import (
    CoachAttendanceForPayout,
    CoachRate,
    PayableOccurrence,
)
from backend.v2.contexts.coaching.infrastructure.mongo_coach_rate_repo import (
    coach_rate_from_mongo_doc,
)
from backend.v2.shared.billing_type import is_not_billed
from backend.v2.shared.occurrences import (
    effective_occurrence_status,
    occurrence_session_id,
    optional_str,
)
from backend.v2.shared.time.academy_timezone import (
    AcademyTimezoneReader,
    academy_timezone_lookup,
    resolve_academy_clock_timezone,
)


class InvoicedTuitionBasis(Protocol):
    """Invoiced tuition per ``(session_id, "YYYY-MM")`` and the owner's share rules.

    Billing owns the answer (``MongoInvoicedTuitionReadModel``). A missing key
    means the class-month has no counted invoice.
    """

    @property
    def amounts(self) -> Mapping[tuple[str, str], int]: ...

    @property
    def cancelled_class_share(self) -> str: ...

    @property
    def missing_invoices(self) -> str: ...

    @property
    def assistant_pay_from(self) -> str | None: ...

    @property
    def unattributed_invoices(self) -> int: ...


class InvoicedClassTuition(Protocol):
    async def tuition_by_class_month(
        self,
        *,
        academy_id: str,
        session_ids: Iterable[str],
        months: Iterable[str],
    ) -> InvoicedTuitionBasis: ...


class MongoPayableOccurrenceQuery:
    def __init__(
        self,
        db: AsyncIOMotorDatabase[Any],
        *,
        tuition: InvoicedClassTuition,
        academy_timezone: AcademyTimezoneReader | None = None,
    ) -> None:
        self._db = db
        self._tuition = tuition
        self._academy_timezone = academy_timezone or academy_timezone_lookup(db)

    async def list_in_period(
        self,
        academy_id: str,
        period_start: datetime,
        period_end: datetime,
    ) -> list[PayableOccurrence]:
        cursor = self._db["session_occurrences"].find(
            {
                "academy_id": academy_id,
                "start_at": {"$gte": period_start, "$lt": period_end},
            },
            sort=[("start_at", 1)],
        )
        docs = [doc async for doc in cursor]
        occurrence_ids = [str(doc["occurrence_id"]) for doc in docs]
        revenue_by_occurrence, assistants_paid = await self._invoiced_share_by_occurrence(
            academy_id, docs
        )
        attendance_by_occurrence: dict[str, list[CoachAttendanceForPayout]] = {
            occurrence_id: [] for occurrence_id in occurrence_ids
        }
        if occurrence_ids:
            attendance_cursor = self._db["coach_attendance"].find(
                {
                    "academy_id": academy_id,
                    "occurrence_id": {"$in": occurrence_ids},
                },
                sort=[("marked_at", 1)],
            )
            async for row in attendance_cursor:
                occurrence_id = str(row["occurrence_id"])
                attendance_by_occurrence.setdefault(occurrence_id, []).append(
                    CoachAttendanceForPayout(
                        coach_id=str(row["coach_id"]),
                        status=row.get("status", "absent"),
                        role=row.get("role", "lead"),
                        rate_override_minor=(
                            None
                            if row.get("rate_override_minor") is None
                            else int(row["rate_override_minor"])
                        ),
                    )
                )

        return [
            PayableOccurrence(
                occurrence_id=str(doc["occurrence_id"]),
                academy_id=str(doc["academy_id"]),
                start_at=doc["start_at"],
                end_at=doc["end_at"],
                status=effective_occurrence_status(doc),
                scheduled_coach_id=str(doc["scheduled_coach_id"]),
                actual_coach_id=optional_str(doc.get("actual_coach_id")),
                substitute_coach_id=optional_str(doc.get("substitute_coach_id")),
                # Before the academy's assistant pay-from month, assistants are
                # paid outside the app and get no lines (L7).
                assistant_coach_ids=(
                    [str(c) for c in doc.get("assistant_coach_ids") or [] if c]
                    if str(doc["occurrence_id"]) in assistants_paid
                    else []
                ),
                is_payable=bool(doc.get("is_payable", True)),
                coach_attendance=attendance_by_occurrence.get(str(doc["occurrence_id"]), []),
                expected_revenue_minor=revenue_by_occurrence.get(str(doc["occurrence_id"])),
            )
            for doc in docs
        ]

    async def unattributed_invoices(
        self, academy_id: str, period_start: datetime, period_end: datetime
    ) -> int:
        """Counted invoices in the window's academy-local months with no class."""
        tz = ZoneInfo(await resolve_academy_clock_timezone(self._academy_timezone, academy_id))
        first = _as_utc(period_start).astimezone(tz)
        last = (_as_utc(period_end) - timedelta(microseconds=1)).astimezone(tz)
        months, (year, mon) = [], (first.year, first.month)
        while (year, mon) <= (last.year, last.month):
            months.append(f"{year:04d}-{mon:02d}")
            year, mon = year + (mon == 12), mon % 12 + 1
        basis = await self._tuition.tuition_by_class_month(
            academy_id=academy_id, session_ids=(), months=months
        )
        return basis.unattributed_invoices

    async def _invoiced_share_by_occurrence(
        self,
        academy_id: str,
        occurrence_docs: list[dict[str, Any]],
    ) -> tuple[dict[str, int], set[str]]:
        """Each occurrence's share of its class's invoiced tuition for the month.

        The month is the academy-local month (the clock that labels invoice
        periods), so a Saturday 7pm class on Oct 31 counts in October. The
        divisor is the class's payable occurrences in that month, independent
        of the query window (#504): non-cancelled ones under ``ran_only`` (the
        coach keeps the whole month when a class is cancelled), every one under
        ``all_scheduled``. Shares are whole cents and sum exactly to the
        month's tuition: the remainder goes one cent at a time to the earliest
        classes.

        A class-month with no invoices is left out (a blocking warning for a
        percent coach downstream), unless the academy pays 0 for it.

        Also returns the occurrences whose assistants are paid in the app: those
        in or after the academy's ``assistant_pay_from`` month.
        """
        if not occurrence_docs:
            return {}, set()
        tz = ZoneInfo(await resolve_academy_clock_timezone(self._academy_timezone, academy_id))
        local_month = {
            str(doc["occurrence_id"]): f"{_as_utc(doc['start_at']).astimezone(tz):%Y-%m}"
            for doc in occurrence_docs
        }
        month_of: dict[str, tuple[str, str]] = {}
        for doc in occurrence_docs:
            session_id = occurrence_session_id(doc)
            if session_id:
                month_of[str(doc["occurrence_id"])] = (
                    session_id,
                    local_month[str(doc["occurrence_id"])],
                )

        basis = await self._tuition.tuition_by_class_month(
            academy_id=academy_id,
            session_ids={sid for sid, _ in month_of.values()},
            months=set(local_month.values()),
        )
        pay_from = basis.assistant_pay_from
        assistants_paid = (
            {occ for occ, month in local_month.items() if month >= pay_from} if pay_from else set()
        )
        share_of: dict[str, int] = {}
        for session_id, month in sorted(set(month_of.values())):
            tuition = basis.amounts.get((session_id, month))
            month_start, month_end = _local_month_bounds(month, tz)
            if tuition is None:
                # A class whose only children are not billed has nothing to
                # invoice: its base is $0, not a missing invoice.
                if basis.missing_invoices != "pay_zero" and not (
                    await self._only_not_billed_children(
                        academy_id, session_id, month_start, month_end
                    )
                ):
                    continue
                tuition = 0
            query: dict[str, Any] = {
                "academy_id": academy_id,
                "session_id": session_id,
                "start_at": {"$gte": month_start, "$lt": month_end},
                "is_payable": {"$ne": False},
            }
            if basis.cancelled_class_share != "all_scheduled":
                query["status"] = {"$ne": "cancelled"}
            ids = [
                str(row["occurrence_id"])
                async for row in self._db["session_occurrences"].find(
                    query, {"occurrence_id": 1}, sort=[("start_at", 1), ("occurrence_id", 1)]
                )
            ]
            if not ids:
                continue
            base, remainder = divmod(tuition, len(ids))
            for index, occurrence_id in enumerate(ids):
                share_of[occurrence_id] = base + (1 if index < remainder else 0)
        return {
            occurrence_id: share_of[occurrence_id]
            for occurrence_id in month_of
            if occurrence_id in share_of
        }, assistants_paid

    async def _only_not_billed_children(
        self, academy_id: str, session_id: str, month_start: datetime, month_end: datetime
    ) -> bool:
        """True when the class has enrolled children and none was billed that month.

        Active, paused and held rows count; one billed child among them keeps
        the missing-invoice warning (the class should have been invoiced). A
        child marked not billed after the month ended was billed that month,
        so marking today never hides an older month's missing invoice; one
        whose billing started after the month began was not billed that month.
        A child who left during the month still counts. Imported ``NoCharge``
        rows carry no mark time and count every month.
        """
        rows = [
            row
            async for row in self._db["enrollments"].find(
                {
                    "academy_id": academy_id,
                    "session_id": session_id,
                    "is_deleted": {"$ne": True},
                    "$or": [
                        {"status": {"$in": list(_PAYROLL_ROSTER_STATUSES)}},
                        {"updated_at": {"$gte": month_start}},
                    ],
                },
                {"billing_type": 1, "not_billed_at": 1, "billing_started_at": 1},
            )
        ]

        def not_billed_that_month(row: dict[str, Any]) -> bool:
            if is_not_billed(row):
                marked = row.get("not_billed_at")
                return marked is None or _as_utc(marked) < month_end
            started = row.get("billing_started_at")
            return started is not None and _as_utc(started) >= month_start

        return bool(rows) and all(not_billed_that_month(row) for row in rows)


#: Enrollment statuses that put a child in a class for payroll's not-billed check.
_PAYROLL_ROSTER_STATUSES = ("active", "paused", "held")


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _local_month_bounds(month: str, tz: ZoneInfo) -> tuple[datetime, datetime]:
    year, mon = (int(part) for part in month.split("-"))
    start = datetime(year, mon, 1, tzinfo=tz)
    end = datetime(year + (mon == 12), mon % 12 + 1, 1, tzinfo=tz)
    return start.astimezone(UTC), end.astimezone(UTC)


class MongoCoachRateLookup:
    def __init__(self, db: AsyncIOMotorDatabase[Any]) -> None:
        self._db = db

    async def find_for_coach_at(self, coach_id: str, at_time: datetime) -> CoachRate | None:
        from backend.v2.shared.tenancy import current_academy_id

        doc = await self._db["coach_rates"].find_one(
            {
                "academy_id": current_academy_id(),
                "coach_id": coach_id,
                "effective_from": {"$lte": at_time},
                "$or": [
                    {"effective_until": {"$exists": False}},
                    {"effective_until": None},
                    {"effective_until": {"$gt": at_time}},
                ],
            },
            sort=[("effective_from", -1)],
        )
        if doc is None:
            return None
        return coach_rate_from_mongo_doc(doc)

    async def list_for_coach(self, coach_id: str) -> list[CoachRate]:
        from backend.v2.shared.tenancy import current_academy_id

        cursor = self._db["coach_rates"].find(
            {"academy_id": current_academy_id(), "coach_id": coach_id},
            sort=[("effective_from", 1)],
        )
        return [coach_rate_from_mongo_doc(doc) async for doc in cursor]


class MonthlyCoachOccurrenceReaderAdapter:
    """Groups session_occurrences by paying coach for a calendar month.

    Paying coach = actual_coach_id when set, else scheduled_coach_id.
    Clock-derived completion: end_at < now OR status == 'completed'.

    A scheduled coach displaced by a replacement is also returned, with
    ``session_count`` 0, so payroll generation still produces a period for
    them to carry the ``replaced_by_actual_coach`` trace.
    """

    def __init__(
        self,
        collection: Any,
        *,
        assistant_pay_from: Callable[[str], Awaitable[str | None]] | None = None,
    ) -> None:
        self._col = collection
        #: The academy's first month assistants are paid in the app; no
        #: reader (or ``None``) means assistants get no payroll rows.
        self._assistant_pay_from = assistant_pay_from

    async def coaches_with_occurrences(
        self,
        *,
        academy_id: str,
        period_start: datetime,
        period_end: datetime,
    ) -> list[Any]:
        from dataclasses import dataclass

        @dataclass(frozen=True)
        class _Row:
            coach_id: str
            session_count: int

        now = datetime.now(tz=UTC)
        match: dict[str, Any] = {
            "academy_id": academy_id,
            "start_at": {"$gte": period_start, "$lt": period_end},
            "is_payable": {"$ne": False},
            "status": {"$ne": "cancelled"},
            "$or": [{"status": "completed"}, {"end_at": {"$lt": now}}],
        }
        pipeline = [
            {"$match": match},
            {"$project": {"coach": {"$ifNull": ["$actual_coach_id", "$scheduled_coach_id"]}}},
            {"$group": {"_id": "$coach", "session_count": {"$sum": 1}}},
        ]
        rows = [
            _Row(coach_id=str(doc["_id"]), session_count=int(doc["session_count"]))
            async for doc in self._col.aggregate(pipeline)
        ]

        # A scheduled coach displaced by a replacement is not the paying coach,
        # so the grouping above misses them. They still need a payout period to
        # carry the ``replaced_by_actual_coach`` trace (#228) — without one, a
        # mistaken ``actual_coach_id`` has no review surface. They are added with
        # ``session_count`` 0: the occurrence is one session of work and belongs
        # to whoever was paid, so it must not be double-counted.
        known = {row.coach_id for row in rows}
        displaced: set[str] = set()
        cursor = self._col.find(
            {**match, "actual_coach_id": {"$nin": [None, ""]}},
            {"scheduled_coach_id": 1, "actual_coach_id": 1},
        )
        async for doc in cursor:
            scheduled = doc.get("scheduled_coach_id")
            actual = doc.get("actual_coach_id")
            if scheduled and actual != scheduled and scheduled not in known:
                displaced.add(str(scheduled))
        rows.extend(_Row(coach_id=coach_id, session_count=0) for coach_id in sorted(displaced))

        # Assistants are paid their own line per assisted class (L7), so they
        # need a payout period too; their assisted classes add to their count.
        # Only from the academy's assistant pay-from month on. The window's UTC
        # midpoint always falls inside the academy-local month it bounds.
        pay_from = await self._assistant_pay_from(academy_id) if self._assistant_pay_from else None
        month = f"{period_start + (period_end - period_start) / 2:%Y-%m}"
        if pay_from is None or month < pay_from:
            return rows
        assisted: dict[str, int] = {}
        cursor = self._col.find(
            {**match, "assistant_coach_ids.0": {"$exists": True}},
            {"scheduled_coach_id": 1, "actual_coach_id": 1, "assistant_coach_ids": 1},
        )
        async for doc in cursor:
            paying = doc.get("actual_coach_id") or doc.get("scheduled_coach_id")
            for assistant in set(doc.get("assistant_coach_ids") or []):
                if assistant and assistant != paying:
                    assisted[str(assistant)] = assisted.get(str(assistant), 0) + 1
        by_coach = {row.coach_id: row for row in rows}
        for coach_id, count in sorted(assisted.items()):
            row = by_coach.get(coach_id)
            by_coach[coach_id] = _Row(
                coach_id=coach_id, session_count=(row.session_count if row else 0) + count
            )
        return list(by_coach.values())
