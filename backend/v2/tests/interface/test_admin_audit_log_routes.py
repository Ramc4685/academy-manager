"""Interface tests for ``GET /admin/audit-logs`` (S39).

The merged read is covered by the mongomock tests in
``tests/unit/test_admin_audit_log_merged.py``; here it is a fake that records
its arguments, so the gate, the query params and the page shape are pinned.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.interfaces.admin.router import router as admin_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers


class _FakeAuditLog:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[dict[str, Any]] = []
        self.fail = fail

    async def list_page(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if self.fail:
            raise ValueError("bad cursor")
        return {
            "logs": [
                {
                    "audit_id": "b4",
                    "source": "billing_audit_log",
                    "actor_id": "u-owner",
                    "actor_type": "owner",
                    "actor_role": "owner",
                    "actor_name": "Olive Owner",
                    "action": "manual_payment_recorded",
                    "action_label": "Payment recorded by hand",
                    "entity_type": "payment",
                    "entity_id": "pay-1",
                    "created_at": datetime(2026, 11, 20, 15, 4, tzinfo=UTC),
                }
            ],
            "next_cursor": "2026-11-20T15:04:00+00:00|billing_audit_log|b4",
        }


def _client(roles: tuple[str, ...], audit_log: _FakeAuditLog) -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(admin_router, prefix="/api/v2")
    claims = AuthClaims(user_id="u-1", email="u@example.com", academy_id="acad", roles=roles)  # type: ignore[arg-type]
    app.dependency_overrides[get_auth_claims] = lambda: claims
    app.state.admin_audit_log = audit_log
    return TestClient(app)


def test_owner_reads_a_page_with_labels_and_a_cursor() -> None:
    fake = _FakeAuditLog()
    r = _client(("owner",), fake).get(
        "/api/v2/admin/audit-logs", params={"actor_type": "owner", "limit": 25, "cursor": "c1"}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["logs"][0]["action_label"] == "Payment recorded by hand"
    assert body["logs"][0]["source"] == "billing_audit_log"
    assert body["next_cursor"].endswith("|b4")
    assert fake.calls == [{"actor_type": "owner", "limit": 25, "cursor": "c1"}]


def test_admin_without_owner_is_refused() -> None:
    fake = _FakeAuditLog()
    r = _client(("admin",), fake).get("/api/v2/admin/audit-logs")
    assert r.status_code == 404
    assert fake.calls == []


def test_a_bad_cursor_is_a_422_not_a_500() -> None:
    r = _client(("owner",), _FakeAuditLog(fail=True)).get(
        "/api/v2/admin/audit-logs", params={"cursor": "nope"}
    )
    assert r.status_code == 422


def test_limit_is_capped() -> None:
    r = _client(("owner",), _FakeAuditLog()).get("/api/v2/admin/audit-logs", params={"limit": 500})
    assert r.status_code == 422
