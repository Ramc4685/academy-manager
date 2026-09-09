"""Stop-all-classes + the leaving report (issue #698).

``POST .../stop-all-classes`` mirrors the single-enrollment withdraw route
(``sessions_routes.withdraw_enrollment``): same request shape, same
``ensure_owner_for_withdrawal_credit`` gate on the ``credit`` outcome, same
``_start_of_day_utc`` convention for the effective date. The only new thing
is that the caller may omit ``outcome`` and let the academy's configured
``drop_default_outcome`` decide it.

``GET /reports/leaving`` is owner-only, per ``OWNER_ONLY_ROUTE_PATHS`` — it is
a financial report, same tier as every other report under ``/reports/*``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from backend.v2.contexts.enrollment.application.use_cases.leaving_report import (
    LeavingReportRequest,
)
from backend.v2.contexts.enrollment.application.use_cases.stop_all_classes import (
    StopAllClassesCommand,
)
from backend.v2.interfaces.admin.deps import (
    AdminUseCases,
    get_admin_use_cases,
    require_use_case,
)
from backend.v2.interfaces.admin.owner_gate import ensure_owner_for_withdrawal_credit
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_owner, require_persona

router = APIRouter(tags=["admin.departures"])

#: The value the Stop-all-classes dialog pre-selects when the admin does not
#: choose an outcome — see the design contract §1.2's mapping table.
#: ``no_credit_end_of_period`` maps to the same money-side outcome
#: (``"adjustment"``) as ``no_credit_mid_month`` today: the deferred,
#: attendance-continues-to-period-end mechanism that #675 built for the
#: PARENT self-cancel flow is not reused here, because it is written
#: specifically for that flow's own "cancelled" status and audit fields
#: (see the design contract's ground-truth notes on ``mark_pending_
#: cancellation_by_parent``). Stop-all-classes always takes the admin's
#: explicit ``effective_date`` and acts immediately on it, same as a
#: single-enrollment Drop does today. Flagged as an open question in the PR
#: body — see this branch's report.
_DROP_DEFAULT_TO_WITHDRAWAL_OUTCOME: dict[str, Literal["credit", "refund", "adjustment"]] = {
    "no_credit_mid_month": "adjustment",
    "credit_mid_month": "credit",
    "no_credit_end_of_period": "adjustment",
}


def _start_of_day_utc(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=UTC)


class StopAllClassesRequest(BaseModel):
    effective_date: date
    #: Omitted → resolved from the academy's ``drop_default_outcome``.
    outcome: Literal["credit", "refund", "adjustment"] | None = None
    reason: str = Field(min_length=1, max_length=500)


class EnrollmentStopResultView(BaseModel):
    enrollment_id: str
    session_id: str
    outcome: Literal["dropped", "failed"]
    error: str | None = None


class StopAllClassesResponse(BaseModel):
    student_id: str
    dropped_count: int
    failed_count: int
    results: list[EnrollmentStopResultView]


@router.post("/students/{student_id}/stop-all-classes", response_model=StopAllClassesResponse)
async def stop_all_classes(
    student_id: str,
    body: StopAllClassesRequest,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> StopAllClassesResponse:
    policy = await require_use_case(use_cases.departure_policy, "departure_policy").execute()
    outcome = body.outcome or _DROP_DEFAULT_TO_WITHDRAWAL_OUTCOME[policy.drop_default_outcome]
    # Same money-governance gate as the single-enrollment Drop route,
    # including for the academy's own configured default — a plain admin at
    # an academy whose default is ``credit_mid_month`` still gets 404 here.
    ensure_owner_for_withdrawal_credit(claims, outcome)
    result = await require_use_case(use_cases.stop_all_classes, "stop_all_classes").execute(
        StopAllClassesCommand(
            student_id=student_id,
            effective_at=_start_of_day_utc(body.effective_date),
            outcome=outcome,
            reason=body.reason,
            actor_id=claims.user_id,
        )
    )
    return StopAllClassesResponse(
        student_id=result.student_id,
        dropped_count=result.dropped_count,
        failed_count=result.failed_count,
        results=[
            EnrollmentStopResultView(
                enrollment_id=r.enrollment_id,
                session_id=r.session_id,
                outcome=r.outcome,
                error=r.error,
            )
            for r in result.results
        ],
    )


class LeavingReportRowView(BaseModel):
    event_id: str
    student_id: str
    student_name: str | None
    enrollment_id: str | None
    session_id: str | None
    session_title: str | None
    occurred_at: datetime
    effective_at: datetime
    event_type: str
    reason: str | None
    actor_id: str | None
    is_system_action: bool
    billing_result: str | None
    credit_id: str | None
    monthly_revenue_effect_cents: int | None


class LeavingReportResponse(BaseModel):
    rows: list[LeavingReportRowView]
    #: Sum of every row's (non-null) monthly revenue effect — negative.
    total_monthly_revenue_effect_cents: int


@router.get("/reports/leaving", response_model=LeavingReportResponse)
async def get_leaving_report(
    start: date = Query(...),
    end: date = Query(...),
    _claims: AuthClaims = Depends(require_owner()),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> LeavingReportResponse:
    rows = await require_use_case(use_cases.leaving_report, "leaving_report").execute(
        LeavingReportRequest(start=_start_of_day_utc(start), end=_start_of_day_utc(end))
    )
    total = sum(r.monthly_revenue_effect_cents or 0 for r in rows)
    return LeavingReportResponse(
        rows=[
            LeavingReportRowView(
                event_id=r.event_id,
                student_id=r.student_id,
                student_name=r.student_name,
                enrollment_id=r.enrollment_id,
                session_id=r.session_id,
                session_title=r.session_title,
                occurred_at=r.occurred_at,
                effective_at=r.effective_at,
                event_type=r.event_type,
                reason=r.reason,
                actor_id=r.actor_id,
                is_system_action=r.is_system_action,
                billing_result=r.billing_result,
                credit_id=r.credit_id,
                monthly_revenue_effect_cents=r.monthly_revenue_effect_cents,
            )
            for r in rows
        ],
        total_monthly_revenue_effect_cents=total,
    )
