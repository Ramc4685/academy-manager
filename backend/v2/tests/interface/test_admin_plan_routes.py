"""Interface tests for the admin Plan routes (Phase 2 A2): owner only in both
directions, 409s surface as plain errors, and the checkout URL is returned."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.contexts.platform.billing.application.use_cases.plan_checkout import (
    GrowthPlanUnavailable,
    PlanOverview,
)
from backend.v2.contexts.platform.billing.domain.models import (
    PlanLimits,
    PlatformPlan,
    TenantSubscription,
)
from backend.v2.interfaces.admin.plan_routes import get_admin_plan
from backend.v2.interfaces.admin.router import router as admin_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers

NOW = datetime(2026, 11, 4, tzinfo=UTC)
GROWTH = PlatformPlan(
    plan_id="plan_growth",
    code="growth",
    display_name="Growth",
    monthly_price_cents=9900,
    limits=PlanLimits(),
    stripe_price_id="price_1",
    features=frozenset({"ai"}),
    created_at=NOW,
    updated_at=NOW,
)


class _Overview:
    def __init__(self, overview: PlanOverview) -> None:
        self.overview = overview

    async def execute(self, academy_id: str) -> PlanOverview:
        assert academy_id == "acad"
        return self.overview


class _Checkout:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.commands: list[Any] = []

    async def execute(self, command: Any) -> str:
        self.commands.append(command)
        if self.error:
            raise self.error
        return "https://checkout.stripe.test/cs_1"


class FakeAdminPlan:
    def __init__(self, overview: PlanOverview, error: Exception | None = None) -> None:
        self.get_overview = _Overview(overview)
        self.start_checkout = _Checkout(error)

    async def academy_frontend_base_url(self, academy_id: str) -> str:
        return "https://blno.courtmastr.test/"

    async def academy_name(self, academy_id: str) -> str:
        return "BLNO"


def _claims(role: str) -> AuthClaims:
    roles: tuple[str, ...] = ("admin", "owner") if role == "owner" else (role,)
    return AuthClaims(
        user_id=f"u-{role}",
        email=f"{role}@example.com",
        academy_id="acad",
        roles=roles,  # type: ignore[arg-type]
    )


def _app(role: str, services: FakeAdminPlan) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(admin_router, prefix="/api/v2")
    app.dependency_overrides[get_auth_claims] = lambda: _claims(role)
    app.dependency_overrides[get_admin_plan] = lambda: services
    return app


def _free() -> PlanOverview:
    return PlanOverview(subscription=None, plan=None, growth=GROWTH, checkout_available=True)


ROUTES = [("GET", "/api/v2/admin/billing/plan"), ("POST", "/api/v2/admin/billing/plan/checkout")]


@pytest.mark.parametrize(("method", "path"), ROUTES)
def test_owner_reaches_the_plan_routes(method: str, path: str) -> None:
    with TestClient(_app("owner", FakeAdminPlan(_free()))) as client:
        assert client.request(method, path).status_code == 200


@pytest.mark.parametrize("role", ["admin", "coach", "parent"])
@pytest.mark.parametrize(("method", "path"), ROUTES)
def test_nobody_but_the_owner_reaches_the_plan_routes(role: str, method: str, path: str) -> None:
    with TestClient(_app(role, FakeAdminPlan(_free()))) as client:
        assert client.request(method, path).status_code == 404


def test_get_plan_free_academy_shows_the_growth_offer() -> None:
    with TestClient(_app("owner", FakeAdminPlan(_free()))) as client:
        body = client.get("/api/v2/admin/billing/plan").json()
    assert body == {
        "plan": None,
        "subscription": None,
        "growth": {
            "code": "growth",
            "display_name": "Growth",
            "monthly_price_cents": 9900,
            "features": ["ai"],
        },
        "checkout_available": True,
    }


def test_get_plan_with_an_active_subscription() -> None:
    sub = TenantSubscription(
        subscription_id="s1",
        academy_id="acad",
        plan_id="plan_growth",
        billing_status="active",
        cancel_at_period_end=True,
        current_period_end=NOW,
        created_at=NOW,
        updated_at=NOW,
    )
    overview = PlanOverview(subscription=sub, plan=GROWTH, growth=GROWTH, checkout_available=True)
    with TestClient(_app("owner", FakeAdminPlan(overview))) as client:
        body = client.get("/api/v2/admin/billing/plan").json()
    assert body["plan"]["code"] == "growth"
    assert body["subscription"] == {
        "billing_status": "active",
        "cancel_at_period_end": True,
        "current_period_end": "2026-11-04T00:00:00Z",
    }


def test_checkout_returns_the_url_and_links_back_to_settings() -> None:
    services = FakeAdminPlan(_free())
    with TestClient(_app("owner", services)) as client:
        response = client.post("/api/v2/admin/billing/plan/checkout")
    assert response.json() == {"url": "https://checkout.stripe.test/cs_1"}
    command = services.start_checkout.commands[0]
    assert command.academy_id == "acad"
    assert command.academy_name == "BLNO"
    assert command.actor_user_id == "u-owner"
    assert command.actor_email == "owner@example.com"
    assert command.success_url == (
        "https://blno.courtmastr.test/admin/settings?panel=integrations&plan=upgraded"
    )
    assert command.cancel_url == (
        "https://blno.courtmastr.test/admin/settings?panel=integrations&plan=cancelled"
    )


def test_checkout_409_when_growth_is_not_priced() -> None:
    services = FakeAdminPlan(_free(), error=GrowthPlanUnavailable("not priced"))
    with TestClient(_app("owner", services)) as client:
        response = client.post("/api/v2/admin/billing/plan/checkout")
    assert response.status_code == 409
    assert "not priced" in response.text
