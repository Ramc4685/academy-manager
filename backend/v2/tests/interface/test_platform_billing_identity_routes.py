"""Interface tests for the platform billing-identity routes (Settings overhaul P1 PR 2).

``/platform/academies/{id}/billing-identity`` shows and sets an academy's
invoice prefix. Only a platform admin may use it; an academy admin (or
platform support) gets 404, like every platform route. The use cases own the
rules (format, uniqueness, lock); this checks the HTTP mapping.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.contexts.billing.application.use_cases.invoice_prefix import (
    InvoicePrefixResult,
    SetInvoicePrefixCommand,
)
from backend.v2.contexts.billing.domain.errors import (
    InvoicePrefixAcademyNotFound,
    InvoicePrefixLocked,
    InvoicePrefixTaken,
)
from backend.v2.contexts.billing.domain.invoice_prefix import normalize_invoice_prefix
from backend.v2.interfaces.platform.billing_identity_routes import router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers


class _State:
    def __init__(self) -> None:
        self.prefixes: dict[str, str | None] = {"acad-1": None, "acad-blno": "BLNO"}
        self.locked = {"acad-blno"}
        self.commands: list[SetInvoicePrefixCommand] = []


class _Get:
    def __init__(self, state: _State) -> None:
        self.state = state

    async def execute(self, academy_id: str) -> InvoicePrefixResult:
        if academy_id not in self.state.prefixes:
            raise InvoicePrefixAcademyNotFound("academy not found", academy_id=academy_id)
        return InvoicePrefixResult(
            academy_id=academy_id,
            invoice_prefix=self.state.prefixes[academy_id],
            locked=academy_id in self.state.locked,
        )


class _Set:
    def __init__(self, state: _State) -> None:
        self.state = state

    async def execute(self, cmd: SetInvoicePrefixCommand) -> InvoicePrefixResult:
        if cmd.academy_id not in self.state.prefixes:
            raise InvoicePrefixAcademyNotFound("academy not found", academy_id=cmd.academy_id)
        prefix = normalize_invoice_prefix(cmd.invoice_prefix)
        if cmd.academy_id in self.state.locked:
            raise InvoicePrefixLocked("locked", academy_id=cmd.academy_id)
        if prefix in {p for a, p in self.state.prefixes.items() if a != cmd.academy_id}:
            raise InvoicePrefixTaken("taken", invoice_prefix=prefix)
        self.state.commands.append(cmd)
        self.state.prefixes[cmd.academy_id] = prefix
        return InvoicePrefixResult(academy_id=cmd.academy_id, invoice_prefix=prefix, locked=False)


class _Wiring:
    def __init__(self) -> None:
        self.state = _State()
        self.get = _Get(self.state)
        self.set = _Set(self.state)


def _claims(**kwargs: object) -> AuthClaims:
    return AuthClaims(**kwargs)  # type: ignore[arg-type]


PLATFORM_ADMIN = _claims(
    user_id="platform-admin",
    email="ops@example.com",
    academy_id="platform-control",
    platform_roles=("platform_admin",),
)
PLATFORM_SUPPORT = _claims(
    user_id="platform-support",
    email="support@example.com",
    academy_id="platform-control",
    platform_roles=("platform_support",),
)
ACADEMY_OWNER = _claims(
    user_id="academy-admin",
    email="admin@example.com",
    academy_id="acad-1",
    membership_id="m-1",
    roles=("admin", "owner"),
)


def _client(claims: AuthClaims, wiring: _Wiring) -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router, prefix="/api/v2")
    app.state.platform_billing_identity = wiring

    async def _override() -> AuthClaims:
        return claims

    app.dependency_overrides[get_auth_claims] = _override
    return TestClient(app)


def _url(academy_id: str = "acad-1") -> str:
    return f"/api/v2/platform/academies/{academy_id}/billing-identity"


@pytest.fixture()
def wiring() -> _Wiring:
    return _Wiring()


@pytest.fixture()
def client(wiring: _Wiring) -> Iterator[TestClient]:
    with _client(PLATFORM_ADMIN, wiring) as c:
        yield c


def test_reads_prefix_and_lock(client: TestClient) -> None:
    assert client.get(_url("acad-blno")).json() == {
        "academy_id": "acad-blno",
        "invoice_prefix": "BLNO",
        "locked": True,
    }
    assert client.get(_url()).json() == {
        "academy_id": "acad-1",
        "invoice_prefix": None,
        "locked": False,
    }


def test_sets_the_prefix_with_actor_and_reason(client: TestClient, wiring: _Wiring) -> None:
    response = client.put(_url(), json={"invoice_prefix": "ace", "reason": "go-live"})

    assert response.status_code == 200
    assert response.json() == {"academy_id": "acad-1", "invoice_prefix": "ACE", "locked": False}
    [cmd] = wiring.state.commands
    assert (cmd.academy_id, cmd.invoice_prefix, cmd.actor_id, cmd.reason) == (
        "acad-1",
        "ace",
        "platform-admin",
        "go-live",
    )


def test_locked_prefix_is_409(client: TestClient) -> None:
    response = client.put(_url("acad-blno"), json={"invoice_prefix": "BLN2"})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "Billing.InvoicePrefixLocked"


def test_taken_prefix_is_409(client: TestClient) -> None:
    response = client.put(_url(), json={"invoice_prefix": "BLNO"})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "Billing.InvoicePrefixTaken"


@pytest.mark.parametrize("prefix", ["B", "TOOLONG1", "1ACE", "AC-E"])
def test_invalid_prefix_is_422(client: TestClient, wiring: _Wiring, prefix: str) -> None:
    assert client.put(_url(), json={"invoice_prefix": prefix}).status_code == 422
    assert wiring.state.commands == []


def test_unknown_academy_is_404(client: TestClient) -> None:
    assert client.get(_url("nope")).status_code == 404
    assert client.put(_url("nope"), json={"invoice_prefix": "ACE"}).status_code == 404


@pytest.mark.parametrize("claims", [ACADEMY_OWNER, PLATFORM_SUPPORT])
def test_non_platform_admins_get_404(wiring: _Wiring, claims: AuthClaims) -> None:
    with _client(claims, wiring) as c:
        assert c.get(_url()).status_code == 404
        assert c.put(_url(), json={"invoice_prefix": "ACE"}).status_code == 404
    assert wiring.state.commands == []
