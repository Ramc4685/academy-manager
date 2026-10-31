"""``/admin/pricing`` routes (Settings overhaul Phase 3 PR 11b).

Owner only, reads included. A plain admin gets a 403 with a sentence the page
can show; anyone without an admin role gets the usual 404. The use cases are
faked: their rules are pinned in ``tests/contract/test_pricing_page_mongo.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.contexts.billing.application.use_cases.plan_price_changes import (
    PlanPriceChangePreview,
    PlanPriceChangeView,
    ScheduledClassFee,
)
from backend.v2.contexts.billing.application.use_cases.pricing_page import (
    LinkMatchingClassesResult,
    PricingClassRow,
    PricingOverview,
    PricingPlanRow,
)
from backend.v2.contexts.billing.domain.errors import (
    PlanPriceMismatch,
    PriceChangeMonthNotAllowed,
)
from backend.v2.contexts.billing.domain.session_type import SessionType
from backend.v2.interfaces.admin.owner_gate import OWNER_ONLY_ROUTE_PATHS, PRICING_FORBIDDEN
from backend.v2.interfaces.admin.router import router as admin_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers

_ADMIN = "/api/v2/admin"
NOW = datetime(2026, 9, 29, tzinfo=UTC)

ROUTES: tuple[tuple[str, str, dict[str, Any] | None], ...] = (
    ("GET", "/pricing", None),
    ("PUT", "/pricing/classes/sess-1/plan", {"plan_id": "group"}),
    ("POST", "/pricing/link-matching-classes", None),
    (
        "GET",
        "/pricing/price-changes/preview?plan_id=group&new_price_cents=13000",
        None,
    ),
    (
        "POST",
        "/pricing/price-changes",
        {"plan_id": "group", "new_price_cents": 13_000, "effective_period": "2026-11"},
    ),
    ("DELETE", "/pricing/price-changes/ppc-1", None),
)


class _Fake:
    def __init__(self) -> None:
        self.calls: list[Any] = []

    async def overview(self) -> PricingOverview:
        plan = SessionType(
            session_type_id="group",
            academy_id="acad",
            name="Group class",
            price_cents=12_000,
            created_at=NOW,
            updated_at=NOW,
        )
        return PricingOverview(
            plans=[PricingPlanRow(plan=plan, linked_classes=1)],
            classes=[self._row("group")],
            saved_overrides=[],
            auto_linkable=0,
        )

    @staticmethod
    def _row(plan_id: str | None) -> PricingClassRow:
        return PricingClassRow(
            session_id="sess-1",
            title="Juniors",
            charged_cents=12_000,
            fee_set=True,
            students=3,
            plan_id=plan_id,
            matching_plan_ids=["group"],
            stale_link=False,
        )

    async def set_link(self, cmd) -> PricingClassRow:
        self.calls.append(cmd)
        if cmd.plan_id == "pricey":
            raise PlanPriceMismatch("A class can only use a plan with the same price.")
        return self._row(cmd.plan_id)

    async def link_matching(self, *, academy_id: str, actor_id: str):
        self.calls.append((academy_id, actor_id))
        return LinkMatchingClassesResult(linked=2, no_match=1, several_matches=0, already_decided=3)

    async def preview(self, *, plan_id: str, new_price_cents: int, effective_period=None):
        self.calls.append(("preview", plan_id, new_price_cents, effective_period))
        if effective_period == "2026-09":
            raise PriceChangeMonthNotAllowed("Pick a later month.", earliest="2026-11")
        return PlanPriceChangePreview(
            plan_id=plan_id,
            plan_name="Group class",
            old_cents=12_000,
            new_cents=new_price_cents,
            effective_period=effective_period or "2026-11",
            earliest_period="2026-11",
            classes=[],
            not_affected=[],
            total_classes=0,
            total_students=0,
            old_monthly_cents=0,
            new_monthly_cents=0,
        )

    async def schedule(self, cmd) -> PlanPriceChangeView:
        self.calls.append(cmd)
        return PlanPriceChangeView(
            change_id="ppc-1",
            plan_id=cmd.plan_id,
            plan_name="Group class",
            old_cents=12_000,
            new_cents=cmd.new_price_cents,
            effective_period=cmd.effective_period,
            session_ids=["sess-1"],
            status="scheduled",
            created_by=cmd.actor_id,
        )

    async def cancel(self, *, academy_id: str, change_id: str, actor_id: str) -> None:
        self.calls.append(("cancel", academy_id, change_id, actor_id))

    async def scheduled_fees(self) -> list[ScheduledClassFee]:
        return [
            ScheduledClassFee(
                session_id="sess-1",
                change_id="ppc-1",
                plan_id="group",
                new_cents=13_000,
                effective_period="2026-11",
            )
        ]


def _client(roles: tuple[str, ...]) -> tuple[TestClient, _Fake]:
    fake = _Fake()
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(admin_router, prefix="/api/v2")
    claims = AuthClaims(
        user_id="u-1",
        email="u@example.com",
        academy_id="acad",
        roles=roles,  # type: ignore[arg-type]
    )
    app.dependency_overrides[get_auth_claims] = lambda: claims
    app.state.admin_pricing = SimpleNamespace(
        overview=SimpleNamespace(execute=fake.overview),
        set_link=SimpleNamespace(execute=fake.set_link),
        link_matching=SimpleNamespace(execute=fake.link_matching),
        preview_price_change=SimpleNamespace(execute=fake.preview),
        schedule_price_change=SimpleNamespace(execute=fake.schedule),
        cancel_price_change=SimpleNamespace(execute=fake.cancel),
        scheduled_class_fees=SimpleNamespace(execute=fake.scheduled_fees),
    )
    return TestClient(app), fake


def _template(path: str) -> str:
    path = path.split("?")[0].replace("sess-1", "{session_id}").replace("ppc-1", "{change_id}")
    return f"{_ADMIN}{path}"


@pytest.mark.parametrize(("method", "path", "_body"), ROUTES)
def test_every_pricing_route_is_declared_owner_only(method, path, _body) -> None:
    assert (method, _template(path)) in OWNER_ONLY_ROUTE_PATHS


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
def test_plain_admin_gets_403_on_every_pricing_route(method, path, body) -> None:
    client, fake = _client(("admin",))
    response = client.request(method, f"{_ADMIN}{path}", json=body)
    assert response.status_code == 403, response.text
    assert response.json()["detail"] == PRICING_FORBIDDEN
    assert fake.calls == []


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
@pytest.mark.parametrize("role", ["coach", "parent", "billing", "front_desk"])
def test_non_admins_get_404(method, path, body, role) -> None:
    client, fake = _client((role,))
    response = client.request(method, f"{_ADMIN}{path}", json=body)
    assert response.status_code == 404, response.text
    assert fake.calls == []


def test_owner_reads_the_overview() -> None:
    client, _ = _client(("admin", "owner"))
    response = client.get(f"{_ADMIN}/pricing")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["plans"][0] == {
        "plan_id": "group",
        "name": "Group class",
        "description": None,
        "price_cents": 12_000,
        "plan_type": "monthly",
        "is_active": True,
        "linked_classes": 1,
        "updated_at": "2026-09-29T00:00:00Z",
        "scheduled_change_id": None,
        "scheduled_cents": None,
        "scheduled_from": None,
    }
    assert body["classes"][0]["charged_cents"] == 12_000
    assert body["saved_overrides"] == []


def test_owner_links_a_class_with_claims_tenant_and_actor() -> None:
    client, fake = _client(("admin", "owner"))
    response = client.put(f"{_ADMIN}/pricing/classes/sess-1/plan", json={"plan_id": "group"})
    assert response.status_code == 200, response.text
    assert response.json()["plan_id"] == "group"
    cmd = fake.calls[0]
    assert (cmd.academy_id, cmd.session_id, cmd.plan_id, cmd.actor_id) == (
        "acad",
        "sess-1",
        "group",
        "u-1",
    )


def test_owner_marks_a_class_custom() -> None:
    client, fake = _client(("owner",))
    response = client.put(f"{_ADMIN}/pricing/classes/sess-1/plan", json={"plan_id": None})
    assert response.status_code == 200, response.text
    assert response.json()["plan_id"] is None
    assert fake.calls[0].plan_id is None


def test_mismatched_plan_price_is_409() -> None:
    client, _ = _client(("owner",))
    response = client.put(f"{_ADMIN}/pricing/classes/sess-1/plan", json={"plan_id": "pricey"})
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "Billing.PlanPriceMismatch"


def test_owner_links_matching_classes() -> None:
    client, fake = _client(("owner",))
    response = client.post(f"{_ADMIN}/pricing/link-matching-classes")
    assert response.status_code == 200, response.text
    assert response.json() == {
        "linked": 2,
        "no_match": 1,
        "several_matches": 0,
        "already_decided": 3,
    }
    assert fake.calls == [("acad", "u-1")]


def test_plan_type_other_than_monthly_is_rejected_on_the_price_list() -> None:
    """``per_session`` plans are a later phase: the write refuses them."""
    client, _ = _client(("owner",))
    client.app.state.admin = SimpleNamespace()  # type: ignore[attr-defined]
    response = client.post(
        f"{_ADMIN}/session-types",
        json={"name": "Drop-in", "price_cents": 3_000, "plan_type": "per_session"},
    )
    assert response.status_code == 422, response.text


# ------------------------------------------------ change a plan price (PR 26)


def test_owner_previews_a_price_change() -> None:
    client, fake = _client(("owner",))
    response = client.get(
        f"{_ADMIN}/pricing/price-changes/preview",
        params={"plan_id": "group", "new_price_cents": 13_000, "effective_period": "2026-12"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["effective_period"] == "2026-12"
    assert fake.calls == [("preview", "group", 13_000, "2026-12")]


def test_past_month_is_422_from_the_use_case() -> None:
    client, _ = _client(("owner",))
    response = client.get(
        f"{_ADMIN}/pricing/price-changes/preview",
        params={"plan_id": "group", "new_price_cents": 13_000, "effective_period": "2026-09"},
    )
    assert response.status_code == 422, response.text


def test_malformed_month_is_422_before_the_use_case() -> None:
    client, fake = _client(("owner",))
    response = client.post(
        f"{_ADMIN}/pricing/price-changes",
        json={"plan_id": "group", "new_price_cents": 13_000, "effective_period": "Nov"},
    )
    assert response.status_code == 422, response.text
    assert fake.calls == []


def test_owner_schedules_with_claims_tenant_and_actor() -> None:
    client, fake = _client(("owner",))
    response = client.post(
        f"{_ADMIN}/pricing/price-changes",
        json={"plan_id": "group", "new_price_cents": 13_000, "effective_period": "2026-11"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["change_id"] == "ppc-1"
    cmd = fake.calls[0]
    assert (cmd.academy_id, cmd.actor_id, cmd.effective_period) == ("acad", "u-1", "2026-11")


def test_owner_cancels_a_scheduled_change() -> None:
    client, fake = _client(("owner",))
    response = client.delete(f"{_ADMIN}/pricing/price-changes/ppc-1")
    assert response.status_code == 204, response.text
    assert fake.calls == [("cancel", "acad", "ppc-1", "u-1")]


@pytest.mark.parametrize("roles", [("admin",), ("admin", "owner")])
def test_scheduled_class_fees_are_readable_by_any_admin(roles) -> None:
    client, _ = _client(roles)
    response = client.get(f"{_ADMIN}/pricing/scheduled-class-fees")
    assert response.status_code == 200, response.text
    assert response.json()[0]["new_cents"] == 13_000
    assert ("GET", f"{_ADMIN}/pricing/scheduled-class-fees") not in OWNER_ONLY_ROUTE_PATHS


def test_scheduled_class_fees_are_404_for_a_parent() -> None:
    client, _ = _client(("parent",))
    response = client.get(f"{_ADMIN}/pricing/scheduled-class-fees")
    assert response.status_code == 404, response.text
