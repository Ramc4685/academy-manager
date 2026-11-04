"""Interface tests for the platform application-fee routes (roadmap L9b).

Only a platform admin may read or change an academy's application fee; an
academy admin (or platform support) gets 404, per the security matrix.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.contexts.billing.application.use_cases.application_fee import (
    ApplicationFeeResult,
    SetApplicationFeeCommand,
)
from backend.v2.contexts.billing.domain.errors import ApplicationFeeAcademyNotFound
from backend.v2.interfaces.platform.application_fee_routes import router as fee_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers


class _Get:
    def __init__(self, fees: dict[str, int]) -> None:
        self.fees = fees

    async def execute(self, academy_id: str) -> ApplicationFeeResult:
        if academy_id not in self.fees:
            raise ApplicationFeeAcademyNotFound("academy not found", academy_id=academy_id)
        return ApplicationFeeResult(
            academy_id=academy_id, application_fee_bps=self.fees[academy_id]
        )


class _Set:
    def __init__(self, fees: dict[str, int]) -> None:
        self.fees = fees
        self.commands: list[SetApplicationFeeCommand] = []

    async def execute(self, cmd: SetApplicationFeeCommand) -> ApplicationFeeResult:
        if cmd.academy_id not in self.fees:
            raise ApplicationFeeAcademyNotFound("academy not found", academy_id=cmd.academy_id)
        self.commands.append(cmd)
        self.fees[cmd.academy_id] = cmd.application_fee_bps
        return ApplicationFeeResult(
            academy_id=cmd.academy_id, application_fee_bps=cmd.application_fee_bps
        )


class _Wiring:
    def __init__(self) -> None:
        fees = {"acad-1": 0}
        self.get = _Get(fees)
        self.set = _Set(fees)


def _platform_admin() -> AuthClaims:
    return AuthClaims(
        user_id="platform-admin",
        email="ops@example.com",
        academy_id="platform-control",
        platform_roles=("platform_admin",),
    )


def _platform_support() -> AuthClaims:
    return AuthClaims(
        user_id="platform-support",
        email="support@example.com",
        academy_id="platform-control",
        platform_roles=("platform_support",),
    )


def _academy_admin() -> AuthClaims:
    return AuthClaims(
        user_id="academy-admin",
        email="admin@example.com",
        academy_id="acad-1",
        membership_id="m-1",
        roles=("admin", "owner"),
    )


def _client(claims: AuthClaims, wiring: _Wiring) -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(fee_router, prefix="/api/v2")
    app.state.platform_application_fee = wiring

    async def _override() -> AuthClaims:
        return claims

    app.dependency_overrides[get_auth_claims] = _override
    return TestClient(app)


URL = "/api/v2/platform/academies/acad-1/application-fee"


@pytest.fixture()
def wiring() -> _Wiring:
    return _Wiring()


@pytest.fixture()
def platform_client(wiring: _Wiring) -> Iterator[TestClient]:
    with _client(_platform_admin(), wiring) as client:
        yield client


def test_platform_admin_reads_default_zero(platform_client: TestClient) -> None:
    response = platform_client.get(URL)

    assert response.status_code == 200
    assert response.json() == {
        "academy_id": "acad-1",
        "application_fee_bps": 0,
        "max_application_fee_bps": 1000,
    }


def test_platform_admin_sets_the_fee_with_actor(
    platform_client: TestClient, wiring: _Wiring
) -> None:
    response = platform_client.put(URL, json={"application_fee_bps": 250, "reason": "agreement"})

    assert response.status_code == 200
    assert response.json()["application_fee_bps"] == 250
    cmd = wiring.set.commands[0]
    assert (cmd.academy_id, cmd.application_fee_bps, cmd.actor_id, cmd.reason) == (
        "acad-1",
        250,
        "platform-admin",
        "agreement",
    )
    assert platform_client.get(URL).json()["application_fee_bps"] == 250


@pytest.mark.parametrize("bps", [-1, 1001, "abc"])
def test_out_of_range_fee_is_rejected(
    platform_client: TestClient, wiring: _Wiring, bps: object
) -> None:
    response = platform_client.put(URL, json={"application_fee_bps": bps})

    assert response.status_code == 422
    assert wiring.set.commands == []


def test_unknown_academy_is_404(platform_client: TestClient, wiring: _Wiring) -> None:
    url = "/api/v2/platform/academies/acad-missing/application-fee"

    assert platform_client.get(url).status_code == 404
    assert platform_client.put(url, json={"application_fee_bps": 100}).status_code == 404
    assert wiring.set.commands == []


@pytest.mark.parametrize("claims", [_academy_admin(), _platform_support()])
def test_non_platform_admins_cannot_read_or_set_the_fee(
    wiring: _Wiring, claims: AuthClaims
) -> None:
    with _client(claims, wiring) as client:
        assert client.get(URL).status_code == 404
        assert client.put(URL, json={"application_fee_bps": 500}).status_code == 404

    assert wiring.set.commands == []
    assert wiring.get.fees["acad-1"] == 0
