"""Interface tests for the roster-import copilot routes (Phase 2 slice B2):
persona gates, the body cap, the AI-off 503 and the owner-only sharing switch."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.composition.ai_import import AiImportComposition
from backend.v2.contexts.ai.application.use_cases.map_import_columns import MapImportColumns
from backend.v2.contexts.ai.application.use_cases.record_ai_call import RecordAiCall
from backend.v2.contexts.ai.domain.models import DEFAULT_MODEL, LlmResult
from backend.v2.contexts.ai.infrastructure.disabled_llm_port import DisabledLlmPort
from backend.v2.interfaces.admin.ai_import_routes import get_ai_import
from backend.v2.interfaces.admin.family_import_routes import MAX_BODY_BYTES
from backend.v2.interfaces.admin.router import router as admin_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers
from backend.v2.shared.http.rate_limit import _PATH_LIMIT_OVERRIDES
from backend.v2.shared.tenancy.context import _current as _tenant
from backend.v2.tests.fixtures.ai_counters import counters_at

A = "acad-a"
MAP = "/api/v2/admin/imports/families/map-columns"
SHARING = "/api/v2/admin/ai/import-sharing"
CSV = "Guardian,Child\nJane Doe,Sam Doe\n"
ANSWER = json.dumps(
    {
        "mappings": [
            {
                "target": "parent_name",
                "source_headers": ["Guardian"],
                "confidence": "high",
                "note": "",
            },
            {
                "target": "student_name",
                "source_headers": ["Child"],
                "confidence": "high",
                "note": "",
            },
        ],
        "unmapped_headers": [],
        "notes": "No contact column found.",
    }
)


class FakeLlm:
    async def complete(self, *, prompt_version: str, system: str, user: str, max_tokens: int):
        return LlmResult(
            text=ANSWER, input_tokens=1, output_tokens=1, cost_cents=1, model=DEFAULT_MODEL
        )


class FakeCalls:
    def __init__(self) -> None:
        self.recorded: list = []

    async def count_since(self, since: datetime) -> int:
        return 0

    async def record(self, call) -> None:
        self.recorded.append(call)


class FakeCap:
    async def monthly_cap(self) -> int:
        return 200


class FakeSharing:
    def __init__(self) -> None:
        self.value = False

    async def share_values(self) -> bool:
        return self.value

    async def set_share_values(self, value: bool) -> None:
        self.value = value


class Caller:
    def __init__(self) -> None:
        self.be("u-admin", "admin")

    def be(self, user_id: str, *roles: str) -> None:
        self.claims = AuthClaims(
            user_id=user_id,
            email=f"{user_id}@example.test",
            academy_id=A,
            roles=roles,  # type: ignore[arg-type]
        )


def _services(llm) -> AiImportComposition:
    sharing = FakeSharing()
    record = RecordAiCall(
        calls=FakeCalls(),
        counters=counters_at(),
        cap_source=FakeCap(),
        clock=lambda: datetime(2026, 11, 4, tzinfo=UTC),
    )
    return AiImportComposition(
        map_columns=MapImportColumns(llm=llm, record_ai_call=record, sharing=sharing),
        sharing=sharing,
    )


@pytest.fixture
def caller() -> Caller:
    return Caller()


@pytest.fixture
def services() -> AiImportComposition:
    return _services(FakeLlm())


@pytest.fixture
def client(caller: Caller, services: AiImportComposition) -> Iterator[TestClient]:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(admin_router, prefix="/api/v2")

    async def claims() -> AuthClaims:
        _tenant.set(A)
        return caller.claims

    app.dependency_overrides[get_auth_claims] = claims
    app.dependency_overrides[get_ai_import] = lambda: services
    with TestClient(app) as c:
        yield c


def test_admin_gets_the_draft_with_sample_mode_and_prompt_version(client: TestClient) -> None:
    response = client.post(MAP, json={"filename": "roster.csv", "csv": CSV})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["sample_mode"] == "masked"
    assert body["prompt_version"] == "roster-import-map-v1"
    assert [m["target"] for m in body["mappings"]] == ["parent_name", "student_name"]
    assert body["notes"] == "No contact column found."


@pytest.mark.parametrize("roles", [("coach",), ("parent",), ("billing",), ("front_desk",)])
def test_non_admins_get_the_wrong_persona_404(
    client: TestClient, caller: Caller, roles: tuple[str, ...]
) -> None:
    caller.be("u-other", *roles)
    assert client.post(MAP, json={"csv": CSV}).status_code == 404


def test_oversized_body_is_refused_before_parsing(client: TestClient) -> None:
    big = b'{"csv": "' + b"a" * MAX_BODY_BYTES + b'"}'
    assert client.post(MAP, content=big).status_code == 413
    assert client.post(MAP, json={"csv": CSV, "academy_id": "acad-b"}).status_code == 422


def test_duplicate_headers_are_a_422(client: TestClient) -> None:
    response = client.post(MAP, json={"csv": "Jane Doe,jane doe\nJane,Sam\n"})
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "Ai.ImportSampleRejected"
    assert "Jane" not in response.text


def test_disabled_port_is_a_503_with_the_ai_disabled_code(caller: Caller) -> None:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(admin_router, prefix="/api/v2")

    async def claims() -> AuthClaims:
        _tenant.set(A)
        return caller.claims

    app.dependency_overrides[get_auth_claims] = claims
    app.dependency_overrides[get_ai_import] = lambda: _services(DisabledLlmPort())
    with TestClient(app) as c:
        response = c.post(MAP, json={"csv": CSV})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "Ai.Disabled"


def test_sharing_switch_is_owner_only(client: TestClient, caller: Caller) -> None:
    assert client.get(SHARING).status_code == 404
    assert client.put(SHARING, json={"share_values": True}).status_code == 404
    caller.be("u-owner", "owner", "admin")
    assert client.get(SHARING).json() == {"share_values": False}
    assert client.put(SHARING, json={"share_values": True}).json() == {"share_values": True}
    assert client.get(SHARING).json() == {"share_values": True}


def test_the_route_is_rate_limited() -> None:
    assert ("POST", MAP) in _PATH_LIMIT_OVERRIDES
