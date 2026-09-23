"""Interface tests for ``GET /admin/families`` and ``/admin/families/summary``.

People CRM spec §3.2. The response shapes here are the contract the Families
view (A3b) consumes.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.contexts.crm.application.family_index import (
    FamilyChild,
    FamilyIndex,
    FamilyIndexUnavailable,
    FamilyMoney,
    FamilyRecord,
)
from backend.v2.interfaces.admin import family_index_routes
from backend.v2.interfaces.admin.family_index_routes import get_admin_family_index
from backend.v2.interfaces.admin.router import router as admin_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers

NOW = datetime(2026, 9, 23, 15, 0, tzinfo=UTC)


def _index(academy_id: str) -> FamilyIndex:
    return FamilyIndex(
        academy_id=academy_id,
        generated_at=NOW,
        families=(
            FamilyRecord(
                family_id="u-alpha",
                parent_name="Testparent Alpha",
                email="alpha@example.test",
                phone="555-010-0001",
                has_account=True,
                children=(
                    FamilyChild(
                        student_id="s-1",
                        name="Kiddo Alpha",
                        lifecycle="active",
                        session_ids=("sess-sat",),
                        session_titles=("Sat Beginners",),
                    ),
                ),
                stage="active",
                card_on_file=True,
                registration="registered",
                money=FamilyMoney(
                    balance_cents=6000,
                    open_invoice_count=1,
                    overdue_invoice_count=1,
                    overdue_cents=6000,
                    oldest_overdue_due_on=date(2026, 9, 1),
                    last_failed_payment_at=None,
                ),
            ),
            FamilyRecord(
                family_id="u-bravo",
                parent_name="Testparent Bravo",
                email=None,
                phone=None,
                has_account=False,
                children=(),
                stage="left",
                card_on_file=False,
                registration="not_invited",
                money=None,
            ),
        ),
        warnings=(),
    )


class FakeIndex:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.error: Exception | None = None

    async def build(self, academy_id: str) -> FamilyIndex:
        self.calls.append(academy_id)
        if self.error:
            raise self.error
        return _index(academy_id)


class FakeServices:
    def __init__(self) -> None:
        self.index = FakeIndex()


def _claims(*roles: str) -> AuthClaims:
    return AuthClaims(user_id="u-1", email="u@example.test", academy_id="acad", roles=tuple(roles))  # type: ignore[arg-type]


def _client(roles: tuple[str, ...], services: FakeServices) -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(admin_router, prefix="/api/v2")
    app.dependency_overrides[get_auth_claims] = lambda: _claims(*roles)
    app.dependency_overrides[get_admin_family_index] = lambda: services
    return TestClient(app)


@pytest.fixture
def services() -> FakeServices:
    return FakeServices()


@pytest.fixture
def admin(services: FakeServices) -> Iterator[TestClient]:
    with _client(("admin",), services) as c:
        yield c


def test_list_shape_and_tenant(admin: TestClient, services: FakeServices) -> None:
    res = admin.get("/api/v2/admin/families")
    assert res.status_code == 200
    body = res.json()
    assert services.index.calls == ["acad"]
    assert body["total"] == 2
    assert body["page"] == 1 and body["page_size"] == 50
    assert body["money_visible"] is True
    alpha = body["families"][0]
    assert alpha == {
        "family_id": "u-alpha",
        "parent_name": "Testparent Alpha",
        "email": "alpha@example.test",
        "phone": "555-010-0001",
        "has_account": True,
        "stage": "active",
        "children": [
            {
                "student_id": "s-1",
                "name": "Kiddo Alpha",
                "lifecycle": "active",
                "lifecycle_as_of": None,
                "classes": [{"session_id": "sess-sat", "title": "Sat Beginners"}],
                "matched": False,
            }
        ],
        "card_on_file": True,
        "registration": "registered",
        "money": {
            "balance_cents": 6000,
            "open_invoice_count": 1,
            "overdue_invoice_count": 1,
            "overdue_cents": 6000,
            "oldest_overdue_due_on": "2026-09-01",
            "last_failed_payment_at": None,
        },
        "matched_parent": False,
    }
    assert body["families"][1]["money"] is None


def test_filters_search_and_pagination(admin: TestClient) -> None:
    body = admin.get("/api/v2/admin/families", params={"scope": "left"}).json()
    assert [f["family_id"] for f in body["families"]] == ["u-bravo"]
    body = admin.get("/api/v2/admin/families", params={"class_id": "sess-sat"}).json()
    assert [f["family_id"] for f in body["families"]] == ["u-alpha"]
    body = admin.get("/api/v2/admin/families", params={"search": "kiddo"}).json()
    assert body["families"][0]["children"][0]["matched"] is True
    body = admin.get(
        "/api/v2/admin/families",
        params=[("stage", "active,left"), ("page_size", "1"), ("page", "2")],
    ).json()
    assert body["total"] == 2
    assert [f["family_id"] for f in body["families"]] == ["u-bravo"]


def test_unknown_stage_is_422(admin: TestClient) -> None:
    assert admin.get("/api/v2/admin/families", params={"stage": "frozen"}).status_code == 422
    assert admin.get("/api/v2/admin/families", params={"scope": "leads"}).status_code == 422
    assert admin.get("/api/v2/admin/families", params={"page_size": "500"}).status_code == 422


def test_primary_failure_is_503(admin: TestClient, services: FakeServices) -> None:
    services.index.error = FamilyIndexUnavailable("down")
    assert admin.get("/api/v2/admin/families").status_code == 503
    assert admin.get("/api/v2/admin/families/summary").status_code == 503


def test_summary_tiles_and_presets(admin: TestClient) -> None:
    body = admin.get("/api/v2/admin/families/summary").json()
    assert body["total_families"] == 2
    assert body["tiles"] == {"active": 1, "leaving": 0, "left": 1}
    assert body["counts_by_stage"]["active"] == 1
    assert len(body["counts_by_stage"]) == 8
    assert [p["id"] for p in body["presets"]] == ["active", "leaving", "left", "overdue", "no_card"]


def test_money_seam_hides_every_amount(
    services: FakeServices, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the #553 seam says no, nothing money-shaped leaves the server."""
    monkeypatch.setattr(family_index_routes, "can_view_family_money", lambda claims: False)
    with _client(("admin",), services) as client:
        body = client.get("/api/v2/admin/families", params={"sort": "balance"}).json()
        assert body["money_visible"] is False
        assert all(f["money"] is None for f in body["families"])
        assert [f["family_id"] for f in body["families"]] == ["u-alpha", "u-bravo"]
        overdue = client.get("/api/v2/admin/families", params={"overdue": "true"}).json()
        assert overdue["families"] == []
        summary = client.get("/api/v2/admin/families/summary").json()
        assert "overdue" not in [p["id"] for p in summary["presets"]]


@pytest.mark.parametrize("roles", [("coach",), ("parent",), ("owner",)])
def test_non_admin_personas_are_404(services: FakeServices, roles: tuple[str, ...]) -> None:
    with _client(roles, services) as client:
        assert client.get("/api/v2/admin/families").status_code == 404
        assert client.get("/api/v2/admin/families/summary").status_code == 404
    assert services.index.calls == []


def test_summary_is_not_read_as_a_parent_id(admin: TestClient) -> None:
    """``/families/summary`` must never fall through to ``/families/{parent_id}/…``."""
    assert admin.get("/api/v2/admin/families/summary").json()["total_families"] == 2
