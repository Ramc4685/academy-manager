"""Interface tests for the People reports (roadmap L5a and L5b).

``GET /admin/reports/people/money-owed-by-age`` and
``GET /admin/reports/people/inquiry-conversion``: response shapes (the contract
the ``/admin/reports`` cards read), the money gate (403 through
``can_view_family_money``), the admin persona gate (404), bad ranges (422)
and an unreadable money source (503, never a zero).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.contexts.crm.application.family_index import FamilyIndexUnavailable
from backend.v2.contexts.crm.application.people_reports import (
    AgeBandTotal,
    AttendanceRiskFacts,
    DepartureFact,
    FamiliesLost,
    InvalidReportRange,
    MoneyOwedByAge,
    PeopleReportUnavailable,
    RiskClass,
    RiskStudent,
    summarize_attendance_risk,
    summarize_families_lost,
    summarize_inquiry_conversion,
)
from backend.v2.contexts.crm.domain.family_index import FamilyChild, FamilyIndex, FamilyRecord
from backend.v2.interfaces.admin import people_reports_routes
from backend.v2.interfaces.admin.owner_gate import OWNER_ONLY_ROUTE_PATHS
from backend.v2.interfaces.admin.people_reports_routes import get_admin_people_reports
from backend.v2.interfaces.admin.router import router as admin_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers

NOW = datetime(2026, 9, 23, 15, 0, tzinfo=UTC)
MONEY_URL = "/api/v2/admin/reports/people/money-owed-by-age"
INQUIRY_URL = "/api/v2/admin/reports/people/inquiry-conversion"
RISK_URL = "/api/v2/admin/reports/people/attendance-risk"
LOST_URL = "/api/v2/admin/reports/people/families-lost"


def _band(key: str, low: int | None, high: int | None, families: int, cents: int) -> AgeBandTotal:
    return AgeBandTotal(
        key=key,
        label=key,
        min_days=low,
        max_days=high,
        family_count=families,
        total_cents=cents,
    )


class FakeMoney:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.error: Exception | None = None

    async def run(self, academy_id: str) -> MoneyOwedByAge:
        self.calls.append(academy_id)
        if self.error:
            raise self.error
        return MoneyOwedByAge(
            as_of=date(2026, 9, 23),
            generated_at=NOW,
            not_yet_due=_band("not_yet_due", None, 0, 2, 6_000),
            bands=(
                _band("days_1_30", 1, 30, 1, 3_500),
                _band("days_31_60", 31, 60, 1, 7_000),
                _band("days_over_60", 61, None, 1, 4_000),
            ),
            overdue_cents=14_500,
            overdue_family_count=2,
            balance_cents=20_500,
            owing_family_count=2,
        )


class FakeInquiry:
    def __init__(self) -> None:
        self.calls: list[tuple[str, date | None, date | None]] = []

    async def run(
        self, academy_id: str, *, date_from: date | None = None, date_to: date | None = None
    ) -> Any:
        self.calls.append((academy_id, date_from, date_to))
        if date_from and date_to and date_from > date_to:
            raise InvalidReportRange("from must be on or before to")
        return summarize_inquiry_conversion(
            [("website", "lead", 2), ("website", "enrolled", 2), ("referral", "trial", 1)],
            date_from=date_from or date(2026, 6, 26),
            date_to=date_to or date(2026, 9, 23),
            timezone="America/Chicago",
        )


class FakeRisk:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.error: Exception | None = None

    async def run(self, academy_id: str) -> Any:
        self.calls.append(academy_id)
        if self.error:
            raise self.error
        return summarize_attendance_risk(
            AttendanceRiskFacts(
                students=(
                    RiskStudent("s1", "at_risk", ("c1",)),
                    RiskStudent("s2", "active", ("c1",)),
                ),
                classes={"c1": RiskClass("c1", "Tuesday Juniors", "coach-1")},
                coach_names={"coach-1": "Testcoach One"},
            ),
            generated_at=NOW,
        )


class FakeLost:
    def __init__(self) -> None:
        self.calls: list[tuple[str, date | None, date | None]] = []
        self.error: Exception | None = None

    async def run(
        self, academy_id: str, *, date_from: date | None = None, date_to: date | None = None
    ) -> FamiliesLost:
        self.calls.append((academy_id, date_from, date_to))
        if self.error:
            raise self.error
        if date_from and date_to and date_from > date_to:
            raise InvalidReportRange("from must be on or before to")
        index = FamilyIndex(
            academy_id=academy_id,
            generated_at=NOW,
            families=(
                FamilyRecord(
                    family_id="f1",
                    parent_name=None,
                    email=None,
                    phone=None,
                    has_account=False,
                    children=(FamilyChild(student_id="s1", name="s1", lifecycle="left"),),
                    stage="left",
                ),
                FamilyRecord(
                    family_id="f2",
                    parent_name=None,
                    email=None,
                    phone=None,
                    has_account=False,
                    children=(FamilyChild(student_id="s2", name="s2", lifecycle="left"),),
                    stage="left",
                ),
            ),
        )
        return summarize_families_lost(
            index,
            [
                DepartureFact("s1", "withdrawn", "cost", NOW),
                DepartureFact("s2", "cancelled", None, NOW),
            ],
            date_from=date_from or date(2026, 6, 26),
            date_to=date_to or date(2026, 9, 23),
            timezone="America/Chicago",
        )


class FakeServices:
    def __init__(self) -> None:
        self.money_owed_by_age = FakeMoney()
        self.inquiry_conversion = FakeInquiry()
        self.attendance_risk = FakeRisk()
        self.families_lost = FakeLost()


def _claims(*roles: str) -> AuthClaims:
    return AuthClaims(user_id="u-1", email="u@example.test", academy_id="acad", roles=tuple(roles))  # type: ignore[arg-type]


def _client(roles: tuple[str, ...], services: FakeServices) -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(admin_router, prefix="/api/v2")
    app.dependency_overrides[get_auth_claims] = lambda: _claims(*roles)
    app.dependency_overrides[get_admin_people_reports] = lambda: services
    return TestClient(app)


@pytest.fixture
def services() -> FakeServices:
    return FakeServices()


@pytest.fixture
def admin(services: FakeServices) -> Iterator[TestClient]:
    with _client(("admin",), services) as c:
        yield c


def test_money_owed_by_age_shape(admin: TestClient, services: FakeServices) -> None:
    res = admin.get(MONEY_URL)
    assert res.status_code == 200
    assert services.money_owed_by_age.calls == ["acad"]
    body = res.json()
    assert body["as_of"] == "2026-09-23"
    assert body["not_yet_due"] == {
        "key": "not_yet_due",
        "label": "not_yet_due",
        "min_days": None,
        "max_days": 0,
        "family_count": 2,
        "total_cents": 6_000,
    }
    assert [(b["key"], b["family_count"], b["total_cents"]) for b in body["bands"]] == [
        ("days_1_30", 1, 3_500),
        ("days_31_60", 1, 7_000),
        ("days_over_60", 1, 4_000),
    ]
    assert body["overdue_cents"] == 14_500
    assert body["balance_cents"] == 20_500
    assert body["owing_family_count"] == 2
    assert body["overdue_family_count"] == 2


def test_money_owed_is_403_when_the_money_seam_says_no(
    services: FakeServices, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(people_reports_routes, "can_view_family_money", lambda claims: False)
    with _client(("admin",), services) as client:
        res = client.get(MONEY_URL)
        assert res.status_code == 403
        # The inquiry card carries no money: still readable.
        assert client.get(INQUIRY_URL).status_code == 200
    assert services.money_owed_by_age.calls == []


@pytest.mark.parametrize("roles", [("coach",), ("parent",), ()])
def test_non_admin_personas_are_404(services: FakeServices, roles: tuple[str, ...]) -> None:
    with _client(roles, services) as client:
        assert client.get(MONEY_URL).status_code == 404
        assert client.get(INQUIRY_URL).status_code == 404
        assert client.get(RISK_URL).status_code == 404
        assert client.get(LOST_URL).status_code == 404
    assert services.money_owed_by_age.calls == []
    assert services.inquiry_conversion.calls == []
    assert services.attendance_risk.calls == []
    assert services.families_lost.calls == []


@pytest.mark.parametrize(
    "error", [PeopleReportUnavailable("money down"), FamilyIndexUnavailable("users down")]
)
def test_money_source_failure_is_503_not_a_zero(
    admin: TestClient, services: FakeServices, error: Exception
) -> None:
    services.money_owed_by_age.error = error
    assert admin.get(MONEY_URL).status_code == 503


def test_inquiry_conversion_shape_and_default_window(
    admin: TestClient, services: FakeServices
) -> None:
    res = admin.get(INQUIRY_URL)
    assert res.status_code == 200
    assert services.inquiry_conversion.calls == [("acad", None, None)]
    body = res.json()
    assert (body["date_from"], body["date_to"], body["timezone"]) == (
        "2026-06-26",
        "2026-09-23",
        "America/Chicago",
    )
    assert [s["source"] for s in body["sources"]] == [
        "website",
        "whatsapp_or_phone",
        "referral",
        "other",
    ]
    website = body["sources"][0]
    assert website == {
        "source": "website",
        "inquiries": 4,
        "lead": 2,
        "trial": 0,
        "enrolled": 2,
        "conversion_rate": 0.5,
    }
    assert body["sources"][3]["conversion_rate"] is None
    assert body["total"]["inquiries"] == 5
    assert body["total"]["enrolled"] == 2


def test_inquiry_conversion_passes_the_range_through(
    admin: TestClient, services: FakeServices
) -> None:
    res = admin.get(INQUIRY_URL, params={"from": "2026-09-01", "to": "2026-09-10"})
    assert res.status_code == 200
    assert services.inquiry_conversion.calls == [("acad", date(2026, 9, 1), date(2026, 9, 10))]


def test_inquiry_conversion_bad_range_is_422(admin: TestClient) -> None:
    assert (
        admin.get(INQUIRY_URL, params={"from": "2026-09-10", "to": "2026-09-01"}).status_code == 422
    )
    assert admin.get(INQUIRY_URL, params={"from": "not-a-date"}).status_code == 422


def test_people_reports_are_admin_not_owner_only() -> None:
    """Gated by the money seam (owner/admin), not the owner-only report tier."""
    for path in (MONEY_URL, INQUIRY_URL, RISK_URL, LOST_URL):
        assert ("GET", path) not in OWNER_ONLY_ROUTE_PATHS


# ------------------------------------------------------------ L5b


def test_attendance_risk_shape(admin: TestClient, services: FakeServices) -> None:
    res = admin.get(RISK_URL)
    assert res.status_code == 200
    assert services.attendance_risk.calls == ["acad"]
    body = res.json()
    assert body["by_class"] == [
        {
            "session_id": "c1",
            "title": "Tuesday Juniors",
            "coach_id": "coach-1",
            "coach_name": "Testcoach One",
            "students": 2,
            "at_risk": 1,
            "at_risk_rate": 0.5,
        }
    ]
    assert body["by_coach"] == [
        {
            "coach_id": "coach-1",
            "coach_name": "Testcoach One",
            "classes": 1,
            "students": 2,
            "at_risk": 1,
            "at_risk_rate": 0.5,
        }
    ]
    assert (body["students"], body["at_risk"]) == (2, 1)


def test_attendance_risk_needs_no_money_visibility(
    services: FakeServices, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(people_reports_routes, "can_view_family_money", lambda claims: False)
    with _client(("admin",), services) as client:
        assert client.get(RISK_URL).status_code == 200
        assert client.get(LOST_URL).status_code == 200


def test_attendance_risk_source_failure_is_503(admin: TestClient, services: FakeServices) -> None:
    services.attendance_risk.error = PeopleReportUnavailable("down")
    assert admin.get(RISK_URL).status_code == 503


def test_families_lost_shape(admin: TestClient, services: FakeServices) -> None:
    res = admin.get(LOST_URL)
    assert res.status_code == 200
    assert services.families_lost.calls == [("acad", None, None)]
    body = res.json()
    assert (body["date_from"], body["date_to"], body["timezone"]) == (
        "2026-06-26",
        "2026-09-23",
        "America/Chicago",
    )
    assert body["families_lost"] == 2
    assert len(body["by_reason"]) == 10
    assert {r["key"]: r["families"] for r in body["by_reason"] if r["families"]} == {"cost": 1}
    assert body["with_reason"] == 1
    assert body["by_transition"] == [
        {"key": "cancelled_by_family", "label": "Cancelled by the family", "families": 1}
    ]
    assert body["without_reason"] == 1


def test_families_lost_range_and_errors(admin: TestClient, services: FakeServices) -> None:
    assert admin.get(LOST_URL, params={"from": "2026-09-01", "to": "2026-09-10"}).status_code == 200
    assert services.families_lost.calls[-1] == ("acad", date(2026, 9, 1), date(2026, 9, 10))
    assert admin.get(LOST_URL, params={"from": "2026-09-10", "to": "2026-09-01"}).status_code == 422
    for error in (PeopleReportUnavailable("down"), FamilyIndexUnavailable("users down")):
        services.families_lost.error = error
        assert admin.get(LOST_URL).status_code == 503
