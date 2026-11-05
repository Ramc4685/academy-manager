"""Read-only report tools for "ask the academy" (Phase 3 slice D2).

Each tool is a name, a one-paragraph description, a pydantic argument model
and a runner that calls an existing report use case. The specs live here; the
runners are built in ``composition/ai_tools.py`` because the reports belong to
other contexts (billing, enrollment, coaching, crm) and this context imports
none of them. Nothing here calls a model: D3's tool-use loop is the first user.

``ToolRegistry.call`` validates the arguments, refuses a tool the caller's
role may not see (the same owner and family-money gates as the HTTP routes),
runs the use case inside ``tenant_scope(caller.academy_id)`` and returns the
typed response model as JSON, cut to ``MAX_TOOL_RESULT_CHARS``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.v2.shared.tenancy import tenant_scope

#: Most characters of JSON one tool result may put in front of the model.
MAX_TOOL_RESULT_CHARS = 12_000

#: ``admin``: any admin persona caller; ``owner``: the routes behind
#: ``require_owner()``; ``family_money``: ``can_view_family_money`` (#553).
ToolAccess = Literal["admin", "owner", "family_money"]

Period = Annotated[
    str,
    Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="A calendar month, YYYY-MM."),
]


class ToolError(Exception):
    """A tool could not run; the message is safe to hand back to the model."""


class ToolNotFound(ToolError):
    pass


class ToolNotAllowed(ToolError):
    pass


class ToolUnavailable(ToolError):
    pass


# ------------------------------------------------------------------ arguments


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NoArgs(_Args):
    pass


class PeriodArgs(_Args):
    period: Period


class OptionalPeriodArgs(_Args):
    period: Period | None = None


class PeriodsArgs(_Args):
    periods: list[Period] = Field(min_length=1, max_length=12)


class DateRangeArgs(_Args):
    date_from: date | None = Field(
        default=None, description="First academy-local day, inclusive. Default: 90 days ago."
    )
    date_to: date | None = Field(
        default=None, description="Last academy-local day, inclusive. Default: today."
    )


# ------------------------------------------------------------------ registry


@dataclass(frozen=True)
class ToolCaller:
    """Who is asking. Built from the auth claims in composition."""

    academy_id: str
    is_owner: bool = False
    can_view_family_money: bool = False

    def may_use(self, access: ToolAccess) -> bool:
        if access == "owner":
            return self.is_owner
        if access == "family_money":
            return self.can_view_family_money
        return True


ToolRunner = Callable[[Any, ToolCaller], Awaitable[BaseModel]]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args_model: type[BaseModel]
    access: ToolAccess


@dataclass(frozen=True)
class ReadOnlyTool:
    spec: ToolSpec
    run: ToolRunner


def anthropic_tool(spec: ToolSpec) -> dict[str, Any]:
    """One tool in the Anthropic Messages API ``tools`` shape."""
    return {
        "name": spec.name,
        "description": spec.description,
        "input_schema": spec.args_model.model_json_schema(),
    }


def truncate_result(text: str, limit: int = MAX_TOOL_RESULT_CHARS) -> str:
    if len(text) <= limit:
        return text
    marker = f"...[truncated: {limit} of {len(text)} characters shown]"
    return text[: max(limit - len(marker), 0)] + marker


class ToolRegistry:
    def __init__(self, tools: Iterable[ReadOnlyTool]) -> None:
        self._tools = {tool.spec.name: tool for tool in tools}

    def names(self) -> list[str]:
        return list(self._tools)

    def visible_to(self, caller: ToolCaller) -> list[ToolSpec]:
        return [t.spec for t in self._tools.values() if caller.may_use(t.spec.access)]

    def anthropic_tools(self, caller: ToolCaller) -> list[dict[str, Any]]:
        return [anthropic_tool(spec) for spec in self.visible_to(caller)]

    async def call(self, name: str, arguments: Mapping[str, Any], caller: ToolCaller) -> str:
        """Run one tool; a bad argument raises pydantic ``ValidationError``."""
        tool = self._tools.get(name)
        if tool is None:
            raise ToolNotFound(f"unknown tool: {name}")
        if not caller.may_use(tool.spec.access):
            raise ToolNotAllowed(f"{name} is not available to this user")
        args = tool.spec.args_model.model_validate(dict(arguments))
        with tenant_scope(caller.academy_id):
            result = await tool.run(args, caller)
        return truncate_result(result.model_dump_json())


def build_tool_registry(runners: Mapping[str, ToolRunner]) -> ToolRegistry:
    """Pair each spec with its runner; a spec with no runner is not registered."""
    unknown = set(runners) - {spec.name for spec in TOOL_SPECS}
    if unknown:
        raise ValueError(f"runners for unknown tools: {sorted(unknown)}")
    return ToolRegistry(
        ReadOnlyTool(spec=spec, run=runners[spec.name])
        for spec in TOOL_SPECS
        if spec.name in runners
    )


# ------------------------------------------------------------------ the tools

TOOL_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="reports_dashboard",
        description=(
            "The owner's monthly dashboard for one month: cash collected, amount billed, "
            "collection rate, outstanding dues, attendance rate, sessions scheduled, completed "
            "and cancelled, seat capacity and waitlist, expenses by category, overdue families "
            "by age bucket, profit and loss, and coach payroll status. Money is in cents."
        ),
        args_model=PeriodArgs,
        access="admin",
    ),
    ToolSpec(
        name="session_economics",
        description=(
            "Per class for one month: active enrollments, paid and unpaid students, monthly "
            "fee, expected revenue, paid and unpaid amounts, coach payroll, rent and other "
            "expenses, expected profit and margin, plus an academy-wide summary. Use it to "
            "see which classes make or lose money. Money is in cents."
        ),
        args_model=PeriodArgs,
        access="owner",
    ),
    ToolSpec(
        name="projected_income",
        description=(
            "Expected tuition income for one month from current enrollments: the total, the "
            "part on autopay and the part paid manually, enrollment counts for each, and the "
            "expected amount per class. It is a projection, not money received. Money is in "
            "cents."
        ),
        args_model=PeriodArgs,
        access="owner",
    ),
    ToolSpec(
        name="enrollment_funnel",
        description=(
            "Registration applications by stage: leads, applied, assessed, confirmed and "
            "dropped, the total and the conversion rate. Pass a month to limit it to "
            "applications from that month, or leave it out for all time."
        ),
        args_model=OptionalPeriodArgs,
        access="admin",
    ),
    ToolSpec(
        name="attendance_trends",
        description=(
            "Attendance per month for the months given: sessions scheduled, completed and "
            "no-show counts and the completion rate for each month, plus the overall "
            "completion rate. Use it to compare months; pass up to twelve."
        ),
        args_model=PeriodsArgs,
        access="admin",
    ),
    ToolSpec(
        name="coach_utilization",
        description=(
            "Per coach and month for the months given: hours worked, payout, utilization rate "
            "and the share of attendance recorded within 24 hours, plus the total payout. "
            "Coaches are identified by id. Payout is in cents."
        ),
        args_model=PeriodsArgs,
        access="admin",
    ),
    ToolSpec(
        name="refunds_report",
        description=(
            "Refunds and account credits issued in one month: the total and count of each, "
            "and every refund and credit with its amount, date, invoice and reason as "
            "recorded. Money is in cents."
        ),
        args_model=PeriodArgs,
        access="owner",
    ),
    ToolSpec(
        name="revenue_by_category",
        description=(
            "Payments received in one month, allocated to what they paid for (tuition, fees "
            "and other categories), with the total allocated, the amount per category and "
            "the amount received but not yet applied to an invoice. Money is in cents."
        ),
        args_model=PeriodArgs,
        access="owner",
    ),
    ToolSpec(
        name="deposit_slip",
        description=(
            "The month's deposit slip: money received in one month, per day and per payment "
            "method within each day, with amounts and payment counts and the month total. "
            "Use it to reconcile against the bank. Money is in cents."
        ),
        args_model=PeriodArgs,
        access="owner",
    ),
    ToolSpec(
        name="money_owed_by_age",
        description=(
            "Open family balances as of today, by days past due: not yet due, 1-30, 31-60 and "
            "over 60 days, with the family count and total for each band, the overdue total "
            "and the whole open balance. Money is in cents."
        ),
        args_model=NoArgs,
        access="family_money",
    ),
    ToolSpec(
        name="inquiry_conversion",
        description=(
            "Inquiries received between two academy-local days, by source (web form, walk-in "
            "and so on), with how many are still leads, reached a trial, or enrolled, and the "
            "conversion rate per source and in total. Defaults to the last 90 days."
        ),
        args_model=DateRangeArgs,
        access="admin",
    ),
    ToolSpec(
        name="attendance_risk",
        description=(
            "Students who have stopped coming (lifecycle at risk) right now, counted per class "
            "and per coach with the at-risk rate, plus the academy totals. Use it to find the "
            "classes and coaches with the most students drifting away."
        ),
        args_model=NoArgs,
        access="admin",
    ),
    ToolSpec(
        name="families_lost",
        description=(
            "Families that left between two academy-local days, counted by the reason "
            "recorded when they left, and the rest by how they left (dropped by staff, "
            "cancelled by the family, hold ran out, class removed). Defaults to the last 90 "
            "days."
        ),
        args_model=DateRangeArgs,
        access="admin",
    ),
)
