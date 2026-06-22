"""Admin payout-period routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from backend.v2.contexts.finance.application.ports import PayoutPeriodRepository
from backend.v2.contexts.finance.application.use_cases.approve_payout_period import (
    ApprovePayoutPeriod,
    MarkPayoutPaid,
    MarkPayoutPaidCommand,
)
from backend.v2.contexts.finance.application.use_cases.generate_payout_period import (
    GeneratePayoutPeriod,
)
from backend.v2.contexts.finance.application.use_cases.manage_payout_period import (
    ListPayoutAuditEntries,
    OverridePayoutLine,
    PayoutPeriodStateError,
    RecomputePayoutPeriod,
    ReopenPayoutPeriod,
)
from backend.v2.interfaces.admin.deps import AdminUseCases, get_admin_use_cases
from backend.v2.interfaces.admin.views import (
    AdminPayoutPayslipView,
    AdminPayoutPeriodLineView,
    AdminPayoutPeriodView,
    AdminPayoutWarningView,
    AdminUnpaidOccurrenceView,
    GeneratePayoutPeriodRequest,
    MarkPayoutPeriodPaidRequest,
    OverridePayoutLineRequest,
    PayoutAuditEntryView,
    PayoutAuditTrailView,
    ReopenPayoutPeriodRequest,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import DomainError, require_persona

router = APIRouter(tags=["admin.payout-periods"])


class PayoutPeriodNotFound(DomainError):
    code = "Finance.PayoutPeriodNotFound"
    status_code = 404


class PayoutPeriodInvalidTransition(DomainError):
    code = "Finance.PayoutPeriodInvalidTransition"
    status_code = 400


def _line_view(line: Any) -> AdminPayoutPeriodLineView:
    return AdminPayoutPeriodLineView(
        occurrence_id=line.occurrence_id,
        coach_id=line.coach_id,
        basis=line.basis,
        minutes=str(line.minutes),
        amount_cents=line.amount_minor,
        currency=line.currency,
        rate_id=line.rate_id,
        percent_bps=line.percent_bps,
        expected_revenue_cents=line.expected_revenue_minor,
        original_amount_cents=line.original_amount_minor,
        adjustment_reason=line.adjustment_reason,
    )


def _warning_view(warning: Any) -> AdminPayoutWarningView:
    return AdminPayoutWarningView(
        occurrence_id=warning.occurrence_id,
        reason=warning.reason,
        severity=warning.severity,
        message=warning.message,
        occurred_at=warning.occurred_at,
        session_id=warning.session_id,
        session_title=warning.session_title,
        coach_id=warning.coach_id,
        repair_action=warning.repair_action,
    )


def _period_view(period: Any) -> AdminPayoutPeriodView:
    payout_warnings = [_warning_view(warning) for warning in period.payout_warnings]
    structured_unpaid = [
        AdminUnpaidOccurrenceView(
            occurrence_id=row.occurrence_id,
            reason=row.reason,
            detail=row.detail,
            unresolved=row.unresolved,
        )
        for row in getattr(period, "unpaid_occurrences", [])
    ]
    if not structured_unpaid:
        structured_unpaid = [
            AdminUnpaidOccurrenceView(
                occurrence_id=occurrence_id,
                reason="unknown_unpaid_reason",
                detail="This payout period was generated before structured unpaid reasons.",
                unresolved=True,
            )
            for occurrence_id in period.unpaid_occurrence_ids
        ]
    unpaid_occurrence_ids = {row.occurrence_id for row in structured_unpaid}
    for warning in payout_warnings:
        if warning.occurrence_id in unpaid_occurrence_ids:
            continue
        structured_unpaid.append(
            AdminUnpaidOccurrenceView(
                occurrence_id=warning.occurrence_id,
                reason=warning.reason,
                detail=warning.message,
                unresolved=True,
                occurred_at=warning.occurred_at,
                session_id=warning.session_id,
                session_title=warning.session_title,
                severity=warning.severity,
                message=warning.message,
                coach_id=warning.coach_id,
                repair_action=warning.repair_action,
            )
        )
    return AdminPayoutPeriodView(
        period_id=period.period_id,
        coach_id=period.coach_id,
        period_start=period.period_start,
        period_end=period.period_end,
        status=period.status,
        currency=period.currency,
        total_amount_cents=period.total_minor,
        lines=[_line_view(line) for line in period.lines],
        unpaid_occurrence_ids=list(period.unpaid_occurrence_ids),
        unpaid_occurrences=structured_unpaid,
        payout_warnings=payout_warnings,
        generated_at=period.generated_at,
        approved_at=period.approved_at,
        paid_at=period.paid_at,
        paid_method=period.paid_method,
        paid_amount_cents=period.paid_amount_minor,
        paid_reference=period.paid_reference,
    )


async def _enriched_period_view(use_cases: AdminUseCases, period: Any) -> AdminPayoutPeriodView:
    """Period view with display data (dates, session titles) per line.

    Enrichment is best-effort: when the describer is not wired (tests,
    partial composition) the plain view is returned unchanged.
    """
    view = _period_view(period)
    describe = use_cases.describe_payout_occurrences
    if describe is None:
        return view
    occurrence_ids = [line.occurrence_id for line in view.lines] + view.unpaid_occurrence_ids
    descriptions: dict[str, dict[str, Any]] = await describe(occurrence_ids)  # type: ignore[operator]
    lines = [
        line.model_copy(
            update={
                "occurred_at": descriptions.get(line.occurrence_id, {}).get("occurred_at"),
                "session_title": descriptions.get(line.occurrence_id, {}).get("session_title"),
            }
        )
        for line in view.lines
    ]
    warnings_by_occurrence = {warning.occurrence_id: warning for warning in view.payout_warnings}
    warnings = [
        warning.model_copy(
            update={
                "occurred_at": warning.occurred_at
                or descriptions.get(warning.occurrence_id, {}).get("occurred_at"),
                "session_id": warning.session_id
                or descriptions.get(warning.occurrence_id, {}).get("session_id"),
                "session_title": warning.session_title
                or descriptions.get(warning.occurrence_id, {}).get("session_title"),
            }
        )
        for warning in view.payout_warnings
    ]
    warnings_by_occurrence = {warning.occurrence_id: warning for warning in warnings}
    unpaid = [
        occ.model_copy(
            update={
                "occurred_at": descriptions.get(occ.occurrence_id, {}).get("occurred_at"),
                "session_id": descriptions.get(occ.occurrence_id, {}).get("session_id"),
                "session_title": descriptions.get(occ.occurrence_id, {}).get("session_title"),
                "reason": (
                    warnings_by_occurrence[occ.occurrence_id].reason
                    if occ.occurrence_id in warnings_by_occurrence
                    else occ.reason
                ),
                "severity": (
                    warnings_by_occurrence[occ.occurrence_id].severity
                    if occ.occurrence_id in warnings_by_occurrence
                    else None
                ),
                "message": (
                    warnings_by_occurrence[occ.occurrence_id].message
                    if occ.occurrence_id in warnings_by_occurrence
                    else occ.detail
                ),
                "coach_id": (
                    warnings_by_occurrence[occ.occurrence_id].coach_id
                    if occ.occurrence_id in warnings_by_occurrence
                    else None
                ),
                "repair_action": (
                    warnings_by_occurrence[occ.occurrence_id].repair_action
                    if occ.occurrence_id in warnings_by_occurrence
                    else None
                ),
            }
        )
        for occ in view.unpaid_occurrences
    ]
    return view.model_copy(
        update={"lines": lines, "unpaid_occurrences": unpaid, "payout_warnings": warnings}
    )


def _payout_periods(use_cases: AdminUseCases) -> PayoutPeriodRepository:
    repo = use_cases.payout_periods
    if repo is None:
        raise HTTPException(status_code=503, detail="Payout periods are not configured")
    return repo  # type: ignore[return-value]


def _generate_payout_period(use_cases: AdminUseCases) -> GeneratePayoutPeriod:
    use_case = use_cases.generate_payout_period
    if use_case is None:
        raise HTTPException(status_code=503, detail="Payout generation is not configured")
    return use_case


def _approve_payout_period(use_cases: AdminUseCases) -> ApprovePayoutPeriod:
    use_case = use_cases.approve_payout_period
    if use_case is None:
        raise HTTPException(status_code=503, detail="Payout approval is not configured")
    return use_case


def _mark_payout_paid(use_cases: AdminUseCases) -> MarkPayoutPaid:
    use_case = use_cases.mark_payout_paid
    if use_case is None:
        raise HTTPException(status_code=503, detail="Payout payment is not configured")
    return use_case


def _recompute_payout_period(use_cases: AdminUseCases) -> RecomputePayoutPeriod:
    use_case = use_cases.recompute_payout_period
    if use_case is None:
        raise HTTPException(status_code=503, detail="Payout recompute is not configured")
    return use_case


def _reopen_payout_period(use_cases: AdminUseCases) -> ReopenPayoutPeriod:
    use_case = use_cases.reopen_payout_period
    if use_case is None:
        raise HTTPException(status_code=503, detail="Payout reopen is not configured")
    return use_case


def _override_payout_line(use_cases: AdminUseCases) -> OverridePayoutLine:
    use_case = use_cases.override_payout_line
    if use_case is None:
        raise HTTPException(status_code=503, detail="Payout line override is not configured")
    return use_case


def _list_payout_audit_entries(use_cases: AdminUseCases) -> ListPayoutAuditEntries:
    use_case = use_cases.list_payout_audit_entries
    if use_case is None:
        raise HTTPException(status_code=503, detail="Payout audit trail is not configured")
    return use_case


async def _load_period(use_cases: AdminUseCases, period_id: str) -> Any:
    period = await _payout_periods(use_cases).find_by_id(period_id)
    if period is None:
        raise PayoutPeriodNotFound(f"Payout period {period_id!r} not found")
    return period


@router.post("/payout-periods/generate", response_model=AdminPayoutPeriodView)
async def generate_payout_period(
    body: GeneratePayoutPeriodRequest,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminPayoutPeriodView:
    period = await _generate_payout_period(use_cases).execute(
        coach_id=body.coach_id,
        academy_id=claims.academy_id,
        period_start=body.period_start,
        period_end=body.period_end,
    )
    return await _enriched_period_view(use_cases, period)


@router.get("/payout-periods/{period_id}", response_model=AdminPayoutPeriodView)
async def get_payout_period(
    period_id: str,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminPayoutPeriodView:
    return await _enriched_period_view(use_cases, await _load_period(use_cases, period_id))


@router.post("/payout-periods/{period_id}/approve", response_model=AdminPayoutPeriodView)
async def approve_payout_period(
    period_id: str,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminPayoutPeriodView:
    try:
        period = await _approve_payout_period(use_cases).execute(period_id=period_id)
    except LookupError as exc:
        raise PayoutPeriodNotFound(f"Payout period {period_id!r} not found") from exc
    except ValueError as exc:
        raise PayoutPeriodInvalidTransition(str(exc)) from exc
    return await _enriched_period_view(use_cases, period)


@router.post("/payout-periods/{period_id}/mark-paid", response_model=AdminPayoutPeriodView)
async def mark_payout_period_paid(
    period_id: str,
    body: MarkPayoutPeriodPaidRequest,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminPayoutPeriodView:
    try:
        period = await _mark_payout_paid(use_cases).execute(
            MarkPayoutPaidCommand(
                period_id=period_id,
                method=body.method,
                paid_at=body.paid_at,
                amount_minor=body.amount_cents,
                reference=body.reference,
            )
        )
    except LookupError as exc:
        raise PayoutPeriodNotFound(f"Payout period {period_id!r} not found") from exc
    except ValueError as exc:
        raise PayoutPeriodInvalidTransition(str(exc)) from exc
    return await _enriched_period_view(use_cases, period)


@router.post("/payout-periods/{period_id}/recompute", response_model=AdminPayoutPeriodView)
async def recompute_payout_period(
    period_id: str,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminPayoutPeriodView:
    try:
        period = await _recompute_payout_period(use_cases).execute(
            period_id=period_id, actor_id=claims.user_id
        )
    except LookupError as exc:
        raise PayoutPeriodNotFound(f"Payout period {period_id!r} not found") from exc
    except PayoutPeriodStateError as exc:
        raise PayoutPeriodInvalidTransition(str(exc)) from exc
    return await _enriched_period_view(use_cases, period)


@router.post("/payout-periods/{period_id}/reopen", response_model=AdminPayoutPeriodView)
async def reopen_payout_period(
    period_id: str,
    body: ReopenPayoutPeriodRequest,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminPayoutPeriodView:
    try:
        period = await _reopen_payout_period(use_cases).execute(
            period_id=period_id, actor_id=claims.user_id, reason=body.reason
        )
    except LookupError as exc:
        raise PayoutPeriodNotFound(f"Payout period {period_id!r} not found") from exc
    except ValueError as exc:
        raise PayoutPeriodInvalidTransition(str(exc)) from exc
    return await _enriched_period_view(use_cases, period)


@router.patch(
    "/payout-periods/{period_id}/lines/{occurrence_id}",
    response_model=AdminPayoutPeriodView,
)
async def override_payout_period_line(
    period_id: str,
    occurrence_id: str,
    body: OverridePayoutLineRequest,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminPayoutPeriodView:
    try:
        period = await _override_payout_line(use_cases).execute(
            period_id=period_id,
            occurrence_id=occurrence_id,
            amount_minor=body.amount_cents,
            reason=body.reason,
            actor_id=claims.user_id,
        )
    except LookupError as exc:
        raise PayoutPeriodNotFound(str(exc)) from exc
    except ValueError as exc:
        raise PayoutPeriodInvalidTransition(str(exc)) from exc
    return await _enriched_period_view(use_cases, period)


@router.get("/payout-periods/{period_id}/audit", response_model=PayoutAuditTrailView)
async def get_payout_period_audit(
    period_id: str,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> PayoutAuditTrailView:
    entries = await _list_payout_audit_entries(use_cases).execute(period_id=period_id)
    return PayoutAuditTrailView(
        entries=[
            PayoutAuditEntryView(
                audit_id=e.audit_id,
                period_id=e.period_id,
                occurrence_id=e.occurrence_id,
                action=e.action,
                actor_id=e.actor_id,
                at=e.at,
                reason=e.reason,
                before=e.before,
                after=e.after,
            )
            for e in entries
        ]
    )


@router.get("/payout-periods/{period_id}/export")
async def export_payout_period_xlsx(
    period_id: str,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
):
    """Download the payout period as an Excel workbook.

    One row per occurrence (paid lines first, then unpaid occurrences),
    with a summary block on top. Amounts are in major units so the
    sheet is readable without conversion.
    """
    import io

    from fastapi.responses import StreamingResponse
    from openpyxl import Workbook

    period = await _load_period(use_cases, period_id)
    view = await _enriched_period_view(use_cases, period)

    wb = Workbook()
    ws = wb.active
    ws.title = "Payout"

    ws.append(["Coach payout period"])
    ws.append(["Coach", view.coach_id])
    ws.append(["Period", f"{view.period_start:%Y-%m-%d} to {view.period_end:%Y-%m-%d}"])
    ws.append(["Status", view.status])
    ws.append(["Currency", view.currency])
    ws.append(["Total", view.total_amount_cents / 100])
    ws.append([])
    ws.append(
        [
            "Date",
            "Session",
            "Role",
            "Status",
            "Percent",
            "Expected revenue",
            "Pay",
            "Adjustment",
            "Warning reason",
            "Repair action",
        ]
    )
    for line in view.lines:
        ws.append(
            [
                f"{line.occurred_at:%Y-%m-%d}" if line.occurred_at else "",
                line.session_title or line.occurrence_id,
                "Replacement" if line.basis == "substitute" else "Scheduled",
                "Paid",
                (line.percent_bps / 100) if line.percent_bps is not None else None,
                (line.expected_revenue_cents / 100)
                if line.expected_revenue_cents is not None
                else None,
                line.amount_cents / 100,
                (
                    f"was {line.original_amount_cents / 100:.2f} — {line.adjustment_reason}"
                    if line.original_amount_cents is not None
                    else ""
                ),
                "",
                "",
            ]
        )
    for unpaid in view.unpaid_occurrences:
        ws.append(
            [
                f"{unpaid.occurred_at:%Y-%m-%d}" if unpaid.occurred_at else "",
                unpaid.session_title or unpaid.occurrence_id,
                "",
                "Not paid",
                None,
                None,
                0,
                "",
                unpaid.reason or "",
                unpaid.repair_action or "",
            ]
        )

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    filename = f"payout-{view.coach_id}-{view.period_start:%Y%m%d}-{view.period_end:%Y%m%d}.xlsx"
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/payout-periods/{period_id}/payslip", response_model=AdminPayoutPayslipView)
async def get_printable_payout_payslip(
    period_id: str,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminPayoutPayslipView:
    period = await _load_period(use_cases, period_id)
    period_view = _period_view(period)
    return AdminPayoutPayslipView(period=period_view, lines=period_view.lines)
