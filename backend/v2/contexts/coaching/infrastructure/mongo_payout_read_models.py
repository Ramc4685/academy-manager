"""Read models feeding coach payout computation.

Extracted verbatim from ``composition/admin.py`` (audit item MT1). These are
the read side of the payout flow: they turn raw ``session_occurrences``,
``coach_attendance`` and ``coach_rates`` documents into the domain shapes
``ComputeCoachPayout`` consumes. The write side of ``coach_rates`` lives in
``mongo_coach_rate_repo`` alongside them.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.v2.contexts.coaching.domain.payout import (
    CoachAttendanceForPayout,
    CoachRate,
    PayableOccurrence,
)
from backend.v2.contexts.coaching.infrastructure.mongo_coach_rate_repo import (
    coach_rate_from_mongo_doc,
)
from backend.v2.shared.money import round_money_minor
from backend.v2.shared.occurrences import (
    effective_occurrence_status,
    occurrence_session_id,
    optional_str,
)


class MongoPayableOccurrenceQuery:
    def __init__(self, db: AsyncIOMotorDatabase[Any]) -> None:
        self._db = db

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
        revenue_by_session = await self._expected_revenue_by_session(academy_id, docs)
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
                is_payable=bool(doc.get("is_payable", True)),
                coach_attendance=attendance_by_occurrence.get(str(doc["occurrence_id"]), []),
                expected_revenue_minor=revenue_by_session.get(occurrence_session_id(doc)),
            )
            for doc in docs
        ]

    async def _expected_revenue_by_session(
        self,
        academy_id: str,
        occurrence_docs: list[dict[str, Any]],
    ) -> dict[str, int]:
        """Expected revenue per occurrence = monthly session price prorated
        across the session's non-cancelled payable occurrences in the
        requested period, then multiplied by active enrollments.

        Used as the basis for ``percent_of_revenue`` coach rates. Sessions
        without a configured ``amount_cents`` are omitted, which surfaces
        downstream as ``unpaid_occurrence_ids`` instead of silently paying 0.
        """
        session_ids = sorted(
            {occurrence_session_id(doc) for doc in occurrence_docs if occurrence_session_id(doc)}
        )
        if not session_ids:
            return {}

        price_by_session: dict[str, int] = {}
        session_cursor = self._db["sessions"].find(
            {"academy_id": academy_id, "session_id": {"$in": session_ids}},
            {"session_id": 1, "amount_cents": 1},
        )
        async for row in session_cursor:
            amount = row.get("amount_cents")
            if amount is not None:
                price_by_session[str(row["session_id"])] = int(amount)

        if not price_by_session:
            return {}

        occurrences_by_session: dict[str, int] = dict.fromkeys(price_by_session, 0)
        for doc in occurrence_docs:
            session_id = occurrence_session_id(doc)
            if session_id not in occurrences_by_session:
                continue
            if doc.get("is_payable") is False:
                continue
            if str(doc.get("status", "scheduled")) == "cancelled":
                continue
            occurrences_by_session[session_id] += 1

        enrolled_by_session: dict[str, int] = dict.fromkeys(price_by_session, 0)
        enrollment_cursor = self._db["enrollments"].find(
            {
                "academy_id": academy_id,
                "session_id": {"$in": list(price_by_session)},
                "status": "active",
                "is_deleted": {"$ne": True},
            },
            {"session_id": 1},
        )
        async for row in enrollment_cursor:
            session_id = str(row["session_id"])
            enrolled_by_session[session_id] = enrolled_by_session.get(session_id, 0) + 1

        return {
            session_id: round_money_minor(
                Decimal(price_by_session[session_id])
                * Decimal(enrolled_by_session.get(session_id, 0))
                / Decimal(occurrences_by_session[session_id])
            )
            for session_id in price_by_session
            if occurrences_by_session.get(session_id, 0) > 0
        }


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
    """

    def __init__(self, collection: Any) -> None:
        self._col = collection

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
        pipeline = [
            {
                "$match": {
                    "academy_id": academy_id,
                    "start_at": {"$gte": period_start, "$lt": period_end},
                    "is_payable": {"$ne": False},
                    "status": {"$ne": "cancelled"},
                    "$or": [{"status": "completed"}, {"end_at": {"$lt": now}}],
                }
            },
            {"$project": {"coach": {"$ifNull": ["$actual_coach_id", "$scheduled_coach_id"]}}},
            {"$group": {"_id": "$coach", "session_count": {"$sum": 1}}},
        ]
        return [
            _Row(coach_id=str(doc["_id"]), session_count=int(doc["session_count"]))
            async for doc in self._col.aggregate(pipeline)
        ]
