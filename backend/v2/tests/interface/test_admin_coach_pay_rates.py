"""Admin coach pay-rate BFF routes."""

from __future__ import annotations

from datetime import UTC, datetime

from backend.v2.contexts.coaching.application.use_cases.manage_coach_rates import (
    SetCoachPayRateCommand,
)
from backend.v2.contexts.coaching.domain.payout import CoachRate


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


def _rate(**overrides) -> CoachRate:
    base = dict(
        rate_id="cr-1",
        academy_id="acad",
        coach_id="coach-1",
        billing_unit="percent_of_revenue",
        amount_minor=0,
        percent_bps=6000,
        currency="USD",
        effective_from=_dt("2026-06-01T00:00:00"),
        effective_until=None,
        status="active",
    )
    base.update(overrides)
    return CoachRate(**base)


class _SetCoachPayRate:
    def __init__(self, rate: CoachRate) -> None:
        self.rate = rate
        self.commands: list[SetCoachPayRateCommand] = []

    async def execute(self, command: SetCoachPayRateCommand) -> CoachRate:
        self.commands.append(command)
        if command.billing_unit == "percent_of_revenue" and command.percent_bps is None:
            raise ValueError("percent is required for percent_of_revenue rates")
        return self.rate


class _ListCoachPayRates:
    def __init__(self, rates: list[CoachRate]) -> None:
        self.rates = rates

    async def execute(self, *, coach_id: str) -> list[CoachRate]:
        return [r for r in self.rates if r.coach_id == coach_id]


async def _list_sessions_with_missing_price(_date, *, window=None, coach_id=None):
    return [
        {
            "session_id": "sess-missing-price",
            "coach_id": coach_id,
            "title": "No Price Session",
            "amount_cents": None,
        }
    ]


async def _list_sessions_without_missing_price(_date, *, window=None, coach_id=None):
    return []


def test_set_coach_pay_rate_converts_percent_to_bps(admin_client):
    fake = _SetCoachPayRate(_rate())
    admin_client.use_cases.set_coach_pay_rate = fake
    admin_client.use_cases.list_admin_sessions = _list_sessions_without_missing_price

    response = admin_client.post(
        "/api/v2/admin/coaches/coach-1/pay-rates",
        json={"billing_unit": "percent_of_revenue", "percent": 60},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["percent"] == 60.0
    assert body["billing_unit"] == "percent_of_revenue"
    assert body["status"] == "active"
    assert fake.commands[0].percent_bps == 6000
    assert fake.commands[0].coach_id == "coach-1"


def test_set_coach_pay_rate_validation_maps_to_400(admin_client):
    admin_client.use_cases.set_coach_pay_rate = _SetCoachPayRate(_rate())

    response = admin_client.post(
        "/api/v2/admin/coaches/coach-1/pay-rates",
        json={"billing_unit": "percent_of_revenue"},
    )

    assert response.status_code == 400
    assert "percent is required" in response.json()["detail"]


def test_set_percent_rate_blocks_active_sessions_with_missing_price(admin_client):
    admin_client.use_cases.set_coach_pay_rate = _SetCoachPayRate(_rate())
    admin_client.use_cases.list_admin_sessions = _list_sessions_with_missing_price

    response = admin_client.post(
        "/api/v2/admin/coaches/coach-1/pay-rates",
        json={"billing_unit": "percent_of_revenue", "percent": 60},
    )

    assert response.status_code == 400
    assert "Percent-of-revenue coach pay requires session prices" in response.json()["detail"]
    assert "No Price Session" in response.json()["detail"]


def test_list_coach_pay_rates_returns_history(admin_client):
    rates = [
        _rate(),
        _rate(
            rate_id="cr-0",
            billing_unit="per_session",
            amount_minor=5000,
            percent_bps=None,
            effective_from=_dt("2026-01-01T00:00:00"),
            effective_until=_dt("2026-06-01T00:00:00"),
            status="superseded",
        ),
    ]
    admin_client.use_cases.list_coach_pay_rates = _ListCoachPayRates(rates)

    response = admin_client.get("/api/v2/admin/coaches/coach-1/pay-rates")

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["rates"]) == 2
    assert body["rates"][0]["percent"] == 60.0
    assert body["rates"][1]["amount_cents"] == 5000
    assert body["rates"][1]["percent"] is None


def test_coach_pay_rates_unconfigured_returns_503(admin_client):
    admin_client.use_cases.set_coach_pay_rate = None
    admin_client.use_cases.list_coach_pay_rates = None

    assert admin_client.get("/api/v2/admin/coaches/coach-1/pay-rates").status_code == 503
    assert (
        admin_client.post(
            "/api/v2/admin/coaches/coach-1/pay-rates",
            json={"billing_unit": "per_session", "amount_cents": 5000},
        ).status_code
        == 503
    )
