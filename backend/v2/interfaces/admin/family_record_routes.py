"""Admin BFF: reads for the People CRM family record page (Lane A4).

* ``GET /admin/students/{student_id}/coach-notes``: the child drawer's coach
  notes, read-only, with the coach's name. Only notes a coach shared (#665):
  the same set the family already sees. 404 when the student is not a student
  of the caller's academy.

``require_persona("admin")``. Services at ``app.state.admin_family_record``
(``composition/family_record.py``).
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from backend.v2.contexts.coaching.application.use_cases.shared_coach_notes import (
    SharedCoachNote,
    StudentNotInAcademy,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona
from backend.v2.shared.tenancy import TenantContextUnset, current_academy_id


class SharedCoachNotesUseCase(Protocol):
    async def execute(
        self, *, academy_id: str, student_id: str, limit: int = ...
    ) -> list[SharedCoachNote]: ...


class AdminFamilyRecordServices(Protocol):
    shared_coach_notes: SharedCoachNotesUseCase


def get_admin_family_record(request: Request) -> AdminFamilyRecordServices:
    services: AdminFamilyRecordServices = request.app.state.admin_family_record
    return services


class AdminCoachNoteView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note_id: str
    session_id: str | None = None
    session_title: str | None = None
    coach_name: str | None = None
    body: str
    created_at: datetime


class AdminCoachNoteList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    student_id: str
    notes: list[AdminCoachNoteView]


def _academy_id(claims: AuthClaims) -> str:
    try:
        return current_academy_id()
    except TenantContextUnset:
        return claims.academy_id


router = APIRouter(tags=["admin.families"])


@router.get("/students/{student_id}/coach-notes", response_model=AdminCoachNoteList)
async def list_student_coach_notes(
    student_id: str,
    claims: AuthClaims = Depends(require_persona("admin")),
    services: AdminFamilyRecordServices = Depends(get_admin_family_record),
) -> AdminCoachNoteList:
    """Coach notes shared with the family, newest first (read-only)."""
    try:
        notes = await services.shared_coach_notes.execute(
            academy_id=_academy_id(claims), student_id=student_id
        )
    except StudentNotInAcademy as exc:
        raise HTTPException(status_code=404, detail="student not found") from exc
    return AdminCoachNoteList(
        student_id=student_id,
        notes=[
            AdminCoachNoteView(
                note_id=n.note_id,
                session_id=n.session_id,
                session_title=n.session_title,
                coach_name=n.coach_name,
                body=n.body,
                created_at=n.created_at,
            )
            for n in notes
        ],
    )
