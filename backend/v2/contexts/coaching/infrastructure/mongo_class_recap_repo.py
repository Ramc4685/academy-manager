"""Mongo repositories for class recaps and the private reports behind them.

``class_recaps``: one row per occurrence (unique, migration 0243); writes are a
compare-and-set on ``revision``; ``practice`` is per child.
``class_recap_reports``: insert-only raw coach reports (only the owner's
resolve stamp is ever set later), kept apart so no parent read touches them.
``StudentConfirmedAttendance`` reads the existing ``attendance`` collection
(index ``admin_student_attendance_lookup``) for the parent's own-child list.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pymongo.errors import DuplicateKeyError

from backend.v2.contexts.coaching.domain.class_recap import (
    CONFIRMED_PRESENT,
    ChildPass,
    ChildPractice,
    ClassRecap,
    ClassReport,
    PassClaim,
)
from backend.v2.shared.tenancy import TenantScopedRepository


class MongoClassRecapRepository(TenantScopedRepository):
    collection_name = "class_recaps"

    @staticmethod
    def _to_domain(doc: dict[str, Any]) -> ClassRecap:
        return ClassRecap(
            recap_id=str(doc["recap_id"]),
            academy_id=str(doc["academy_id"]),
            occurrence_id=str(doc["occurrence_id"]),
            session_id=str(doc["session_id"]),
            class_starts_at=doc["class_starts_at"],
            taught_skill_ids=tuple(doc.get("taught_skill_ids") or ()),
            practice=tuple(
                ChildPractice(student_id=str(row["student_id"]), skill_ids=tuple(row["skill_ids"]))
                for row in doc.get("practice") or ()
            ),
            passes=tuple(
                ChildPass(
                    student_id=str(row["student_id"]),
                    skill_id=str(row["skill_id"]),
                    added_revision=int(row["added_revision"]),
                )
                for row in doc.get("passes") or ()
            ),
            revision=int(doc.get("revision") or 0),
            last_mutation_id=doc.get("last_mutation_id"),
            source=doc.get("source") or "direct",
            source_report_id=doc.get("source_report_id"),
            updated_by=str(doc["updated_by"]),
            updated_at=doc["updated_at"],
        )

    async def get(self, occurrence_id: str) -> ClassRecap | None:
        doc = await self._find_one({"occurrence_id": occurrence_id})
        return self._to_domain(doc) if doc else None

    async def save(self, recap: ClassRecap, *, expected_revision: int) -> bool:
        body = recap.model_dump(exclude={"academy_id"})
        body["taught_skill_ids"] = list(recap.taught_skill_ids)
        body["practice"] = [
            {"student_id": row.student_id, "skill_ids": list(row.skill_ids)}
            for row in recap.practice
        ]
        body["passes"] = [row.model_dump() for row in recap.passes]
        if expected_revision == 0:
            try:
                await self._insert_one(body)
            except DuplicateKeyError:
                return False
            return True
        result = await self._update_one(
            {"occurrence_id": recap.occurrence_id, "revision": expected_revision},
            {"$set": body},
        )
        return bool(result.matched_count)

    async def list_for_occurrences(self, occurrence_ids: list[str]) -> list[ClassRecap]:
        if not occurrence_ids:
            return []
        cursor = self._find_many({"occurrence_id": {"$in": occurrence_ids}})
        return [self._to_domain(doc) async for doc in cursor]

    async def page_for_occurrences(
        self,
        occurrence_ids: list[str],
        *,
        before: tuple[datetime, str] | None,
        limit: int,
    ) -> list[ClassRecap]:
        if not occurrence_ids:
            return []
        filter_: dict[str, Any] = {"occurrence_id": {"$in": occurrence_ids}}
        if before is not None:
            at, occurrence_id = before
            filter_["$or"] = [
                {"class_starts_at": {"$lt": at}},
                {"class_starts_at": at, "occurrence_id": {"$lt": occurrence_id}},
            ]
        cursor = self._find_many(
            filter_, sort=[("class_starts_at", -1), ("occurrence_id", -1)], limit=limit
        )
        return [self._to_domain(doc) async for doc in cursor]


class MongoClassReportRepository(TenantScopedRepository):
    collection_name = "class_recap_reports"

    @staticmethod
    def _to_domain(doc: dict[str, Any]) -> ClassReport:
        return ClassReport(
            report_id=str(doc["report_id"]),
            academy_id=str(doc["academy_id"]),
            occurrence_id=str(doc["occurrence_id"]),
            class_starts_at=doc["class_starts_at"],
            author_id=str(doc["author_id"]),
            text=str(doc.get("text") or ""),
            submitted_at=doc["submitted_at"],
            outcome=doc["outcome"],
            ai_used=bool(doc.get("ai_used")),
            questions=tuple(doc.get("questions") or ()),
            pass_claims=tuple(PassClaim(**c) for c in doc.get("pass_claims") or ()),
            applied_revision=doc.get("applied_revision"),
            resolved_by=doc.get("resolved_by"),
            resolved_at=doc.get("resolved_at"),
            processing_until=doc.get("processing_until"),
        )

    @staticmethod
    def _body(report: ClassReport) -> dict[str, Any]:
        body = report.model_dump(exclude={"academy_id"})
        body["questions"] = list(report.questions)
        body["pass_claims"] = [c.model_dump() for c in report.pass_claims]
        return body

    async def get(self, report_id: str) -> ClassReport | None:
        doc = await self._find_one({"report_id": report_id})
        return self._to_domain(doc) if doc else None

    async def insert(self, report: ClassReport) -> bool:
        try:
            await self._insert_one(self._body(report))
        except DuplicateKeyError:
            return False
        return True

    async def finish(self, report: ClassReport) -> bool:
        # Only the reading's outcome; the owner's resolve stamp is left alone.
        body = self._body(report)
        fields = ("outcome", "ai_used", "questions", "pass_claims", "applied_revision")
        result = await self._update_one(
            {"report_id": report.report_id, "processing_until": {"$ne": None}},
            {"$set": {**{k: body[k] for k in fields}, "processing_until": None}},
        )
        return bool(result.matched_count)

    async def list_for_occurrence(self, occurrence_id: str) -> list[ClassReport]:
        cursor = self._find_many({"occurrence_id": occurrence_id}, sort=[("submitted_at", 1)])
        return [self._to_domain(doc) async for doc in cursor]

    async def list_open_handoffs(self, *, limit: int) -> list[ClassReport]:
        cursor = self._find_many(
            {
                "outcome": "sent_to_owner",
                "resolved_at": None,
                # A report still being read is not a handoff yet; an
                # interrupted one is once its lease runs out.
                "processing_until": {"$not": {"$gt": datetime.now(UTC)}},
            },
            sort=[("submitted_at", -1)],
            limit=limit,
        )
        return [self._to_domain(doc) async for doc in cursor]

    async def resolve(self, report_id: str, *, by: str, at: datetime) -> ClassReport | None:
        doc = await self._find_one_and_update(
            {"report_id": report_id, "resolved_at": None},
            {"$set": {"resolved_by": by, "resolved_at": at}},
        )
        return self._to_domain(doc) if doc else None


class StudentConfirmedAttendance(TenantScopedRepository):
    """``StudentAttendanceReader`` over the attendance collection."""

    collection_name = "attendance"

    async def confirmed_occurrence_ids(self, student_id: str, *, limit: int) -> list[str]:
        cursor = self._find_many(
            {"student_id": student_id, "status": {"$in": sorted(CONFIRMED_PRESENT)}},
            sort=[("marked_at", -1)],
            limit=limit,
        )
        return list(dict.fromkeys([str(doc["occurrence_id"]) async for doc in cursor]))
