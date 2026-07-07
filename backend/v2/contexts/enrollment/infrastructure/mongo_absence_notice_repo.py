"""Mongo repository for parent-submitted absence notices."""

from __future__ import annotations

from pymongo.errors import DuplicateKeyError

from backend.v2.contexts.enrollment.application.use_cases.absence_notices import AbsenceNotice
from backend.v2.contexts.enrollment.domain.self_service import DuplicateAbsenceNotice
from backend.v2.shared.tenancy import TenantScopedRepository, current_academy_id


class MongoAbsenceNoticeRepository(TenantScopedRepository):
    collection_name = "absence_notices"

    @staticmethod
    def _to_domain(doc: dict[str, object]) -> AbsenceNotice:
        return AbsenceNotice(
            notice_id=str(doc["notice_id"]),
            academy_id=str(doc["academy_id"]),
            student_id=str(doc["student_id"]),
            occurrence_id=str(doc["occurrence_id"]),
            session_id=str(doc["session_id"]),
            submitted_by=str(doc["submitted_by"]),
            submitted_at=doc["submitted_at"],  # type: ignore[arg-type]
            notice_window_met=bool(doc["notice_window_met"]),
        )

    @staticmethod
    def _to_doc(notice: AbsenceNotice) -> dict[str, object]:
        return {
            "notice_id": notice.notice_id,
            "academy_id": current_academy_id(),
            "student_id": notice.student_id,
            "occurrence_id": notice.occurrence_id,
            "session_id": notice.session_id,
            "submitted_by": notice.submitted_by,
            "submitted_at": notice.submitted_at,
            "notice_window_met": notice.notice_window_met,
        }

    async def add(self, notice: AbsenceNotice) -> None:
        try:
            await self._insert_one(self._to_doc(notice))
        except DuplicateKeyError as exc:
            # The use case's check-then-insert can race a concurrent
            # double-submit; the unique (academy_id, occurrence_id,
            # student_id) index from migration 0145 wins that race here —
            # translate to the same 409 the pre-check raises.
            raise DuplicateAbsenceNotice(
                "an absence notice already exists for this occurrence and student",
                occurrence_id=notice.occurrence_id,
                student_id=notice.student_id,
            ) from exc

    async def get_for_occurrence_and_student(
        self, occurrence_id: str, student_id: str
    ) -> AbsenceNotice | None:
        doc = await self._find_one({"occurrence_id": occurrence_id, "student_id": student_id})
        return self._to_domain(doc) if doc else None

    async def list_for_parent(self, parent_id: str) -> list[AbsenceNotice]:
        cursor = self._find_many({"submitted_by": parent_id}, sort=[("submitted_at", -1)])
        return [self._to_domain(doc) async for doc in cursor]

    async def list_for_occurrence(self, occurrence_id: str) -> list[AbsenceNotice]:
        cursor = self._find_many({"occurrence_id": occurrence_id}, sort=[("submitted_at", -1)])
        return [self._to_domain(doc) async for doc in cursor]

    async def list_for_student(self, student_id: str) -> list[AbsenceNotice]:
        cursor = self._find_many({"student_id": student_id}, sort=[("submitted_at", -1)])
        return [self._to_domain(doc) async for doc in cursor]

    async def list_all(self) -> list[AbsenceNotice]:
        cursor = self._find_many({}, sort=[("submitted_at", -1)])
        return [self._to_domain(doc) async for doc in cursor]
