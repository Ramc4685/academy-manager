"""``/admin/ai/win-back-personalised`` (B6): owner-only read and write of the
standing approval; the write stores the owner's id as the approver."""

from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.interfaces.admin.ai_win_back_routes import router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers

ROUTE = "/api/v2/admin/ai/win-back-personalised"


class FakeSetting:
    def __init__(self) -> None:
        self.enabled = False
        self.by: str | None = None

    async def get(self) -> tuple[bool, str | None]:
        return self.enabled, self.by

    async def set(self, *, enabled: bool, user_id: str) -> bool:
        self.enabled, self.by = enabled, (user_id if enabled else None)
        return enabled


def _client(role: str, setting: FakeSetting) -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router, prefix="/api/v2/admin")
    app.state.ai_win_back = SimpleNamespace(setting=setting)
    roles: tuple[str, ...] = ("admin", "owner") if role == "owner" else (role,)
    app.dependency_overrides[get_auth_claims] = lambda: AuthClaims(
        user_id=f"u-{role}",
        email=f"{role}@example.com",
        academy_id="acad",
        roles=roles,  # type: ignore[arg-type]
    )
    return TestClient(app)


def test_owner_reads_the_default_off_and_turns_it_on_storing_their_id() -> None:
    setting = FakeSetting()
    client = _client("owner", setting)
    assert client.get(ROUTE).json() == {"enabled": False}
    response = client.put(ROUTE, json={"enabled": True})
    assert response.status_code == 200 and response.json() == {"enabled": True}
    assert (setting.enabled, setting.by) == (True, "u-owner")
    assert client.put(ROUTE, json={"enabled": False}).json() == {"enabled": False}
    assert (setting.enabled, setting.by) == (False, None)


def test_plain_admin_sees_neither_route() -> None:
    setting = FakeSetting()
    client = _client("admin", setting)
    assert client.get(ROUTE).status_code == 404
    assert client.put(ROUTE, json={"enabled": True}).status_code == 404
    assert setting.enabled is False


def test_coach_sees_neither_route() -> None:
    client = _client("coach", FakeSetting())
    assert client.get(ROUTE).status_code == 404
