"""Response models for the admin reports pages (session economics).

Report view models live here rather than in ``views.py``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

#: ``needs_payroll`` until the month's coach payroll is final (the month close
#: rule) and every class in it has been held; profit and margin are null then.
PayrollStatus = Literal["complete", "needs_payroll"]


class AdminSessionEconomicsSummary(BaseModel):
    expected_revenue_cents: int = 0
    paid_cents: int = 0
    unpaid_cents: int = 0
    coach_payroll_cents: int = 0
    rent_cents: int = 0
    other_expenses_cents: int = 0
    payroll_status: PayrollStatus = "needs_payroll"
    payroll_blocked_by: str | None = None
    expected_profit_cents: int | None = None
    profit_margin: float | None = None


class AdminSessionEconomicsRow(BaseModel):
    session_id: str
    title: str
    #: Lead coach then assistants, comma separated.
    coach_name: str | None = None
    active_enrollment_count: int = 0
    #: Active enrollments left out of the count and expected total: not billed.
    not_billed_enrollment_count: int = 0
    paid_student_count: int = 0
    unpaid_student_count: int = 0
    monthly_fee_cents: int = 0
    payable_occurrence_count: int = 0
    expected_revenue_per_occurrence_cents: int = 0
    expected_revenue_cents: int = 0
    paid_cents: int = 0
    unpaid_cents: int = 0
    coach_payroll_cents: int = 0
    rent_cents: int = 0
    other_expenses_cents: int = 0
    payroll_status: PayrollStatus = "needs_payroll"
    expected_profit_cents: int | None = None
    profit_margin: float | None = None


class AdminSessionEconomicsResponse(BaseModel):
    period: str
    summary: AdminSessionEconomicsSummary = Field(default_factory=AdminSessionEconomicsSummary)
    sessions: list[AdminSessionEconomicsRow] = []
    empty_states: list[str] = []
