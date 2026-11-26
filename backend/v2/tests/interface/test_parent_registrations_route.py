"""GET /parent/registrations returns only the caller's applications in the
caller's tenant (S02), driven through the real parent composition."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.composition.parent import compose_parent
from backend.v2.interfaces.parent.deps import get_parent_use_cases
from backend.v2.interfaces.parent.router import router as parent_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers
from backend.v2.shared.tenancy.context import tenant_scope


class _TenantScopeMiddleware:
    def __init__(self, app: Any, academy_id: str) -> None:
        self.app = app
        self.academy_id = academy_id

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        with tenant_scope(self.academy_id):
            await self.app(scope, receive, send)


def _doc(app_id: str, *, academy: str, parent: str, status: str, child: str) -> dict[str, Any]:
    now = datetime.now(UTC)
    return {
        "application_id": app_id,
        "academy_id": academy,
        "parent_user_id": parent,
        "parent_email": "new.parent@example.com",
        "status": status,
        "selected_session_id": "sess-1",
        "child_profile": {"first_name": child, "last_name": "Rivera"},
        "expires_at": now + timedelta(days=7),
        "created_at": now,
        "updated_at": now,
    }


@pytest.mark.asyncio
async def test_registrations_are_the_callers_own_in_the_callers_tenant() -> None:
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["parent-registrations-route"]
    await db["onboarding_applications"].insert_many(
        [
            _doc(
                "mine", academy="acad", parent="parent-1", status="PENDING_APPROVAL", child="Lucia"
            ),
            _doc("other-parent", academy="acad", parent="parent-2", status="DRAFT", child="Ben"),
            _doc("other-tenant", academy="acad-2", parent="parent-1", status="DRAFT", child="Eve"),
        ]
    )
    await db["sessions"].insert_one(
        {"session_id": "sess-1", "academy_id": "acad", "title": "Wednesday Clinic"}
    )
    parent = compose_parent(
        db,
        outbox=object(),  # type: ignore[arg-type]
        idempotency_store=object(),  # type: ignore[arg-type]
        stripe=object(),  # type: ignore[arg-type]
        academy_id="acad",
    )
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(parent_router, prefix="/api/v2")
    app.add_middleware(_TenantScopeMiddleware, academy_id="acad")
    app.dependency_overrides[get_auth_claims] = lambda: AuthClaims(
        user_id="parent-1",
        email="new.parent@example.com",
        academy_id="acad",
        roles=("parent",),  # type: ignore[arg-type]
    )
    app.dependency_overrides[get_parent_use_cases] = lambda: parent
    with TestClient(app) as client:
        res = client.get("/api/v2/parent/registrations")
    assert res.status_code == 200, res.text
    rows = res.json()["registrations"]
    assert [r["application_id"] for r in rows] == ["mine"]
    assert rows[0]["child_first_name"] == "Lucia"
    assert rows[0]["state"] == "waiting"
    assert rows[0]["session_title"] == "Wednesday Clinic"
