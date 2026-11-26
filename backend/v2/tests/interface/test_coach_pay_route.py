"""S59: GET /api/v2/coach/profile/pay is self only (security matrix)."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime

from fastapi.testclient import TestClient

from backend.v2.contexts.finance.application.use_cases.coach_pay_summary import (
    CoachPayClass,
    GetCoachPaySummary,
    PayslipRow,
)
from backend.v2.shared.reporting_definitions import month_window
from backend.v2.tests.interface.conftest import (
    _assistant_coach_claims,
    _build_use_cases,
    _coach_claims,
    _make_app,
    _parent_claims,
)


class _Reader:
    """Records who was asked for; mirrors the Mongo reader's narrow rows."""

    def __init__(self) -> None:
        self.asked: list[tuple[str, str]] = []

    async def academy_timezone(self, academy_id: str) -> str | None:
        return "America/Chicago"

    async def taught_classes(self, *, academy_id, coach_id, start, end):
        self.asked.append((academy_id, coach_id))
        return [
            CoachPayClass(
                occurrence_id="o1",
                start_at=datetime(2026, 11, 3, 23, 30, tzinfo=UTC),
                class_name="Tuesday Intermediate",
                minutes=60,
                role="lead",
            )
        ]

    async def released_payslip(self, *, academy_id, coach_id, start, end):
        return PayslipRow(
            period_start=date(2026, 11, 1),
            period_end=date(2026, 11, 30),
            status="approved",
            total_minor=4500,
            currency="usd",
            approved_on=date(2026, 11, 20),
        )


def _client(seed, claims=None):
    reader = _Reader()
    use_case = GetCoachPaySummary(
        reader=reader, month_window=month_window, today=lambda _zone: date(2026, 11, 26)
    )

    async def academy_info(*, academy_id: str):
        return {"name": "Demo Academy", "contact_phone": "555-0100", "contact_email": None}

    use_cases = replace(
        _build_use_cases(seed), get_coach_pay=use_case, get_academy_info=academy_info
    )
    return TestClient(_make_app(claims or _coach_claims(), use_cases)), reader


def test_pay_reads_the_signed_in_coach_and_ignores_a_coach_param(seed):
    client, reader = _client(seed)
    r = client.get("/api/v2/coach/profile/pay?coach_id=someone-else&month=2026-11")

    assert r.status_code == 200, r.text
    assert reader.asked == [("test-academy", "coach-1")]
    assert r.headers["cache-control"] == "no-store"
    body = r.json()
    assert body["classes_taught"] == 1 and body["minutes_taught"] == 60
    assert body["payslip"]["total_cents"] == 4500
    assert body["academy_contact"] == {"name": "Demo Academy", "phone": "555-0100", "email": None}
    for secret in ("rate", "percent", "amount_minor", "lines", "revenue"):
        assert secret not in r.text


def test_assistant_coach_reads_their_own_pay(seed):
    client, reader = _client(seed, _assistant_coach_claims())
    assert client.get("/api/v2/coach/profile/pay").status_code == 200
    assert reader.asked == [("test-academy", "asst-1")]


def test_month_outside_two_years_is_422(seed):
    client, _ = _client(seed)
    assert client.get("/api/v2/coach/profile/pay?month=2023-01").status_code == 422
    assert client.get("/api/v2/coach/profile/pay?month=nope").status_code == 422


def test_parent_gets_404(seed):
    client, reader = _client(seed, _parent_claims())
    assert client.get("/api/v2/coach/profile/pay").status_code == 404
    assert reader.asked == []


def test_no_route_names_another_coach(seed):
    client, reader = _client(seed)
    for path in (
        "/api/v2/coach/profile/pay/demo-coach",
        "/api/v2/coach/pay",
        "/api/v2/coach/payroll",
    ):
        assert client.get(path).status_code == 404, path
    assert reader.asked == []


def test_security_matrix_lists_the_self_only_pay_read():
    from pathlib import Path

    matrix = (Path(__file__).resolve().parents[4] / "docs/security-matrix.md").read_text()
    row = next(line for line in matrix.splitlines() if "GET /coach/profile/pay" in line)
    assert "Self only" in row and "No (404)" in row
