"""Admin coach pay-rate BFF routes.

Admin allocates how a coach is paid: a flat amount per session/hour or a
percentage of the session's expected revenue. Rates are effective-dated
and versioned — see ``coaching.application.use_cases.manage_coach_rates``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.v2.contexts.coaching.application.use_cases.manage_coach_rates import (
    CoachRate,
    ListCoachPayRates,
    RepairCoachRateWindow,
    RepairCoachRateWindowCommand,
    SetCoachPayRate,
    SetCoachPayRateCommand,
    diagnose_rate_timeline,
)
from backend.v2.interfaces.admin.deps import AdminUseCases, get_admin_use_cases
from backend.v2.interfaces.admin.views import (
    AdminCoachPayRateList,
    AdminCoachPayRateView,
    RepairCoachPayRateWindowRequest,
    SetCoachPayRateRequest,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_owner

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


def _diagnostics_view(coach_id: str, rates: list[CoachRate]) -> dict:
    diagnostics = diagnose_rate_timeline(coach_id, rates)
    return {
        "coach_id": diagnostics.coach_id,
        "has_blocking_issues": diagnostics.has_blocking_issues,
        "issues": [
            {
                "issue_type": issue.issue_type,
                "message": issue.message,
                "rate_ids": issue.rate_ids,
                "starts_at": issue.starts_at,
                "ends_at": issue.ends_at,
            }
            for issue in diagnostics.issues
        ],
    }


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


async def _sessions_with_missing_price_for_coach(
    use_cases: AdminUseCases,
    coach_id: str,
) -> list[str]:
    list_sessions = use_cases.list_admin_sessions
    if list_sessions is None:
        return []
    rows = await list_sessions(None, window="upcoming", coach_id=coach_id)  # type: ignore[operator]
    missing: list[str] = []
    for row in rows:
        amount = (
            row.get("amount_cents") if isinstance(row, dict) else getattr(row, "amount_cents", None)
        )
        if amount is not None:
            continue
        title = row.get("title") if isinstance(row, dict) else getattr(row, "title", None)
        session_id = (
            row.get("session_id") if isinstance(row, dict) else getattr(row, "session_id", None)
        )
        missing.append(str(title or session_id or "session"))
    return missing


def _repair_rate(use_cases: AdminUseCases) -> RepairCoachRateWindow:
    use_case = use_cases.repair_coach_pay_rate_window
    if use_case is None:
        raise HTTPException(status_code=503, detail="Coach pay-rate repair is not configured")
    return use_case  # type: ignore[return-value]


@router.get("/coaches/{coach_id}/pay-rates", response_model=AdminCoachPayRateList)
async def list_coach_pay_rates(
    coach_id: str,
    _claims: AuthClaims = Depends(require_owner()),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminCoachPayRateList:
    rates = await _list_rates(use_cases).execute(coach_id=coach_id)
    return AdminCoachPayRateList(
        rates=[_rate_view(rate) for rate in rates],
        diagnostics=_diagnostics_view(coach_id, rates),
    )


@router.post("/coaches/{coach_id}/pay-rates", response_model=AdminCoachPayRateView)
async def set_coach_pay_rate(
    coach_id: str,
    body: SetCoachPayRateRequest,
    _claims: AuthClaims = Depends(require_owner()),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminCoachPayRateView:
    if body.billing_unit == "percent_of_revenue":
        if body.percent is None:
            raise HTTPException(
                status_code=400, detail="percent is required for percent_of_revenue rates"
            )
        missing_sessions = await _sessions_with_missing_price_for_coach(use_cases, coach_id)
        if missing_sessions:
            preview = ", ".join(missing_sessions[:3])
            raise HTTPException(
                status_code=400,
                detail=(
                    "Percent-of-revenue coach pay requires session prices. "
                    f"Set a session fee or explicit $0 price for: {preview}"
                ),
            )
    try:
        rate = await _set_rate(use_cases).execute(
            SetCoachPayRateCommand(
                coach_id=coach_id,
                billing_unit=body.billing_unit,
                amount_minor=body.amount_cents,
                percent_bps=(None if body.percent is None else round(body.percent * 100)),
                currency=body.currency,
                effective_from=body.effective_from,
                actor_id=_claims.user_id,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _rate_view(rate)


@router.post("/coaches/{coach_id}/pay-rates/repair", response_model=AdminCoachPayRateView)
async def repair_coach_pay_rate_window(
    coach_id: str,
    body: RepairCoachPayRateWindowRequest,
    claims: AuthClaims = Depends(require_owner()),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminCoachPayRateView:
    try:
        rate = await _repair_rate(use_cases).execute(
            RepairCoachRateWindowCommand(
                coach_id=coach_id,
                billing_unit=body.billing_unit,
                amount_minor=body.amount_cents,
                percent_bps=(None if body.percent is None else round(body.percent * 100)),
                currency=body.currency,
                effective_from=body.effective_from,
                effective_until=body.effective_until,
                reason=body.reason,
                actor_id=claims.user_id,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _rate_view(rate)
