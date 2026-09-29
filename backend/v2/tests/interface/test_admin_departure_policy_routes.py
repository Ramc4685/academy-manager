"""Interface tests for ``/admin/enrollment/departure-policy`` (the Holds card).

``drop_default_outcome`` moved to Settings -> Billing rules (Settings
overhaul Phase 3 PR 10), same pattern PR #1002 used for the cancellation
fee/notice: this route still accepts the field from an old client, but a
*changed* value 422s and points at Billing rules; an unchanged resubmit
passes and writes nothing for that field.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from backend.v2.contexts.enrollment.application.use_cases.departure_policies import (
    GetEnrollmentDeparturePolicy,
    UpdateEnrollmentDeparturePolicy,
)
from backend.v2.interfaces.admin.departure_policy_routes import router as departure_policy_router
from backend.v2.interfaces.admin.deps import AdminUseCases, get_admin_use_cases
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers

ROUTE = "/api/v2/admin/enrollment/departure-policy"


class _Policy(BaseModel):
    max_hold_days: int = 60
    hold_reclaim_policy: str = "longest_held"
    drop_default_outcome: str = "no_credit_mid_month"
    delete_enrollment_requires_owner: bool = True


class _FakeRepo:
    def __init__(self) -> None:
        self.current = _Policy()

    async def get_or_default(self) -> _Policy:
        return self.current

    async def save(self, policy: _Policy) -> None:
        self.current = policy


def _claims(role: str) -> AuthClaims:
    roles: tuple[str, ...] = ("admin", "owner") if role == "owner" else (role,)
    return AuthClaims(
        user_id=f"u-{role}",
        email=f"{role}@example.com",
        academy_id="acad",
        roles=roles,  # type: ignore[arg-type]
    )


def _client(role: str, repo: _FakeRepo) -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(departure_policy_router, prefix="/api/v2/admin")
    # AdminUseCases has ~70 fields, most required; the route only ever touches
    # these two, so build a bare instance rather than filling in the rest.
    use_cases = object.__new__(AdminUseCases)
    use_cases.departure_policy = GetEnrollmentDeparturePolicy(policies=repo)  # type: ignore[arg-type]
    use_cases.update_departure_policy = UpdateEnrollmentDeparturePolicy(  # type: ignore[attr-defined]
        policies=repo  # type: ignore[arg-type]
    )
    app.dependency_overrides[get_auth_claims] = lambda: _claims(role)
    app.dependency_overrides[get_admin_use_cases] = lambda: use_cases
    return TestClient(app)


def _body(**overrides: Any) -> dict[str, Any]:
    body = {
        "max_hold_days": 60,
        "hold_reclaim_policy": "longest_held",
        "delete_enrollment_requires_owner": True,
    }
    body.update(overrides)
    return body


def test_put_saves_the_holds_fields_without_drop_default_outcome() -> None:
    repo = _FakeRepo()
    response = _client("owner", repo).put(ROUTE, json=_body(max_hold_days=30))

    assert response.status_code == 200, response.text
    assert repo.current.max_hold_days == 30
    # Untouched: the Holds route never writes this field any more.
    assert repo.current.drop_default_outcome == "no_credit_mid_month"


def test_put_accepts_an_unchanged_drop_default_outcome() -> None:
    """An old client that still sends the field is not broken by the move."""
    repo = _FakeRepo()
    response = _client("owner", repo).put(
        ROUTE, json=_body(drop_default_outcome="no_credit_mid_month")
    )

    assert response.status_code == 200, response.text
    assert repo.current.drop_default_outcome == "no_credit_mid_month"


def test_put_rejects_a_changed_drop_default_outcome() -> None:
    repo = _FakeRepo()
    response = _client("owner", repo).put(
        ROUTE, json=_body(drop_default_outcome="credit_mid_month")
    )

    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert detail["field"] == "drop_default_outcome"
    assert "Billing rules" in detail["message"]
    # Nothing was written, not even the other fields sent alongside it.
    assert repo.current == _Policy()


def test_put_is_owner_only() -> None:
    repo = _FakeRepo()
    response = _client("admin", repo).put(ROUTE, json=_body())
    assert response.status_code == 404
