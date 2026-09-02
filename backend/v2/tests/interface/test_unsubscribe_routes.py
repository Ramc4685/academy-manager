"""Public unsubscribe endpoints (#555).

The token is the entire authority here — no login — so these tests pin the
three properties that make that safe:

* a **GET** to the confirm path is 405. E-mail security scanners and
  link-preview bots issue GET prefetches; a GET that mutated preferences would
  let a corporate mail scanner unsubscribe families automatically.
* a forged or tampered token is a flat 401 that reveals nothing.
* a token minted under one academy cannot act under another.

They mount only the unsubscribe router over a real Mongo-backed repository, so
the routing/validation surface is exercised without the full app stack.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.v2.contexts.communications.application.unsubscribe_token import (
    mint_unsubscribe_token,
)
from backend.v2.contexts.communications.application.use_cases.get_email_preferences import (
    GetEmailPreferences,
)
from backend.v2.contexts.communications.application.use_cases.resolve_unsubscribe_token import (
    ResolveUnsubscribeToken,
)
from backend.v2.contexts.communications.application.use_cases.set_email_preferences import (
    SetEmailPreferences,
)
from backend.v2.contexts.communications.infrastructure.mongo_email_preference_repo import (
    MongoEmailPreferenceRepository,
)
from backend.v2.interfaces.unsubscribe_routes import router as unsubscribe_router

SECRET = "test-unsubscribe-secret"
ACADEMY = "acad-a"


def _build_app(
    db: Any,
    *,
    secret: str | None = SECRET,
    academy_id: str | None = ACADEMY,
    saas_mode: bool = True,
) -> FastAPI:
    app = FastAPI()
    app.state.saas_mode = saas_mode

    @app.middleware("http")
    async def _resolve_tenant(request: Request, call_next):  # type: ignore[no-untyped-def]
        # Stands in for the real host-based tenant middleware. `academy_id=None`
        # is the real SaaS behaviour for a host TenantResolver cannot map.
        request.state.resolved_academy_id = academy_id
        return await call_next(request)

    repo = MongoEmailPreferenceRepository(db)
    app.state.get_email_preferences = GetEmailPreferences(preferences=repo)
    app.state.set_email_preferences = SetEmailPreferences(preferences=repo)
    app.state.resolve_unsubscribe_token = ResolveUnsubscribeToken(secret=secret)
    app.include_router(unsubscribe_router, prefix="/api/v2")
    return app


@pytest.fixture
def db() -> Any:
    mongomock_motor = pytest.importorskip("mongomock_motor")
    return mongomock_motor.AsyncMongoMockClient()["unsubscribe-routes"]


@pytest.fixture
def client(db: Any) -> Any:
    with TestClient(_build_app(db)) as c:
        yield c


def _token(user_id: str = "u-1", academy_id: str = ACADEMY) -> str:
    token = mint_unsubscribe_token(academy_id=academy_id, user_id=user_id, secret=SECRET)
    assert token is not None
    return token


def test_preview_then_confirm_flips_the_flags(client: Any, db: Any) -> None:
    token = _token()

    before = client.post("/api/v2/unsubscribe/preview", json={"token": token})
    assert before.status_code == 200
    assert before.json() == {
        "campaigns_opted_out": False,
        "digests_opted_out": False,
        "notifications_opted_out": False,
    }

    confirmed = client.post(
        "/api/v2/unsubscribe/confirm",
        json={"token": token, "campaigns": True, "digests": True},
    )
    assert confirmed.status_code == 200
    assert confirmed.json() == {
        "campaigns_opted_out": True,
        "digests_opted_out": True,
        # Omitted from the confirm body: "leave unchanged", not "re-subscribe" (#612).
        "notifications_opted_out": False,
    }

    after = client.post("/api/v2/unsubscribe/preview", json={"token": token})
    assert after.json() == {
        "campaigns_opted_out": True,
        "digests_opted_out": True,
        # Omitted from the confirm body: "leave unchanged", not "re-subscribe" (#612).
        "notifications_opted_out": False,
    }


def test_confirm_is_idempotent(client: Any) -> None:
    token = _token()
    body = {"token": token, "campaigns": True, "digests": False}
    first = client.post("/api/v2/unsubscribe/confirm", json=body)
    second = client.post("/api/v2/unsubscribe/confirm", json=body)
    assert first.json() == second.json()


def test_a_get_to_the_confirm_path_is_rejected(client: Any) -> None:
    """Bot-prefetch guard: the mutation must never be reachable by GET."""
    assert client.get("/api/v2/unsubscribe/confirm").status_code == 405
    assert client.get("/api/v2/unsubscribe/preview").status_code == 405


def test_a_forged_token_is_a_flat_401(client: Any) -> None:
    forged = mint_unsubscribe_token(academy_id=ACADEMY, user_id="u-1", secret="wrong-secret")
    assert forged is not None
    response = client.post(
        "/api/v2/unsubscribe/confirm", json={"token": forged, "campaigns": True, "digests": True}
    )
    assert response.status_code == 401
    assert "u-1" not in response.text


def test_a_tampered_token_is_a_401(client: Any) -> None:
    token = _token()
    tampered = token[:-2] + ("aa" if not token.endswith("aa") else "bb")
    assert client.post("/api/v2/unsubscribe/preview", json={"token": tampered}).status_code == 401


def test_a_token_from_another_academy_cannot_act_here(client: Any, db: Any) -> None:
    """One recipient must not be able to unsubscribe another tenant's family."""
    other = _token(user_id="u-1", academy_id="acad-b")
    response = client.post(
        "/api/v2/unsubscribe/confirm",
        json={"token": other, "campaigns": True, "digests": True},
    )
    assert response.status_code == 401


