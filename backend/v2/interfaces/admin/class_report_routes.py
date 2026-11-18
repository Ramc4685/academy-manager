"""Owner handoff list: coach after-class reports waiting for the owner.

``GET /api/v2/admin/class-reports/handoffs`` (owner only, 404 otherwise).
A report lands here when the coach sent it without AI or AI was unavailable;
the owner opens the class from the dashboard card, enters the recap there,
and marks the report handled (``POST /coach/occurrences/{id}/class-reports/
{report_id}/resolve``).
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_owner

router = APIRouter(tags=["admin.class-reports"])


class ClassReportHandoffView(BaseModel):
    report_id: str
    occurrence_id: str
    class_starts_at: datetime
    author_id: str
    text: str
    submitted_at: datetime


class ClassReportHandoffList(BaseModel):
    reports: list[ClassReportHandoffView]


@router.get("/class-reports/handoffs", response_model=ClassReportHandoffList)
async def list_class_report_handoffs(
    request: Request,
    _claims: AuthClaims = Depends(require_owner()),
) -> ClassReportHandoffList:
    rows = await request.app.state.class_recap.list_handoffs.execute()
    return ClassReportHandoffList(
        reports=[
            ClassReportHandoffView(
                report_id=r.report_id,
                occurrence_id=r.occurrence_id,
                class_starts_at=r.class_starts_at,
                author_id=r.author_id,
                text=r.text,
                submitted_at=r.submitted_at,
            )
            for r in rows
        ]
    )
