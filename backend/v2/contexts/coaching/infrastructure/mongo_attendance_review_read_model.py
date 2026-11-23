"""Read side of the admin attendance review (``ListAttendanceReview``).

Every tenant-owned read goes through ``TenantScopedRepository`` helpers, so the
academy is the request's (``current_academy_id()``), never the boot academy:
PR #1226 fixed exactly that bug on the class-date rows.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any

from backend.v2.contexts.coaching.application.ports import ReviewCorrection, ReviewOccurrence
from backend.v2.shared.occurrences import occurrence_session_id
from backend.v2.shared.tenancy import TenantScopedRepository
from backend.v2.shared.time.mongo import ensure_utc


def _session_name(doc: dict[str, Any] | None) -> str:
    if not doc:
        return "Class"
    return str(doc.get("title") or doc.get("name") or "Class")


class MongoAttendanceReviewReadModel(TenantScopedRepository):
    collection_name = "attendance"

    async def _session_names(self, session_ids: set[str]) -> dict[str, str]:
        cursor = self._find_many_in_collection(
            "sessions",
            {"session_id": {"$in": sorted(session_ids)}},
            {"session_id": 1, "title": 1, "name": 1},
        )
        return {str(doc["session_id"]): _session_name(doc) async for doc in cursor}

    async def occurrences_between(self, start: datetime, end: datetime) -> list[ReviewOccurrence]:
        occurrences = [
            doc
            async for doc in self._find_many_in_collection(
                "session_occurrences",
                {"start_at": {"$gte": start, "$lt": end}, "status": {"$ne": "cancelled"}},
            )
        ]
        if not occurrences:
            return []
        occurrence_ids = [str(doc["occurrence_id"]) for doc in occurrences]
        session_ids = {occurrence_session_id(doc) for doc in occurrences}

        # A voided mark counts as unmarked everywhere downstream (#554).
        marked = Counter(
            [
                str(doc["occurrence_id"])
                async for doc in self._find_many(
                    {"occurrence_id": {"$in": occurrence_ids}, "status": {"$ne": "voided"}}
                )
            ]
        )
        # shortcut: counts only enrollments active *now* (the recurring roster), not
        # one-time make-up/trial roster entries, so a date with only those, or a class
        # whose roster was withdrawn since, is not flagged; needs a departure timestamp to fix.
        enrolled_at_by_session: dict[str, list[datetime | None]] = {}
        async for doc in self._find_many_in_collection(
            "enrollments",
            {"session_id": {"$in": sorted(session_ids)}, "status": "active"},
            {"session_id": 1, "enrolled_at": 1},
        ):
            raw = doc.get("enrolled_at")
            enrolled_at_by_session.setdefault(str(doc["session_id"]), []).append(
                ensure_utc(raw) if isinstance(raw, datetime) else None
            )
        names = await self._session_names(session_ids)

        rows: list[ReviewOccurrence] = []
        for doc in occurrences:
            session_id = occurrence_session_id(doc)
            start_at = ensure_utc(doc["start_at"])
            # Someone who joined after the class date was not on its roster.
            enrolled = [
                at
                for at in enrolled_at_by_session.get(session_id, [])
                if at is None or at <= start_at
            ]
            rows.append(
                ReviewOccurrence(
                    occurrence_id=str(doc["occurrence_id"]),
                    session_id=session_id,
                    session_name=names.get(session_id, "Class"),
                    start_at=start_at,
                    status=str(doc.get("status") or "scheduled"),
                    enrolled_count=len(enrolled),
                    marked_count=marked[str(doc["occurrence_id"])],
                )
            )
        return rows

    async def corrections_since(self, since: datetime) -> list[ReviewCorrection]:
        rows = [doc async for doc in self._find_many({"corrected_at": {"$gte": since}})]
        if not rows:
            return []
        occurrences = {
            str(doc["occurrence_id"]): doc
            async for doc in self._find_many_in_collection(
                "session_occurrences",
                {"occurrence_id": {"$in": sorted({str(r["occurrence_id"]) for r in rows})}},
            )
        }
        students = {
            str(doc["student_id"]): str(doc.get("full_name") or "Student")
            async for doc in self._find_many_in_collection(
                "students",
                {"student_id": {"$in": sorted({str(r["student_id"]) for r in rows})}},
                {"student_id": 1, "full_name": 1},
            )
        }
        session_ids = {
            occurrence_session_id(occurrences[str(r["occurrence_id"])])
            if str(r["occurrence_id"]) in occurrences
            else str(r["session_id"])
            for r in rows
        }
        names = await self._session_names(session_ids)
        corrector_ids = sorted({str(r["corrected_by"]) for r in rows if r.get("corrected_by")})
        # ``users`` is global; the ids come from this academy's own rows.
        correctors = {
            str(doc["user_id"]): str(doc.get("display_name") or doc.get("name") or "")
            async for doc in self._db["users"].find(
                {"user_id": {"$in": corrector_ids}}, {"user_id": 1, "display_name": 1, "name": 1}
            )
        }

        out: list[ReviewCorrection] = []
        for row in rows:
            occurrence = occurrences.get(str(row["occurrence_id"]))
            session_id = occurrence_session_id(occurrence) if occurrence else str(row["session_id"])
            corrected_by = str(row.get("corrected_by") or "")
            out.append(
                ReviewCorrection(
                    attendance_id=str(row["attendance_id"]),
                    occurrence_id=str(row["occurrence_id"]),
                    session_id=session_id,
                    session_name=names.get(session_id, "Class"),
                    start_at=ensure_utc(occurrence["start_at"]) if occurrence else None,
                    student_id=str(row["student_id"]),
                    student_name=students.get(str(row["student_id"]), "Student"),
                    status=row["status"],
                    previous_status=row.get("previous_status"),
                    corrected_at=ensure_utc(row["corrected_at"]),
                    corrected_by_name=correctors.get(corrected_by) or None,
                    reason=row.get("correction_reason"),
                )
            )
        return out
