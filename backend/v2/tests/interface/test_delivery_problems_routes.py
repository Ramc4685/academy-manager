"""Admin Delivery problems route (L11 item 3): admin-only and read-only."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.contexts.communications.application.use_cases.delivery_problems import (
    DeliveryProblems,
    SuppressedMember,
)
from backend.v2.interfaces.admin.comms_routes import router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers


class _Get:
    async def execute(self, *, limit: int = 100) -> DeliveryProblems:
        return DeliveryProblems(
            suppressed=[
                SuppressedMember(
                    user_id="p1",
                    email="bounce@example.test",
                    reason="hard_bounce",
                    bounce_subtype="General",
                    last_seen_at=datetime(2026, 11, 1, tzinfo=UTC),
                ),
                SuppressedMember(
                    user_id="s1",
                    email="shared@example.test",
                    reason=None,
                    bounce_subtype=None,
                    last_seen_at=None,
                ),
            ],
            failed=[],
        )


def _client(roles: tuple[str, ...]) -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router, prefix="/api/v2/admin")
    app.state.delivery_problems = _Get()
    app.dependency_overrides[get_auth_claims] = lambda: AuthClaims(
        user_id="u1",
        email="u1@example.test",
        academy_id="acad",
        membership_id="m1",
        roles=roles,
    )
    return TestClient(app)


def test_admin_sees_the_academys_problems() -> None:
    res = _client(("admin",)).get("/api/v2/admin/comms/delivery-problems")
    assert res.status_code == 200
    body = res.json()
    assert body["suppressed"][0]["email"] == "bounce@example.test"
    assert body["suppressed"][1]["reason"] is None
    assert body["suppressed"][1]["last_seen_at"] is None
    assert body["failed"] == []


def test_a_parent_cannot_read_it() -> None:
    res = _client(("parent",)).get("/api/v2/admin/comms/delivery-problems")
    assert res.status_code in (401, 403, 404)


def test_there_is_no_academy_side_clear() -> None:
    res = _client(("admin",)).post(
        "/api/v2/admin/comms/delivery-problems/release", json={"email": "x@example.test"}
    )
    assert res.status_code in (404, 405)
