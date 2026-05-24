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
from backend.v2.interfaces.admin.deps import AdminUseCases, get_admin_use_cases
from backend.v2.interfaces.admin.views import (
    AdminPayoutPayslipView,
    AdminPayoutPeriodLineView,
    AdminPayoutPeriodView,
    GeneratePayoutPeriodRequest,
    MarkPayoutPeriodPaidRequest,
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
    )


def _period_view(period: Any) -> AdminPayoutPeriodView:
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
        generated_at=period.generated_at,
        approved_at=period.approved_at,
        paid_at=period.paid_at,
        paid_method=period.paid_method,
        paid_amount_cents=period.paid_amount_minor,
        paid_reference=period.paid_reference,
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
    return _period_view(period)


@router.get("/payout-periods/{period_id}", response_model=AdminPayoutPeriodView)
async def get_payout_period(
    period_id: str,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminPayoutPeriodView:
    return _period_view(await _load_period(use_cases, period_id))


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
    return _period_view(period)


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
    return _period_view(period)


@router.get("/payout-periods/{period_id}/payslip", response_model=AdminPayoutPayslipView)
async def get_printable_payout_payslip(
    period_id: str,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminPayoutPayslipView:
    period = await _load_period(use_cases, period_id)
    period_view = _period_view(period)
    return AdminPayoutPayslipView(period=period_view, lines=period_view.lines)
