"""Admin waiver BFF routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from backend.v2.contexts.onboarding.application.use_cases.admin_waiver_templates import (
    AdminWaiverTemplateRecord,
    AssignWaiverTemplateToRegistrationCommand,
    CreateDraftWaiverTemplateCommand,
    ManageAdminWaiverTemplates,
    PublishWaiverTemplateCommand,
    WaiverTemplateNotDraft,
    WaiverTemplateNotFound,
)
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
    AdminWaiverTemplateCreateRequest,
    AdminWaiverTemplateDetailView,
    AdminWaiverTemplateManagementList,
    AdminWaiverTemplateManagementView,
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


@router.get("/waivers/templates", response_model=AdminWaiverTemplateManagementList)
async def list_admin_waiver_templates(
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminWaiverTemplateManagementList:
    manager = _template_manager(use_cases)
    templates = await manager.list_templates()
    return AdminWaiverTemplateManagementList(
        templates=[_template_management_view(template) for template in templates]
    )


@router.post(
    "/waivers/templates",
    response_model=AdminWaiverTemplateManagementView,
    status_code=status.HTTP_201_CREATED,
)
async def create_admin_waiver_template(
    request: AdminWaiverTemplateCreateRequest,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminWaiverTemplateManagementView:
    manager = _template_manager(use_cases)
    try:
        template = await manager.create_draft(
            CreateDraftWaiverTemplateCommand(
                title=request.title,
                body=request.body,
                content=request.content,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _template_management_view(template)


@router.post(
    "/waivers/templates/{waiver_template_id}/publish",
    response_model=AdminWaiverTemplateManagementView,
)
async def publish_admin_waiver_template(
    waiver_template_id: str,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminWaiverTemplateManagementView:
    manager = _template_manager(use_cases)
    try:
        template = await manager.publish(
            PublishWaiverTemplateCommand(waiver_template_id=waiver_template_id)
        )
    except WaiverTemplateNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except WaiverTemplateNotDraft as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _template_management_view(template)


@router.post(
    "/waivers/templates/{waiver_template_id}/assign-registration",
    response_model=AdminWaiverTemplateManagementView,
)
async def assign_admin_waiver_template_to_registration(
    waiver_template_id: str,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminWaiverTemplateManagementView:
    manager = _template_manager(use_cases)
    try:
        template = await manager.assign_to_registration(
            AssignWaiverTemplateToRegistrationCommand(waiver_template_id=waiver_template_id)
        )
    except WaiverTemplateNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _template_management_view(template)


def _template_manager(use_cases: AdminUseCases) -> ManageAdminWaiverTemplates:
    if use_cases.manage_admin_waiver_templates is None:
        raise HTTPException(status_code=503, detail="Waiver template management unavailable")
    return use_cases.manage_admin_waiver_templates


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
        artifact_reference=detail.artifact_id,
        share_link_reference=detail.share_link_id,
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
        status=detail.status,
        body=detail.body,
        content_hash=detail.content_hash,
        effective_at=detail.effective_from,
        assigned_to_registration=detail.assigned_to_registration,
        assigned_at=detail.assigned_at,
        artifact_status=detail.artifact_status,
        share_status=detail.share_status,
        gap_note=detail.gap_note,
    )


def _template_management_view(
    template: AdminWaiverTemplateRecord,
) -> AdminWaiverTemplateManagementView:
    return AdminWaiverTemplateManagementView(
        waiver_template_id=template.waiver_template_id,
        title=template.title,
        body=template.body,
        status=template.status,
        version=template.version,
        content_hash=template.content_hash,
        effective_at=template.effective_from,
        published_at=template.published_at,
        assigned_to_registration=template.assigned_to_registration,
        assigned_at=template.assigned_at,
        updated_at=template.updated_at,
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
