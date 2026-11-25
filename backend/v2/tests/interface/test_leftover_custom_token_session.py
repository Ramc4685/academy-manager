"""LF4: a session left over from the deleted magic-link flow fails closed.

Its Firebase refresh token keeps minting ID tokens with
``sign_in_provider == "custom"`` until revoked. Through the real middleware and
the real ``LoadAuthClaims`` such a request must get a 401 the login surface
understands (sign in again), never a 500.
"""

from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.auth.middleware import TenancyMiddleware
from backend.v2.shared.http import register_exception_handlers
from backend.v2.tests.application.test_load_auth_claims import _build, _coach_user


def _app(*, email_verified: bool) -> FastAPI:
    coach = _coach_user().model_copy(update={"firebase_uid": "fb-coach"})
    loader = _build(
        users=[coach],
        token_claims={
            "uid": "fb-coach",
            "email": "coach@example.com",
            "email_verified": email_verified,
            "firebase": {"sign_in_provider": "custom"},
        },
    )

    async def _resolve(_request) -> str:
        return "academy-court"

    app = FastAPI()
    register_exception_handlers(app)
    app.add_middleware(TenancyMiddleware, load_auth_claims=loader.execute, resolve_tenant=_resolve)

    @app.get("/whoami")
    async def whoami(claims: AuthClaims = Depends(get_auth_claims)) -> dict[str, str]:
        return {"user_id": claims.user_id}

    return app


def test_leftover_custom_token_session_gets_401_not_500() -> None:
    for email_verified in (False, True):
        client = TestClient(_app(email_verified=email_verified))
        response = client.get("/whoami", headers={"Authorization": "Bearer stale-session"})

        assert response.status_code == 401
        error = response.json()["error"]
        assert error["code"] == "Auth.NotAuthenticated"
        assert error["details"] == {"reason": "Identity.InvalidToken"}
