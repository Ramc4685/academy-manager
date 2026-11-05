"""D2: the read-only report tool registry (``contexts/ai/application/tools.py``)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

import backend.v2.contexts.billing.infrastructure.admin_reports_read_model as reports_read_model
from backend.v2.composition.ai_tools import compose_ai_tools, tool_caller
from backend.v2.contexts.ai.application.tools import (
    MAX_TOOL_RESULT_CHARS,
    TOOL_SPECS,
    PeriodArgs,
    ReadOnlyTool,
    ToolCaller,
    ToolNotAllowed,
    ToolNotFound,
    ToolRegistry,
    ToolSpec,
    ToolUnavailable,
    anthropic_tool,
    build_tool_registry,
    truncate_result,
)
from backend.v2.contexts.crm.application.people_reports import (
    AgeBandTotal,
    AttendanceRisk,
    ClassRiskRow,
    CoachRiskRow,
    FamiliesLost,
    InquiryConversion,
    MoneyOwedByAge,
    ReasonCount,
    SourceConversion,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.tenancy import current_academy_id

A, B = "acad-a", "acad-b"
#: A marker per academy that each fake stamps into its report.
SECRET = {A: "ALPHA-ONLY", B: "BRAVO-ONLY"}
OWNER = ToolCaller(academy_id=A, is_owner=True, can_view_family_money=True)
NOW = datetime(2026, 11, 5, tzinfo=UTC)

SAMPLE_ARGS: dict[str, dict[str, Any]] = {
    "reports_dashboard": {"period": "2026-10"},
    "session_economics": {"period": "2026-10"},
    "projected_income": {"period": "2026-11"},
    "enrollment_funnel": {"period": "2026-10"},
    "attendance_trends": {"periods": ["2026-09", "2026-10"]},
    "coach_utilization": {"periods": ["2026-10"]},
    "refunds_report": {"period": "2026-10"},
    "revenue_by_category": {"period": "2026-10"},
    "deposit_slip": {"period": "2026-10"},
    "money_owed_by_age": {},
    "inquiry_conversion": {"date_from": "2026-08-01", "date_to": "2026-10-31"},
    "attendance_risk": {},
    "families_lost": {},
}


# ------------------------------------------------------------------ fakes


def _scoped() -> str:
    return SECRET[current_academy_id()]


@dataclass
class _Funnel:
    period: str | None

    def model_dump(self) -> dict[str, Any]:
        return {
            "leads": 1,
            "applied": 1,
            "assessed": 0,
            "confirmed": 0,
            "dropped": 0,
            "total_applications": 1,
            "conversion_rate": 0.0,
            "period": f"{self.period}:{_scoped()}",
        }


async def _dashboard(period: str) -> dict[str, Any]:
    return {"period": period, "empty_states": [_scoped()]}


async def _economics(period: str) -> dict[str, Any]:
    return {"period": period, "empty_states": [_scoped()]}


async def _projected(period: str) -> dict[str, Any]:
    return {"period": period, "by_session": [{"session_id": "s1", "title": _scoped()}]}


async def _funnel(period: str | None) -> _Funnel:
    return _Funnel(period)


async def _trends(periods: list[str]) -> SimpleNamespace:
    point = {
        "period": _scoped(),
        "scheduled_count": 1,
        "completed_count": 1,
        "no_show_count": 0,
        "completion_rate": 1.0,
    }
    data = {"periods": [point], "overall_completion_rate": 1.0}
    return SimpleNamespace(model_dump=lambda: data)


async def _utilization(periods: list[str]) -> dict[str, Any]:
    coach = {
        "coach_id": _scoped(),
        "period": periods[0],
        "hours": 2.0,
        "payout_minor": 100,
        "utilization_rate": 0.5,
    }
    return {"coaches": [coach], "periods": periods, "total_payout_minor": 100}


async def _refunds(period: str) -> dict[str, Any]:
    return {"period": period, "refunds": [{"reason": _scoped(), "amount_cents": 500}]}


async def _revenue(period: str) -> dict[str, Any]:
    return {"period": period, "rows": [{"category": _scoped(), "amount_cents": 500}]}


async def _deposit(period: str) -> dict[str, Any]:
    return {"period": period, "days": [{"date": _scoped(), "total_cents": 500}]}


def _admin() -> SimpleNamespace:
    return SimpleNamespace(
        get_reports_dashboard=_dashboard,
        get_session_economics=_economics,
        get_projected_income=_projected,
        get_enrollment_funnel=_funnel,
        get_attendance_trends=_trends,
        get_coach_utilization=_utilization,
        get_refunds_report=_refunds,
        get_revenue_by_category_report=_revenue,
        get_deposit_slip_report=_deposit,
    )


def _for(academy_id: str) -> str:
    # The runner is handed the caller's academy and also runs inside its scope.
    assert current_academy_id() == academy_id
    return SECRET[academy_id]


class _MoneyOwed:
    async def run(self, academy_id: str) -> MoneyOwedByAge:
        band = AgeBandTotal("1_30", _for(academy_id), 1, 30, 1, 500)
        return MoneyOwedByAge(date(2026, 11, 5), NOW, band, (band,), 500, 1, 1000, 1)


class _Inquiries:
    async def run(self, academy_id: str, **window: Any) -> InquiryConversion:
        row = SourceConversion("web", 2, 1, 0, 1, 0.5)
        return InquiryConversion(
            date(2026, 8, 1), date(2026, 10, 31), _for(academy_id), (row,), row
        )


class _Risk:
    async def run(self, academy_id: str) -> AttendanceRisk:
        cls = ClassRiskRow("s1", _for(academy_id), None, None, 4, 1, 0.25)
        coach = CoachRiskRow(None, None, 1, 4, 1, 0.25)
        return AttendanceRisk(NOW, (cls,), (coach,), 4, 1)


class _Lost:
    async def run(self, academy_id: str, **window: Any) -> FamiliesLost:
        reason = ReasonCount("moved", "Moved away", 1)
        return FamiliesLost(
            date(2026, 8, 1), date(2026, 10, 31), _for(academy_id), 1, (reason,), 1, (), 0
        )


def _people() -> SimpleNamespace:
    return SimpleNamespace(
        money_owed_by_age=_MoneyOwed(),
        inquiry_conversion=_Inquiries(),
        attendance_risk=_Risk(),
        families_lost=_Lost(),
    )


# ------------------------------------------------------------------ tests


def test_all_thirteen_reports_are_registered() -> None:
    registry = compose_ai_tools(_admin(), _people())
    assert registry.names() == [spec.name for spec in TOOL_SPECS]
    assert set(registry.names()) == set(SAMPLE_ARGS)
    assert len(registry.names()) == 13


@pytest.mark.parametrize("spec", TOOL_SPECS, ids=lambda s: s.name)
def test_argument_schema_round_trips_through_the_anthropic_tool_shape(spec: ToolSpec) -> None:
    rendered = json.loads(json.dumps(anthropic_tool(spec)))

    assert set(rendered) == {"name", "description", "input_schema"}
    assert re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", rendered["name"])
    assert len(rendered["description"]) > 80
    schema = rendered["input_schema"]
    assert schema == spec.args_model.model_json_schema()
    assert schema["type"] == "object"
    assert schema.get("additionalProperties") is False
    assert set(schema.get("required", [])) <= set(schema.get("properties", {}))

    sample = SAMPLE_ARGS[spec.name]
    parsed = spec.args_model.model_validate(sample)
    assert spec.args_model.model_validate(json.loads(parsed.model_dump_json())) == parsed
    assert set(sample) <= set(schema.get("properties", {}))


@pytest.mark.asyncio
@pytest.mark.parametrize("name", list(SAMPLE_ARGS))
async def test_a_tool_called_for_academy_a_returns_nothing_of_academy_b(name: str) -> None:
    registry = compose_ai_tools(_admin(), _people())

    for_a = await registry.call(name, SAMPLE_ARGS[name], OWNER)
    for_b = await registry.call(
        name, SAMPLE_ARGS[name], ToolCaller(B, is_owner=True, can_view_family_money=True)
    )

    json.loads(for_a)
    assert SECRET[A] in for_a and SECRET[B] not in for_a
    assert SECRET[B] in for_b and SECRET[A] not in for_b


@pytest.mark.asyncio
async def test_dashboard_tool_on_the_real_read_model_counts_only_the_callers_academy() -> None:
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["test_db"]
    await db["payments"].insert_many(
        [
            {
                "payment_id": "pay-a",
                "academy_id": A,
                "period": "2026-05",
                "status": "succeeded",
                "final_amount_cents": 10_000,
            },
            {
                "payment_id": "pay-b",
                "academy_id": B,
                "period": "2026-05",
                "status": "succeeded",
                "final_amount_cents": 99_000,
            },
        ]
    )
    admin = SimpleNamespace(get_reports_dashboard=reports_read_model.make_reports_dashboard(db))
    registry = compose_ai_tools(admin, _people())

    result = json.loads(await registry.call("reports_dashboard", {"period": "2026-05"}, OWNER))

    assert result["cash_collected_cents"] == 10_000
    assert "99000" not in json.dumps(result)


@pytest.mark.asyncio
async def test_owner_and_money_tools_follow_the_route_gates() -> None:
    registry = compose_ai_tools(_admin(), _people())
    staff = ToolCaller(academy_id=A)

    visible = {spec.name for spec in registry.visible_to(staff)}
    assert visible == {
        "reports_dashboard",
        "enrollment_funnel",
        "attendance_trends",
        "coach_utilization",
        "inquiry_conversion",
        "attendance_risk",
        "families_lost",
    }
    assert {t["name"] for t in registry.anthropic_tools(staff)} == visible
    with pytest.raises(ToolNotAllowed):
        await registry.call("session_economics", {"period": "2026-10"}, staff)
    with pytest.raises(ToolNotAllowed):
        await registry.call("money_owed_by_age", {}, staff)


def test_tool_caller_reads_the_owner_and_money_roles_from_claims() -> None:
    owner = AuthClaims(user_id="u", email="o@x.test", academy_id=A, roles=("owner",))
    coach = AuthClaims(user_id="c", email="c@x.test", academy_id=A, roles=("coach",))

    assert tool_caller(A, owner).is_owner is True
    assert tool_caller(A, owner).can_view_family_money is True
    assert tool_caller(A, coach) == ToolCaller(academy_id=A)


@pytest.mark.asyncio
async def test_bad_arguments_unknown_tools_and_missing_use_cases_are_refused() -> None:
    registry = compose_ai_tools(SimpleNamespace(get_reports_dashboard=_dashboard), _people())

    with pytest.raises(ValidationError):
        await registry.call("reports_dashboard", {"period": "2026-13"}, OWNER)
    with pytest.raises(ValidationError):
        await registry.call("reports_dashboard", {"period": "2026-10", "academy_id": B}, OWNER)
    with pytest.raises(ToolNotFound):
        await registry.call("drop_tables", {}, OWNER)
    with pytest.raises(ToolUnavailable):
        await registry.call("session_economics", {"period": "2026-10"}, OWNER)
    with pytest.raises(ValueError, match="unknown tools"):
        build_tool_registry({"not_a_report": _dashboard})  # type: ignore[dict-item]


def test_truncation_cuts_to_the_stated_maximum() -> None:
    short = "x" * MAX_TOOL_RESULT_CHARS
    assert truncate_result(short) == short

    long = "y" * (MAX_TOOL_RESULT_CHARS * 2)
    cut = truncate_result(long)
    assert len(cut) == MAX_TOOL_RESULT_CHARS
    assert cut.endswith(f"[truncated: {MAX_TOOL_RESULT_CHARS} of {len(long)} characters shown]")


@pytest.mark.asyncio
async def test_registry_call_truncates_a_large_result() -> None:
    async def huge(args: Any, caller: ToolCaller) -> Any:
        return SimpleNamespace(model_dump_json=lambda: "z" * (MAX_TOOL_RESULT_CHARS + 500))

    spec = ToolSpec("big", "a big report", PeriodArgs, "admin")
    registry = ToolRegistry([ReadOnlyTool(spec=spec, run=huge)])

    result = await registry.call("big", {"period": "2026-10"}, OWNER)
    assert len(result) == MAX_TOOL_RESULT_CHARS
    assert "truncated" in result
