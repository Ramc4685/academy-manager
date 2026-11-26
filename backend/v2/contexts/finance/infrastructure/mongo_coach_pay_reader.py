"""MongoDB implementation of ``CoachPayReader`` (S59).

Two narrow reads for one coach and one academy month. Every query carries
the request academy explicitly and the payout projection names only the
fields a coach may see, so lines, rates and revenue never leave Mongo.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from backend.v2.contexts.finance.application.use_cases.coach_pay_summary import (
    CoachPayClass,
    PayRole,
    PayslipRow,
)
from backend.v2.shared.reporting_definitions import as_utc, class_state, report_zone
from backend.v2.shared.time import academy_timezone_lookup, resolve_reporting_timezone

_PAYSLIP_FIELDS = {
    "period_start": 1,
    "period_end": 1,
    "status": 1,
    "total_minor": 1,
    "currency": 1,
    "approved_at": 1,
    "paid_at": 1,
    "paid_method": 1,
    "paid_amount_minor": 1,
}


def taught_role(occurrence: dict[str, Any], coach_id: str) -> PayRole | None:
    """Lead if they taught it (actual, else substitute, else scheduled coach);
    a substitute with no actual coach set is a cover; else listed assistant."""
    actual = occurrence.get("actual_coach_id")
    substitute = occurrence.get("substitute_coach_id")
    lead = actual or substitute or occurrence.get("scheduled_coach_id")
    if lead == coach_id:
        return "cover" if not actual and substitute == coach_id else "lead"
    if coach_id in (occurrence.get("assistant_coach_ids") or []):
        return "assistant"
    return None


class MongoCoachPayReader:
    def __init__(self, db: Any, *, clock: Any) -> None:
        self._db = db
        self._clock = clock

    async def academy_timezone(self, academy_id: str) -> str | None:
        return await resolve_reporting_timezone(academy_timezone_lookup(self._db), academy_id)

    async def taught_classes(
        self, *, academy_id: str, coach_id: str, start: datetime, end: datetime
    ) -> list[CoachPayClass]:
        now = self._clock()
        rows: list[tuple[dict[str, Any], PayRole]] = []
        async for occurrence in self._db["session_occurrences"].find(
            {
                "academy_id": academy_id,
                "start_at": {"$gte": start, "$lt": end},
                "status": {"$ne": "cancelled"},
                "$or": [
                    {"scheduled_coach_id": coach_id},
                    {"actual_coach_id": coach_id},
                    {"substitute_coach_id": coach_id},
                    {"assistant_coach_ids": coach_id},
                ],
            }
        ):
            if class_state(occurrence, now=now) != "held":
                continue
            role = taught_role(occurrence, coach_id)
            if role is not None:
                rows.append((occurrence, role))
        session_ids = sorted(
            {str(o.get("template_session_id") or o.get("session_id") or "") for o, _ in rows}
        )
        titles = {
            str(doc.get("session_id")): str(doc.get("title") or doc.get("name") or "Class")
            async for doc in self._db["sessions"].find(
                {"academy_id": academy_id, "session_id": {"$in": session_ids}},
                {"session_id": 1, "title": 1, "name": 1},
            )
        }
        result: list[CoachPayClass] = []
        for occurrence, role in rows:
            began, ended = as_utc(occurrence.get("start_at")), as_utc(occurrence.get("end_at"))
            if began is None or ended is None or ended <= began:
                continue
            sid = str(occurrence.get("template_session_id") or occurrence.get("session_id") or "")
            result.append(
                CoachPayClass(
                    occurrence_id=str(occurrence.get("occurrence_id") or ""),
                    start_at=began,
                    class_name=titles.get(sid, "Class"),
                    minutes=int((ended - began).total_seconds() // 60),
                    role=role,
                )
            )
        return result

    async def released_payslip(
        self, *, academy_id: str, coach_id: str, start: datetime, end: datetime
    ) -> PayslipRow | None:
        cursor = (
            self._db["payout_periods"]
            .find(
                {
                    "academy_id": academy_id,
                    "coach_id": coach_id,
                    # Never a draft: the query itself refuses one.
                    "status": {"$in": ["approved", "paid"]},
                    "period_start": {"$lt": end},
                    "period_end": {"$gt": start},
                },
                _PAYSLIP_FIELDS,
            )
            .sort("period_start", -1)
            .limit(1)
        )
        docs = [doc async for doc in cursor]
        if not docs:
            return None
        doc = docs[0]
        zone = report_zone(await self.academy_timezone(academy_id))

        def local_day(value: object, *, exclusive: bool = False) -> date | None:
            instant = as_utc(value)
            if instant is None:
                return None
            if exclusive:
                instant -= timedelta(microseconds=1)
            return instant.astimezone(zone).date()

        return PayslipRow(
            period_start=local_day(doc.get("period_start")) or start.date(),
            period_end=local_day(doc.get("period_end"), exclusive=True) or end.date(),
            status=str(doc.get("status") or ""),
            total_minor=int(doc.get("total_minor") or 0),
            currency=str(doc.get("currency") or "usd"),
            approved_on=local_day(doc.get("approved_at")),
            paid_on=local_day(doc.get("paid_at")),
            paid_method=doc.get("paid_method") or None,
            paid_amount_minor=(
                int(doc["paid_amount_minor"]) if doc.get("paid_amount_minor") is not None else None
            ),
        )
