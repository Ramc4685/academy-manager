"""Admin waiver BFF routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.v2.contexts.onboarding.application.use_cases.admin_waivers import (
    AdminWaiverReport,
    AdminWaiverStudentRow,
)
from backend.v2.interfaces.admin.deps import AdminUseCases, get_admin_use_cases
from backend.v2.interfaces.admin.views import (
    AdminWaiverDocumentView,
    AdminWaiverList,
    AdminWaiverSignatureDetailView,
    AdminWaiverStudentView,
    AdminWaiverSummaryView,
    AdminWaiverTemplateDetailView,
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


@router.get("/waivers/signatures/{signature_id}", response_model=AdminWaiverSignatureDetailView)
async def get_signed_waiver_detail(
    signature_id: str,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminWaiverSignatureDetailView:
    detail = await use_cases.list_admin_waivers.signature_detail(signature_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Signed waiver not found")
    return AdminWaiverSignatureDetailView(
        signature_id=detail.signature_id,
        student_name=detail.student_name,
        parent_name=detail.parent_name,
        parent_email=detail.parent_email,
        signed_at=detail.signed_at,
        signer_name=detail.signer_name,
        signer_email=detail.signer_email,
        waiver_title=detail.waiver_title,
        waiver_version=detail.waiver_version,
        template_reference=detail.waiver_template_id,
        content_hash=detail.content_hash,
        artifact_status=detail.artifact_status,
        share_status=detail.share_status,
        gap_note=detail.gap_note,
    )


@router.get("/waivers/{waiver_id}", response_model=AdminWaiverTemplateDetailView)
async def get_waiver_template_detail(
    waiver_id: str,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminWaiverTemplateDetailView:
    detail = await use_cases.list_admin_waivers.template_detail(waiver_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Waiver template not found")
    return AdminWaiverTemplateDetailView(
        waiver_id=detail.waiver_id,
        title=detail.title,
        version=detail.version,
        body=detail.body,
        content_hash=detail.content_hash,
        effective_at=detail.effective_from,
        artifact_status=detail.artifact_status,
        share_status=detail.share_status,
        gap_note=detail.gap_note,
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
        waiver_id=active.waiver_id,
        title=active.title or f"Waiver {active.version}",
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
        signature_id=row.signature_id,
        student_id=row.student_id,
        student_name=row.student_name,
        parent_id=row.parent_id,
        parent_name=row.parent_name,
        parent_email=row.parent_email,
        status=status,
        template_id=row.waiver_template_id,
        version=row.waiver_version or row.current_waiver_version,
        signed_at=row.signed_at,
        method="online" if row.signed_at else None,
        expires_at=None,
        artifact_status=row.artifact_status,
        share_status=row.share_status,
    )
