"""Interface tests for the Billing Health routes (spec 2026-09-07 §5.2).

Every route here is owner-only: Stripe plumbing is governance, the same tier as
Reports and Payouts. An admin who could open this page yesterday gets a 404
today, so each route is checked for owner 200 AND admin/coach/parent 404 — a
persona regression on a money-governance surface should never be silent.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.contexts.billing.application.ports import StripeResourceNotFound
from backend.v2.interfaces.admin.billing_health_routes import get_admin_billing_health
from backend.v2.interfaces.admin.router import router as admin_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers

_READINESS: dict[str, Any] = {
    "connected_account": {
        "configured": True,
        "status": "active",
        "charges_enabled": True,
        "payouts_enabled": True,
        "ready_for_charges": True,
        "account_id_masked": "acct...6f21",
    },
    "allow_platform_charge_fallback": False,
    "payments_possible": True,
    "funds_route_to_academy": True,
    "webhook_events": {"quarantined": 0, "failed": 0},
    "autopay_disable_failures": {"count": 0, "rows": [], "truncated": False},
    "health": {"state": "ok", "headline": "Stripe is healthy", "reasons": []},
}

_RUN: dict[str, Any] = {
    "run_id": "run-1",
    "started_at": "2026-09-07T10:00:00+00:00",
    "finished_at": "2026-09-07T10:00:20+00:00",
    "scanned": 12,
    "repaired": 1,
    "skipped": 11,
    "quarantined": 0,
    "failed": 0,
    "errors": [],
    "notes": [],
}


@dataclass
class FakeBillingHealth:
    readiness: dict[str, Any] = field(default_factory=lambda: dict(_READINESS))
    runs: list[dict[str, Any]] = field(default_factory=lambda: [dict(_RUN)])
    webhook_rows: list[dict[str, Any]] = field(default_factory=list)
    reconcile_error: Exception | None = None
    replay_error: Exception | None = None
    report_error: Exception | None = None
    confirm_error: Exception | None = None
    calls: dict[str, Any] = field(default_factory=dict)

    async def get_connect_readiness(self) -> dict[str, Any]:
        return self.readiness

    async def list_reconciliation_runs(self) -> list[dict[str, Any]]:
        return self.runs

    async def run_reconciliation(self) -> dict[str, Any]:
        if self.reconcile_error is not None:
            raise self.reconcile_error
        return dict(_RUN)

    async def list_billing_webhook_events(
        self, *, status: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        self.calls["webhooks"] = {"status": status, "limit": limit}
        return self.webhook_rows

    async def replay_webhook_event(self, event_id: str) -> bool:
        self.calls["replay"] = event_id
        if self.replay_error is not None:
            raise self.replay_error
        return True

    async def get_billing_reconciliation_report(self, **kwargs: Any) -> dict[str, Any]:
        self.calls["report"] = kwargs
        if self.report_error is not None:
            raise self.report_error
        return {
            "result": "MATCH",
            "stripe_invoice_id": kwargs.get("stripe_invoice_id"),
            "payment_intent_id": kwargs.get("payment_intent_id"),
            "stripe_customer_id": "cus_1",
            "local_invoice_id": "inv-1",
            "ledger_payment_id": "pay-1",
            "payment_allocation_id": "alloc-1",
            "mismatches": [],
            "manual_review_candidates": [],
            "checked_at": "2026-09-07T10:00:00+00:00",
        }

    async def confirm_legacy_match(self, **kwargs: Any) -> dict[str, Any]:
        self.calls["confirm"] = kwargs
        if self.confirm_error is not None:
            raise self.confirm_error
        return {
            "invoice_id": kwargs["invoice_id"],
            "payment_id": f"legacy-match-{kwargs['stripe_charge_id']}",
            "invoice_status": "paid",
            "balance_due_cents": 0,
        }


def _claims(role: str) -> AuthClaims:
    roles: tuple[str, ...] = ("admin", "owner") if role == "owner" else (role,)
    return AuthClaims(
        user_id=f"u-{role}",
        email=f"{role}@example.com",
        academy_id="acad",
        roles=roles,  # type: ignore[arg-type]
    )


def _make_app(role: str, services: FakeBillingHealth) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(admin_router, prefix="/api/v2")
    app.dependency_overrides[get_auth_claims] = lambda: _claims(role)
    app.dependency_overrides[get_admin_billing_health] = lambda: services
    return app


@pytest.fixture
def services() -> FakeBillingHealth:
    return FakeBillingHealth()


@pytest.fixture
def owner(services: FakeBillingHealth) -> Iterator[TestClient]:
    with TestClient(_make_app("owner", services)) as client:
        yield client


# --------------------------------------------------------------------------- #
# Owner-only, in both directions
# --------------------------------------------------------------------------- #
ROUTES: list[tuple[str, str, dict[str, Any] | None]] = [
    ("GET", "/api/v2/admin/billing/connect-readiness", None),
    ("GET", "/api/v2/admin/billing/webhooks?status=quarantined&limit=50", None),
    ("POST", "/api/v2/admin/billing/webhook-events/evt_1/replay", None),
    ("GET", "/api/v2/admin/billing/reconciliation-runs", None),
    ("POST", "/api/v2/admin/billing/reconcile-now", None),
    ("GET", "/api/v2/admin/billing/reconciliation?payment_intent_id=pi_1", None),
    (
        "POST",
        "/api/v2/admin/billing/legacy-match/confirm",
        {"invoice_id": "inv-1", "stripe_charge_id": "ch_1", "amount_cents": 1000},
    ),
]


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
def test_owner_reaches_every_billing_health_route(
    owner: TestClient, method: str, path: str, body: dict[str, Any] | None
) -> None:
    response = owner.request(method, path, json=body)
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("role", ["admin", "coach", "parent"])
@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
def test_nobody_but_the_owner_reaches_billing_health(
    services: FakeBillingHealth,
    role: str,
    method: str,
    path: str,
    body: dict[str, Any] | None,
) -> None:
    """Including a plain admin: the access change this spec makes deliberately."""
    with TestClient(_make_app(role, services)) as client:
        response = client.request(method, path, json=body)
    assert response.status_code == 404, response.text


def test_the_legacy_match_queue_route_is_gone() -> None:
    """The list recomputed "every open invoice with no allocation" per load and
    fanned out a Stripe call per row; only the explicit confirm survives."""
    paths = {getattr(r, "path", "") for r in admin_router.routes}
    assert "/billing/legacy-match-queue" not in paths
    assert not any("legacy-match-queue" in p for p in paths)


# --------------------------------------------------------------------------- #
# Behaviour
# --------------------------------------------------------------------------- #
def test_connect_readiness_carries_the_health_verdict(
    owner: TestClient, services: FakeBillingHealth
) -> None:
    services.readiness = {
        **_READINESS,
        "payments_possible": False,
        "funds_route_to_academy": False,
        "webhook_events": {"quarantined": 0, "failed": 0},
        "health": {
            "state": "blocked",
            "headline": "Parents cannot pay right now",
            "reasons": [{"code": "connect_not_ready", "detail": "No Stripe account."}],
        },
    }

    body = owner.get("/api/v2/admin/billing/connect-readiness").json()

    assert body["payments_possible"] is False
    assert body["health"]["state"] == "blocked"
    assert body["health"]["headline"] == "Parents cannot pay right now"
    assert body["health"]["reasons"][0]["code"] == "connect_not_ready"


def test_connect_readiness_carries_the_switch_off_failures(
    owner: TestClient, services: FakeBillingHealth
) -> None:
    services.readiness = {
        **_READINESS,
        "autopay_disable_failures": {
            "count": 2,
            "rows": [
                {
                    "invoice_id": "inv-9",
                    "parent_id": "parent-9",
                    "error": "rate_limited",
                    "failed_at": "2026-09-07T09:00:00+00:00",
                }
            ],
            "truncated": True,
        },
    }

    body = owner.get("/api/v2/admin/billing/connect-readiness").json()

    assert body["autopay_disable_failures"]["count"] == 2
    assert body["autopay_disable_failures"]["truncated"] is True
    assert body["autopay_disable_failures"]["rows"][0]["parent_id"] == "parent-9"


def test_connect_readiness_503s_when_not_composed(services: FakeBillingHealth) -> None:
    services.get_connect_readiness = None  # type: ignore[assignment]
    with TestClient(_make_app("owner", services)) as client:
        assert client.get("/api/v2/admin/billing/connect-readiness").status_code == 503


def test_webhook_list_passes_the_status_filter_and_caps_the_limit(
    owner: TestClient, services: FakeBillingHealth
) -> None:
    owner.get("/api/v2/admin/billing/webhooks?status=quarantined&limit=5000")
    assert services.calls["webhooks"] == {"status": "quarantined", "limit": 100}


def test_replay_of_an_unknown_event_is_404(owner: TestClient, services: FakeBillingHealth) -> None:
    services.replay_error = ValueError("quarantined event not found")
    response = owner.post("/api/v2/admin/billing/webhook-events/evt_missing/replay")
    assert response.status_code == 404


def test_reconcile_now_surfaces_an_unconfigured_stripe_as_503(
    owner: TestClient, services: FakeBillingHealth
) -> None:
    services.reconcile_error = RuntimeError("Stripe reconciliation not configured")
    response = owner.post("/api/v2/admin/billing/reconcile-now")
    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]


def test_reconciliation_lookup_needs_an_id(owner: TestClient) -> None:
    assert owner.get("/api/v2/admin/billing/reconciliation").status_code == 422


def test_reconciliation_lookup_hides_the_provider_error(
    owner: TestClient, services: FakeBillingHealth
) -> None:
    services.report_error = StripeResourceNotFound("No such invoice: in_secret_internal_id")
    response = owner.get("/api/v2/admin/billing/reconciliation?stripe_invoice_id=in_1")
    assert response.status_code == 404
    assert "in_secret_internal_id" not in response.text


def test_confirm_posts_the_charge_and_records_the_actor(
    owner: TestClient, services: FakeBillingHealth
) -> None:
    response = owner.post(
        "/api/v2/admin/billing/legacy-match/confirm",
        json={
            "invoice_id": "inv-1",
            "stripe_charge_id": "ch_1",
            "amount_cents": 7000,
            "stripe_payment_intent_id": "pi_1",
            "paid_at": "2026-06-28T09:00:00+00:00",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["invoice_status"] == "paid"
    assert services.calls["confirm"]["amount_cents"] == 7000
    assert services.calls["confirm"]["stripe_payment_intent_id"] == "pi_1"
    assert services.calls["confirm"]["recorded_by"] == "u-owner"


def test_confirm_renders_a_refusal_as_400(owner: TestClient, services: FakeBillingHealth) -> None:
    """Not payable / above the balance — both inline errors on the form."""
    services.confirm_error = ValueError("amount_cents 9000 exceeds balance_due_cents 7000")
    response = owner.post(
        "/api/v2/admin/billing/legacy-match/confirm",
        json={"invoice_id": "inv-1", "stripe_charge_id": "ch_1", "amount_cents": 9000},
    )
    assert response.status_code == 400
    assert "exceeds" in response.json()["detail"]


def test_confirm_refuses_a_non_positive_amount(owner: TestClient) -> None:
    response = owner.post(
        "/api/v2/admin/billing/legacy-match/confirm",
        json={"invoice_id": "inv-1", "stripe_charge_id": "ch_1", "amount_cents": 0},
    )
    assert response.status_code == 422
