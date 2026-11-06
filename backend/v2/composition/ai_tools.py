"""D2 wiring: the read-only report tools for "ask the academy".

Each runner calls the same use case the report route calls and shapes the
result with the route's own response model, so a tool result and the HTTP
response are the same JSON. ``admin`` is ``app.state.admin`` (``AdminUseCases``)
and ``people_reports`` is ``app.state.admin_family_index.reports``. Not wired
in ``main.py`` yet: D3 attaches it when the ask route lands.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from backend.v2.contexts.ai.application.tools import (
    ToolCaller,
    ToolRegistry,
    ToolRunner,
    ToolUnavailable,
    build_tool_registry,
)
from backend.v2.contexts.crm.application.money_visibility import can_view_family_money
from backend.v2.interfaces.admin.people_reports_routes import (
    AdminPeopleReportServices,
    AttendanceRiskView,
    FamiliesLostView,
    InquiryConversionView,
    MoneyOwedByAgeView,
)
from backend.v2.interfaces.admin.views import (
    AdminDepositSlipResponse,
    AdminProjectedIncomeResponse,
    AdminRefundsReportResponse,
    AdminReportsDashboardResponse,
    AdminRevenueByCategoryResponse,
    AdminSessionEconomicsResponse,
    AttendanceTrendsResponse,
    CoachUtilizationResponse,
    EnrollmentFunnelResponse,
)
from backend.v2.shared.auth.claims import AuthClaims


def tool_caller(academy_id: str, claims: AuthClaims) -> ToolCaller:
    return ToolCaller(
        academy_id=academy_id,
        is_owner="owner" in claims.roles,
        can_view_family_money=can_view_family_money(claims),
    )


def _report(admin: Any, attr: str, view: type[BaseModel], arg: str) -> ToolRunner:
    """A runner over one ``AdminUseCases`` report callable, like the route."""
    fn = getattr(admin, attr, None)

    async def run(args: Any, _caller: ToolCaller) -> BaseModel:
        if fn is None:
            raise ToolUnavailable(f"{attr} is unavailable")
        result = await fn(getattr(args, arg))
        return view.model_validate(result if isinstance(result, dict) else result.model_dump())

    return run


def compose_ai_tools(admin: Any, people_reports: AdminPeopleReportServices) -> ToolRegistry:
    async def money_owed_by_age(_args: Any, caller: ToolCaller) -> BaseModel:
        report = await people_reports.money_owed_by_age.run(caller.academy_id)
        return MoneyOwedByAgeView.model_validate(report, from_attributes=True)

    async def inquiry_conversion(args: Any, caller: ToolCaller) -> BaseModel:
        report = await people_reports.inquiry_conversion.run(
            caller.academy_id, date_from=args.date_from, date_to=args.date_to
        )
        return InquiryConversionView.model_validate(report, from_attributes=True)

    async def attendance_risk(_args: Any, caller: ToolCaller) -> BaseModel:
        report = await people_reports.attendance_risk.run(caller.academy_id)
        return AttendanceRiskView.model_validate(report, from_attributes=True)

    async def families_lost(args: Any, caller: ToolCaller) -> BaseModel:
        report = await people_reports.families_lost.run(
            caller.academy_id, date_from=args.date_from, date_to=args.date_to
        )
        return FamiliesLostView.model_validate(report, from_attributes=True)

    return build_tool_registry(
        {
            "reports_dashboard": _report(
                admin, "get_reports_dashboard", AdminReportsDashboardResponse, "period"
            ),
            "session_economics": _report(
                admin, "get_session_economics", AdminSessionEconomicsResponse, "period"
            ),
            "projected_income": _report(
                admin, "get_projected_income", AdminProjectedIncomeResponse, "period"
            ),
            "enrollment_funnel": _report(
                admin, "get_enrollment_funnel", EnrollmentFunnelResponse, "period"
            ),
            "attendance_trends": _report(
                admin, "get_attendance_trends", AttendanceTrendsResponse, "periods"
            ),
            "coach_utilization": _report(
                admin, "get_coach_utilization", CoachUtilizationResponse, "periods"
            ),
            "refunds_report": _report(
                admin, "get_refunds_report", AdminRefundsReportResponse, "period"
            ),
            "revenue_by_category": _report(
                admin, "get_revenue_by_category_report", AdminRevenueByCategoryResponse, "period"
            ),
            "deposit_slip": _report(
                admin, "get_deposit_slip_report", AdminDepositSlipResponse, "period"
            ),
            "money_owed_by_age": money_owed_by_age,
            "inquiry_conversion": inquiry_conversion,
            "attendance_risk": attendance_risk,
            "families_lost": families_lost,
        }
    )
