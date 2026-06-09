"""Admin coach pay-rate BFF routes.

Admin allocates how a coach is paid: a flat amount per session/hour or a
percentage of the session's expected revenue. Rates are effective-dated
and versioned — see ``coaching.application.use_cases.manage_coach_rates``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.v2.contexts.coaching.application.use_cases.manage_coach_rates import (
    ListCoachPayRates,
    SetCoachPayRate,
    SetCoachPayRateCommand,
)
from backend.v2.contexts.coaching.domain.payout import CoachRate
from backend.v2.interfaces.admin.deps import AdminUseCases, get_admin_use_cases
from backend.v2.interfaces.admin.views import (
    AdminCoachPayRateList,
    AdminCoachPayRateView,
    SetCoachPayRateRequest,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["admin.coach-pay-rates"])


def _rate_view(rate: CoachRate) -> AdminCoachPayRateView:
    return AdminCoachPayRateView(
        rate_id=rate.rate_id,
        coach_id=rate.coach_id,
        billing_unit=rate.billing_unit,
        amount_cents=rate.amount_minor,
        percent=(None if rate.percent_bps is None else rate.percent_bps / 100),
        currency=rate.currency,
        effective_from=rate.effective_from,
        effective_until=rate.effective_until,
        status=rate.status,
    )


def _set_rate(use_cases: AdminUseCases) -> SetCoachPayRate:
    use_case = use_cases.set_coach_pay_rate
    if use_case is None:
        raise HTTPException(status_code=503, detail="Coach pay rates are not configured")
    return use_case  # type: ignore[return-value]


def _list_rates(use_cases: AdminUseCases) -> ListCoachPayRates:
    use_case = use_cases.list_coach_pay_rates
    if use_case is None:
        raise HTTPException(status_code=503, detail="Coach pay rates are not configured")
    return use_case  # type: ignore[return-value]


@router.get("/coaches/{coach_id}/pay-rates", response_model=AdminCoachPayRateList)
async def list_coach_pay_rates(
    coach_id: str,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminCoachPayRateList:
    rates = await _list_rates(use_cases).execute(coach_id=coach_id)
    return AdminCoachPayRateList(rates=[_rate_view(rate) for rate in rates])


@router.post("/coaches/{coach_id}/pay-rates", response_model=AdminCoachPayRateView)
async def set_coach_pay_rate(
    coach_id: str,
    body: SetCoachPayRateRequest,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminCoachPayRateView:
    try:
        rate = await _set_rate(use_cases).execute(
            SetCoachPayRateCommand(
                coach_id=coach_id,
                billing_unit=body.billing_unit,
                amount_minor=body.amount_cents,
                percent_bps=(None if body.percent is None else round(body.percent * 100)),
                currency=body.currency,
                effective_from=body.effective_from,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _rate_view(rate)
