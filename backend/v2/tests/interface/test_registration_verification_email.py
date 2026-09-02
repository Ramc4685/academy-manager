"""Interface tests for ``POST /register/parent/verification-email``.

Mirrors ``test_registration.py``. The route is public (bearer token only, no
Mongo authorization row), so its status mapping and its refusal to leak internal
error text are part of the security surface, not cosmetics.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.contexts.identity.domain.errors import (
    InvalidToken,
    LoginInviteSendFailed,
    VerificationEmailThrottled,
)
from backend.v2.interfaces.registration_routes import router as registration_router
from backend.v2.shared.http import register_exception_handlers
from backend.v2.shared.http.rate_limit import _PUBLIC_WRITE_PATHS
from backend.v2.tests._route_paths import route_paths

ROUTE = "/api/v2/register/parent/verification-email"


class FakeSendVerificationEmail:
    def __init__(self, raises: Exception | None = None) -> None:
        self._raises = raises
        self.calls: list[tuple[str, str]] = []

    async def execute(self, id_token: str, *, academy_id: str) -> None:
        self.calls.append((id_token, academy_id))
        if self._raises is not None:
            raise self._raises


def _app(
    *, saas_mode: bool = False, raises: Exception | None = None
) -> tuple[FastAPI, FakeSendVerificationEmail]:
    app = FastAPI()
    register_exception_handlers(app)
    fake = FakeSendVerificationEmail(raises=raises)
    app.state.send_registration_verification_email = fake
    app.state.saas_mode = saas_mode
    app.state.default_academy_id = "academy-a"
    app.include_router(registration_router, prefix="/api/v2")
    return app, fake


def test_returns_204_and_forwards_the_bearer_token() -> None:
    app, fake = _app()
    with TestClient(app) as client:
        response = client.post(ROUTE, headers={"Authorization": "Bearer firebase-token"})

    assert response.status_code == 204
    assert fake.calls == [("firebase-token", "academy-a")]


def test_requires_a_bearer_token() -> None:
    app, fake = _app()
    with TestClient(app) as client:
        response = client.post(ROUTE)

    assert response.status_code == 401
    assert fake.calls == []


def test_the_address_comes_from_the_token_not_the_request_body() -> None:
    """A body-supplied address would aim our mailer at arbitrary victims.

    The route hands the use case the raw token and nothing else, so a body that
    names someone else cannot influence who gets mailed.
    """
    app, fake = _app()
    with TestClient(app) as client:
        response = client.post(
            ROUTE,
            headers={"Authorization": "Bearer firebase-token"},
            json={"email": "victim@example.com"},
        )

    assert response.status_code == 204
    assert fake.calls == [("firebase-token", "academy-a")]


def test_invalid_token_maps_to_401() -> None:
    app, _ = _app(raises=InvalidToken("token missing email"))
    with TestClient(app) as client:
        response = client.post(ROUTE, headers={"Authorization": "Bearer firebase-token"})

    assert response.status_code == 401


def test_the_401_does_not_leak_the_underlying_token_error() -> None:
    """``InvalidToken`` wraps whatever the verifier raised.

    For a Firebase transport failure that is the raw exception text — a
    ``Max retries exceeded`` string naming internal hosts — and this caller is
    unauthenticated. The detail must be the fixed string, with the cause logged.
    """
    leaky = "HTTPSConnectionPool(host='www.googleapis.com', port=443): Max retries exceeded"
    app, _ = _app(raises=InvalidToken(leaky))
    with TestClient(app) as client:
        response = client.post(ROUTE, headers={"Authorization": "Bearer firebase-token"})

    assert response.status_code == 401
    assert response.json()["detail"] == "Not authenticated"
    assert "googleapis" not in response.text


def test_throttled_address_maps_to_429() -> None:
    app, _ = _app(raises=VerificationEmailThrottled("try again in a few minutes"))
    with TestClient(app) as client:
        response = client.post(ROUTE, headers={"Authorization": "Bearer firebase-token"})

    assert response.status_code == 429
    assert "try again in a few minutes" in response.json()["detail"]


def test_send_failure_maps_to_502_without_leaking_the_underlying_error(
    caplog: object,
) -> None:
    """The caller is unauthenticated; the Firebase/Mongo error text is not theirs.

    It still has to reach the operator, so it is logged rather than dropped.
    """
    secret = "pymongo ServerSelectionTimeout: internal-mongo-7.flycast:27017"
    app, _ = _app(raises=LoginInviteSendFailed(secret))
    with caplog.at_level(logging.ERROR):  # type: ignore[attr-defined]
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.post(ROUTE, headers={"Authorization": "Bearer firebase-token"})

    assert response.status_code == 502
    body = response.text
    assert secret not in body
    assert "internal-mongo-7.flycast" not in body
    assert response.json()["detail"] == (
        "Could not send the verification email. Please try again shortly."
    )
    assert secret in caplog.text  # type: ignore[attr-defined]


def test_saas_mode_400_when_the_tenant_is_unresolved() -> None:
    app, fake = _app(saas_mode=True)
    with TestClient(app) as client:
        response = client.post(ROUTE, headers={"Authorization": "Bearer firebase-token"})

    assert response.status_code == 400
    assert fake.calls == []


def test_saas_mode_forwards_the_resolved_tenant() -> None:
    app, fake = _app(saas_mode=True)

    @app.middleware("http")
    async def _inject_resolved_tenant(request, call_next):  # type: ignore[no-untyped-def]
        request.state.resolved_academy_id = "acad_acme"
        return await call_next(request)

    with TestClient(app) as client:
        response = client.post(ROUTE, headers={"Authorization": "Bearer firebase-token"})

    assert response.status_code == 204
    assert fake.calls == [("firebase-token", "acad_acme")]


def test_the_rate_limited_path_matches_the_mounted_route() -> None:
    """The IP rate limit is keyed on an exact (method, path) pair.

    A prefix change or a typo in ``_PUBLIC_WRITE_PATHS`` silently leaves this
    public, unauthenticated, email-sending endpoint unlimited, so the string is
    checked against the router's real mounted path rather than trusted.
    """
    app, _ = _app()
    assert ROUTE in route_paths(app)
    assert ("POST", ROUTE) in _PUBLIC_WRITE_PATHS
