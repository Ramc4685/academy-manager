"""Mongo repositories for coach-authored lesson plans and progress notes."""

from __future__ import annotations

from typing import cast

from backend.v2.contexts.coaching.application.use_cases.session_notes import (
    LessonPlan,
    ProgressNote,
)
from backend.v2.contexts.coaching.domain.models import NoteVisibility
from backend.v2.shared.tenancy import TenantScopedRepository


class MongoLessonPlanRepository(TenantScopedRepository):
    collection_name = "lesson_plans"

    @staticmethod
    def _to_domain(doc: dict[str, object]) -> LessonPlan:
        return LessonPlan(
            lesson_plan_id=str(doc["lesson_plan_id"]),
            session_id=str(doc["session_id"]),
            coach_id=str(doc["coach_id"]),
            title=str(doc.get("title") or ""),
            body=str(doc.get("body") or ""),
            created_at=doc["created_at"],
        )

    async def add_lesson_plan(self, plan: LessonPlan) -> None:
        await self._insert_one(plan.model_dump(mode="python"))

    async def list_lesson_plans(self, session_id: str, coach_id: str) -> list[LessonPlan]:
        cursor = self._find_many(
            {"session_id": session_id, "coach_id": coach_id},
            sort=[("created_at", -1)],
            limit=50,
        )
        return [self._to_domain(doc) async for doc in cursor]


class MongoProgressNoteRepository(TenantScopedRepository):
    collection_name = "progress_notes"

    @staticmethod
    def _to_domain(doc: dict[str, object]) -> ProgressNote:
        return ProgressNote(
            note_id=str(doc.get("note_id") or doc["_id"]),
            session_id=str(doc["session_id"]),
            student_id=str(doc["student_id"]),
            coach_id=str(doc["coach_id"]),
            body=str(doc.get("body") or doc.get("note") or ""),
            created_at=doc["created_at"],
            # Legacy docs (pre-0167) carry no flag and read as private.
            visibility=cast(NoteVisibility, doc.get("visibility") or "private"),
        )

    async def add_progress_note(self, note: ProgressNote) -> None:
        await self._insert_one(note.model_dump(mode="python"))

    async def list_progress_notes(
        self, session_id: str, coach_id: str | None
    ) -> list[ProgressNote]:
        filter_: dict[str, object] = {"session_id": session_id}
        if coach_id is not None:
            filter_["coach_id"] = coach_id
        cursor = self._find_many(filter_, sort=[("created_at", -1)], limit=100)
        return [self._to_domain(doc) async for doc in cursor]

    async def get_progress_note(self, session_id: str, note_id: str) -> ProgressNote | None:
        doc = await self._find_one({"session_id": session_id, "note_id": note_id})
        return self._to_domain(doc) if doc else None

    async def set_progress_note_visibility(
        self, session_id: str, note_id: str, visibility: NoteVisibility
    ) -> ProgressNote | None:
        doc = await self._find_one_and_update(
            {"session_id": session_id, "note_id": note_id},
            {"$set": {"visibility": visibility}},
        )
        return self._to_domain(doc) if doc else None


class MongoCoachingNotesRepository:
    def __init__(self, db) -> None:
        self._lesson_plans = MongoLessonPlanRepository(db)
        self._progress_notes = MongoProgressNoteRepository(db)

    async def add_lesson_plan(self, plan: LessonPlan) -> None:
        await self._lesson_plans.add_lesson_plan(plan)

    async def list_lesson_plans(self, session_id: str, coach_id: str) -> list[LessonPlan]:
        return await self._lesson_plans.list_lesson_plans(session_id, coach_id)

    async def add_progress_note(self, note: ProgressNote) -> None:
        await self._progress_notes.add_progress_note(note)

    async def list_progress_notes(
        self, session_id: str, coach_id: str | None
    ) -> list[ProgressNote]:
        return await self._progress_notes.list_progress_notes(session_id, coach_id)

    async def get_progress_note(self, session_id: str, note_id: str) -> ProgressNote | None:
        return await self._progress_notes.get_progress_note(session_id, note_id)

    async def set_progress_note_visibility(
        self, session_id: str, note_id: str, visibility: NoteVisibility
    ) -> ProgressNote | None:
        return await self._progress_notes.set_progress_note_visibility(
            session_id, note_id, visibility
        )
