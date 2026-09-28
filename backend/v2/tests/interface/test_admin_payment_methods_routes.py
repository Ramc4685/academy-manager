"""Interface tests for ``/admin/academy/payment-methods`` (row 22).

``GET`` admits owner, admin and the billing staff tier (their record-payment
dialogs list these methods); ``PUT`` is owner only and 404s for anyone else.
Real use cases over in-memory stores, so wiring, the 422 shape, the audit
entry and the gates are exercised end to end.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.contexts.billing.application.use_cases.manual_payment_methods import (
    UpdateManualPaymentMethods,
)
from backend.v2.interfaces.admin.payment_methods_routes import get_admin_payment_methods
from backend.v2.interfaces.admin.router import router as admin_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers

ROUTE = "/api/v2/admin/academy/payment-methods"
ALL_SIX = ["cash", "check", "zelle", "venmo", "bank_transfer", "other"]


class _Store:
    """Per-academy lists, so a write for one tenant is visibly not another's."""

    def __init__(self) -> None:
        self.by_academy: dict[str, list[str]] = {}
        self.audit: list[Any] = []

    async def read(self, academy_id: str) -> list[str]:
        return list(self.by_academy.get(academy_id, ALL_SIX))

    async def write(self, academy_id: str, methods: list[str], *, actor_id: str) -> list[str]:
        self.by_academy[academy_id] = list(methods)
        return list(methods)

    async def append(self, entry: Any) -> None:
        self.audit.append(entry)


class _Fn:
    def __init__(self, fn: Any) -> None:
        self.execute = fn


@dataclass
class _Methods:
    read: Any
    write: Any


def _methods(store: _Store) -> _Methods:
    return _Methods(
        read=_Fn(store.read),
        write=UpdateManualPaymentMethods(
            reader=_Fn(store.read), writer=_Fn(store.write), audit=store
        ),
    )


def _claims(role: str, academy_id: str = "acad") -> AuthClaims:
    roles: tuple[str, ...] = ("admin", "owner") if role == "owner" else (role,)
    return AuthClaims(
        user_id=f"u-{role}",
        email=f"{role}@example.com",
        academy_id=academy_id,
        roles=roles,  # type: ignore[arg-type]
    )


def _client(role: str, store: _Store, academy_id: str = "acad") -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(admin_router, prefix="/api/v2")
    app.dependency_overrides[get_auth_claims] = lambda: _claims(role, academy_id)
    app.dependency_overrides[get_admin_payment_methods] = lambda: _methods(store)
    return TestClient(app)


def test_get_returns_all_six_by_default_for_admin_and_billing() -> None:
    for role in ("owner", "admin", "billing"):
        response = _client(role, _Store()).get(ROUTE)
        assert response.status_code == 200, (role, response.text)
        assert response.json() == {"manual_methods": ALL_SIX}


def test_get_wrong_persona_404() -> None:
    for role in ("coach", "parent", "front_desk"):
        assert _client(role, _Store()).get(ROUTE).status_code == 404, role


def test_put_saves_and_audits_for_the_owner() -> None:
    store = _Store()
    response = _client("owner", store).put(
        ROUTE, json={"manual_methods": ["zelle", "cash"], "reason": "no checks"}
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"manual_methods": ["cash", "zelle"]}
    assert store.by_academy == {"acad": ["cash", "zelle"]}
    assert [entry.action for entry in store.audit] == ["payment_methods_changed"]
    assert store.audit[0].actor_id == "u-owner"
    # Another academy still reads all six.
    assert _client("admin", store, academy_id="acad-other").get(ROUTE).json() == {
        "manual_methods": ALL_SIX
    }


def test_put_is_owner_only() -> None:
    for role in ("admin", "billing", "coach"):
        store = _Store()
        response = _client(role, store).put(ROUTE, json={"manual_methods": ["cash"]})
        assert response.status_code == 404, role
        assert store.by_academy == {}


def test_put_validation_422_names_the_field() -> None:
    for body in ({"manual_methods": []}, {"manual_methods": ["cash", "wire"]}):
        store = _Store()
        response = _client("owner", store).put(ROUTE, json=body)
        assert response.status_code == 422, response.text
        assert response.json()["detail"]["field"] == "manual_methods"
        assert store.by_academy == {}
        assert store.audit == []


def test_put_refuses_oversized_input_before_the_use_case() -> None:
    for body in ({"manual_methods": ["x" * 33]}, {"manual_methods": ["cash"] * 21}):
        store = _Store()
        assert _client("owner", store).put(ROUTE, json=body).status_code == 422
        assert store.by_academy == {}