def test_a_transactional_key_is_rejected_not_ignored(client: Any) -> None:
    """Nobody may be led to believe they switched off their own invoices."""
    response = client.post(
        "/api/v2/unsubscribe/confirm",
        json={"token": _token(), "campaigns": True, "digests": True, "transactional": True},
    )
    assert response.status_code == 422


def test_with_no_secret_configured_the_endpoints_404(db: Any) -> None:
    """Fail closed: no secret ⇒ no link was ever minted, so no surface."""
    with TestClient(_build_app(db, secret=None)) as client:
        assert (
            client.post("/api/v2/unsubscribe/preview", json={"token": "u1.a.b"}).status_code == 404
        )


def test_an_unresolvable_host_is_refused_rather_than_waved_through(db: Any) -> None:
    """The `expected_academy_id` binding must not be a branch that never runs.

    In SaaS mode `TenantResolver` returns nothing for a host that is not an
    academy subdomain, and the middleware then leaves `resolved_academy_id`
    unset. If that were accepted, the cross-tenant check below it would be
    skipped on every such request — a guard that exists only in the tests that
    inject a tenant. `magic_link_routes` already refuses this case; so does
    this one.
    """
    with TestClient(_build_app(db, academy_id=None)) as client:
        response = client.post("/api/v2/unsubscribe/preview", json={"token": _token()})

    assert response.status_code == 400
    assert "host" in response.json()["detail"]


def test_a_single_academy_deployment_still_works_without_a_resolved_tenant(db: Any) -> None:
    """Non-SaaS single-academy deployments have no subdomain to resolve, and the
    token's own MAC still binds the academy — so the strictness above is scoped
    to SaaS mode rather than breaking the launch topology."""
    with TestClient(_build_app(db, academy_id=None, saas_mode=False)) as client:
        response = client.post("/api/v2/unsubscribe/preview", json={"token": _token()})

    assert response.status_code == 200
    assert response.json() == {
        "campaigns_opted_out": False,
        "digests_opted_out": False,
        "notifications_opted_out": False,
    }


def test_notifications_round_trip_and_omission_preserves_them(client: Any) -> None:
    """Both halves of the #612 deploy trap, in one flow.

    The model forbids unknown keys, so ``notifications`` could not be made
    required without 422-ing every request from the deployed unsubscribe page;
    and it could not default to ``False`` without re-subscribing whoever saved
    from that page. It is optional and means "leave unchanged".
    """
    token = _token(user_id="coach-9")

    first = client.post(
        "/api/v2/unsubscribe/confirm",
        json={"token": token, "campaigns": False, "digests": False, "notifications": True},
    )
    assert first.status_code == 200
    assert first.json()["notifications_opted_out"] is True

    # An older client saves campaigns only, omitting the new field.
    second = client.post(
        "/api/v2/unsubscribe/confirm",
        json={"token": token, "campaigns": True, "digests": False},
    )
    assert second.status_code == 200
    assert second.json() == {
        "campaigns_opted_out": True,
        "digests_opted_out": False,
        "notifications_opted_out": True,
    }


def test_transactional_is_still_rejected_outright(client: Any) -> None:
    """Adding a third switchable category must not open a fourth."""
    response = client.post(
        "/api/v2/unsubscribe/confirm",
        json={
            "token": _token(),
            "campaigns": True,
            "digests": True,
            "notifications": True,
            "transactional": True,
        },
    )
    assert response.status_code == 422
