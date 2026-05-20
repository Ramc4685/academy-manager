"""Admin waiver BFF routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.v2.contexts.onboarding.application.use_cases.admin_waivers import (
    AdminWaiverReport,
    AdminWaiverStudentRow,
)
from backend.v2.interfaces.admin.deps import AdminUseCases, get_admin_use_cases
from backend.v2.interfaces.admin.views import (
    AdminWaiverDocumentView,
    AdminWaiverList,
    AdminWaiverStudentView,
    AdminWaiverSummaryView,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["admin-waivers"])


@router.get("/waivers", response_model=AdminWaiverList)
async def list_admin_waivers(
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminWaiverList:
    report = await use_cases.list_admin_waivers.execute()
    active = _current_waiver_view(report)
    rows = [_student_waiver_view(row) for row in report.rows]
    return AdminWaiverList(
        summary=_summary_view(report),
        current_waiver=active,
        waivers=rows,
    )


def _summary_view(report: AdminWaiverReport) -> AdminWaiverSummaryView:
    total = report.summary.total_students
    current = report.summary.current_count
    return AdminWaiverSummaryView(
        signed_current=current,
        pending_signature=report.summary.pending_count,
        expiring_30d=0,
        outdated_version=report.summary.outdated_count,
        active_students=total,
        adoption_rate=(current / total if total else None),
    )


def _current_waiver_view(
    report: AdminWaiverReport,
) -> AdminWaiverDocumentView | None:
    active = report.active_waiver
    if active is None:
        return None
    total = report.summary.total_students
    current = report.summary.current_count
    return AdminWaiverDocumentView(
        title=f"Waiver {active.version}",
        version=active.version,
        description=None,
        effective_at=active.effective_from,
        last_edited_at=None,
        signed_count=current,
        total_count=total,
        adoption_rate=(current / total if total else None),
    )


def _student_waiver_view(row: AdminWaiverStudentRow) -> AdminWaiverStudentView:
    status = "signed" if row.status in {"current", "signed"} else row.status
    return AdminWaiverStudentView(
        waiver_id=f"{row.student_id}:{row.waiver_version or 'pending'}",
        student_id=row.student_id,
        student_name=row.student_name,
        parent_id=row.parent_id,
        parent_name=row.parent_name,
        parent_email=row.parent_email,
        status=status,
        version=row.waiver_version or row.current_waiver_version,
        signed_at=row.signed_at,
        method="online" if row.signed_at else None,
        expires_at=None,
    )
