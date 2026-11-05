"""Interface tests for the B1 AI curriculum routes: admin only, 404 for other
personas, the program's sport resolves through the lookup, and the AI
domain errors pass through the shared handler with their codes."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.contexts.ai.application.use_cases.draft_skill_ladder import (
    DraftSkillLadder,
    SkillLadderDraft,
)
from backend.v2.contexts.ai.application.use_cases.record_ai_call import RecordAiCall
from backend.v2.contexts.ai.domain.errors import AiMonthlyCapReached
from backend.v2.contexts.ai.domain.models import AiCallRecord
from backend.v2.contexts.ai.infrastructure.disabled_llm_port import DisabledLlmPort
from backend.v2.interfaces.admin.ai_curriculum_routes import get_ai_curriculum
from backend.v2.interfaces.admin.router import router as admin_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers

STATUS = "/api/v2/admin/ai/status"
DRAFT = "/api/v2/admin/curriculum/programs/prog-1/ladder-draft"
DRAFT_JSON = {
    "levels": [
        {
            "sequence": i,
            "name": f"Level {i}",
            "description": "",
            "skills": [
                {
                    "name": "Grip",
                    "description": "",
                    "scoring_type": "ATTEMPT_BASED",
                    "is_required": True,
                    "criteria": ["Relaxed grip"],
                },
                {
                    "name": "Serve",
                    "description": "",
                    "scoring_type": "COACH_APPROVAL",
                    "is_required": False,
                    "criteria": ["Legal serve"],
                },
            ],
        }
        for i in (1, 2)
    ]
}


class _Sport:
    async def sport_of(self, program_id: str) -> str | None:
        return "badminton" if program_id == "prog-1" else None


class _Drafter:
    prompt_version = "skill-ladder-v1"

    def __init__(self) -> None:
        self.calls: list[tuple[Any, str]] = []
        self.raise_: Exception | None = None

    async def execute(self, inp: Any, *, approver: str) -> SkillLadderDraft:
        self.calls.append((inp, approver))
        if self.raise_:
            raise self.raise_
        return SkillLadderDraft.model_validate(DRAFT_JSON)


class Caller:
    def __init__(self) -> None:
        self.be("u-admin", "admin")

    def be(self, user_id: str, *roles: str) -> None:
        self.claims = AuthClaims(
            user_id=user_id,
            email=f"{user_id}@example.test",
            academy_id="acad-a",
            roles=roles,  # type: ignore[arg-type]
        )


@pytest.fixture
def caller() -> Caller:
    return Caller()


@pytest.fixture
def services() -> SimpleNamespace:
    return SimpleNamespace(enabled=True, program_sport=_Sport(), draft_skill_ladder=_Drafter())


@pytest.fixture
def client(caller: Caller, services: SimpleNamespace) -> Iterator[TestClient]:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(admin_router, prefix="/api/v2")

    async def claims() -> AuthClaims:
        return caller.claims

    app.dependency_overrides[get_auth_claims] = claims
    app.dependency_overrides[get_ai_curriculum] = lambda: services
    with TestClient(app) as c:
        yield c


def test_admin_gets_the_draft_with_its_prompt_version(client: TestClient, services: Any) -> None:
    r = client.post(DRAFT, json={"age_band": "8-10", "level_count": 2, "notes": "fun"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["prompt_version"] == "skill-ladder-v1"
    assert [level["name"] for level in body["levels"]] == ["Level 1", "Level 2"]
    ((inp, approver),) = services.draft_skill_ladder.calls
    assert inp.model_dump() == {
        "sport": "badminton",
        "age_band": "8-10",
        "level_count": 2,
        "notes": "fun",
    }
    assert approver == "u-admin"


def test_status_reports_enabled(client: TestClient, services: Any) -> None:
    assert client.get(STATUS).json() == {"enabled": True}
    services.enabled = False
    assert client.get(STATUS).json() == {"enabled": False}


@pytest.mark.parametrize("roles", [("coach",), ("parent",)])
def test_other_personas_get_404(
    client: TestClient, caller: Caller, services: Any, roles: tuple[str, ...]
) -> None:
    caller.be("u-other", *roles)
    assert client.get(STATUS).status_code == 404
    assert client.post(DRAFT, json={"age_band": "8-10"}).status_code == 404
    assert services.draft_skill_ladder.calls == []


def test_unknown_program_is_404(client: TestClient, services: Any) -> None:
    r = client.post(
        "/api/v2/admin/curriculum/programs/nope/ladder-draft", json={"age_band": "8-10"}
    )
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "Curriculum.ProgramNotFound"
    assert services.draft_skill_ladder.calls == []


def test_body_is_validated(client: TestClient) -> None:
    assert client.post(DRAFT, json={"age_band": "8-10", "level_count": 9}).status_code == 422
    assert client.post(DRAFT, json={"age_band": "8-10", "student": "Kit"}).status_code == 422


def test_cap_reached_is_429_with_its_code(client: TestClient, services: Any) -> None:
    services.draft_skill_ladder.raise_ = AiMonthlyCapReached("cap", used=2, cap=2)
    r = client.post(DRAFT, json={"age_band": "8-10"})
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "Ai.MonthlyCapReached"


class _NoCalls:
    async def count_since(self, since: datetime) -> int:
        return 0

    async def record(self, call: AiCallRecord) -> None:
        raise AssertionError("nothing should be recorded when AI is off")


class _Cap:
    async def monthly_cap(self) -> int:
        return 200


def test_disabled_port_is_503_ai_disabled(client: TestClient, services: Any) -> None:
    services.draft_skill_ladder = DraftSkillLadder(
        llm=DisabledLlmPort(),
        record_ai_call=RecordAiCall(
            calls=_NoCalls(), cap_source=_Cap(), clock=lambda: datetime(2026, 11, 4, tzinfo=UTC)
        ),
    )
    r = client.post(DRAFT, json={"age_band": "8-10"})
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "Ai.Disabled"


def test_missing_state_is_503(caller: Caller) -> None:
    app = FastAPI()
    app.include_router(admin_router, prefix="/api/v2")

    async def claims() -> AuthClaims:
        return caller.claims

    app.dependency_overrides[get_auth_claims] = claims
    with TestClient(app) as c:
        assert c.get(STATUS).status_code == 503
