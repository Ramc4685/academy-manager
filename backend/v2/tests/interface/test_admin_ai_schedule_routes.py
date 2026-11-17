"""Month dates AI helper: strict parsing, what the model sees, the admin gate
and the AI-off 503."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, date, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.contexts.ai.application.use_cases.record_ai_call import RecordAiCall
from backend.v2.contexts.ai.application.use_cases.suggest_no_class_dates import (
    SuggestNoClassDates,
    parse_draft,
    user_message,
)
from backend.v2.contexts.ai.domain.errors import AiProviderError
from backend.v2.contexts.ai.domain.models import DEFAULT_MODEL, LlmResult
from backend.v2.contexts.ai.infrastructure.disabled_llm_port import DisabledLlmPort
from backend.v2.interfaces.admin.ai_schedule_routes import get_ai_schedule
from backend.v2.interfaces.admin.router import router as admin_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers
from backend.v2.shared.http.rate_limit import _PATH_LIMIT_OVERRIDES
from backend.v2.shared.tenancy.context import _current as _tenant
from backend.v2.tests.fixtures.ai_counters import counters_at

A = "acad-a"
URL = "/api/v2/admin/schedule/suggest-no-class-dates"
DATES = [date(2026, 12, 1), date(2026, 12, 22), date(2026, 12, 29)]
LEASE = "Gym closed Dec 21 - Jan 2 for winter break."
ANSWER = json.dumps(
    {
        "no_class": [
            {"date": "2026-12-22", "reason": "Gym closed for winter break"},
            {"date": "2026-12-29", "reason": "Gym closed for winter break"},
        ],
        "notes": "",
    }
)


class FakeLlm:
    def __init__(self, text: str = ANSWER) -> None:
        self.text = text
        self.users: list[str] = []

    async def complete(self, *, prompt_version: str, system: str, user: str, max_tokens: int):
        self.users.append(user)
        return LlmResult(
            text=self.text, input_tokens=1, output_tokens=1, cost_cents=1, model=DEFAULT_MODEL
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


def _service(llm, calls: FakeCalls | None = None) -> SuggestNoClassDates:
    record = RecordAiCall(
        calls=calls or FakeCalls(),
        counters=counters_at(),
        cap_source=FakeCap(),
        clock=lambda: datetime(2026, 11, 17, tzinfo=UTC),
    )
    return SuggestNoClassDates(llm=llm, record_ai_call=record)


def test_model_sees_only_the_dates_and_the_text() -> None:
    facts = json.loads(user_message(LEASE, DATES))
    assert facts == {
        "class_dates": [
            {"date": "2026-12-01", "weekday": "Tuesday"},
            {"date": "2026-12-22", "weekday": "Tuesday"},
            {"date": "2026-12-29", "weekday": "Tuesday"},
        ],
        "pasted_text": LEASE,
    }


@pytest.mark.parametrize(
    "answer",
    [
        "not json",
        json.dumps({"no_class": [{"date": "2026-12-25", "reason": "x"}], "notes": ""}),
        json.dumps({"no_class": [{"date": "2026-12-22"}, {"date": "2026-12-22"}]}),
        json.dumps({"no_class": [], "extra": 1}),
    ],
)
def test_answers_outside_the_class_dates_are_refused(answer: str) -> None:
    with pytest.raises(AiProviderError):
        parse_draft(answer, class_dates=DATES)


def test_fenced_answer_is_read() -> None:
    draft = parse_draft(f"```json\n{ANSWER}\n```", class_dates=DATES)
    assert [d.date for d in draft.no_class] == [date(2026, 12, 22), date(2026, 12, 29)]


@pytest.mark.asyncio
async def test_bad_answer_is_still_recorded() -> None:
    calls = FakeCalls()
    _tenant.set(A)
    with pytest.raises(AiProviderError):
        await _service(FakeLlm("nope"), calls).execute(
            text=LEASE, class_dates=DATES, approver="u-admin"
        )
    assert len(calls.recorded) == 1


class Caller:
    def __init__(self) -> None:
        self.roles: tuple[str, ...] = ("admin",)

    @property
    def claims(self) -> AuthClaims:
        return AuthClaims(
            user_id="u1",
            email="u1@example.test",
            academy_id=A,
            roles=self.roles,  # type: ignore[arg-type]
        )


def _client(caller: Caller, service) -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(admin_router, prefix="/api/v2")

    async def claims() -> AuthClaims:
        _tenant.set(A)
        return caller.claims

    app.dependency_overrides[get_auth_claims] = claims
    app.dependency_overrides[get_ai_schedule] = lambda: service
    return TestClient(app)


@pytest.fixture
def caller() -> Caller:
    return Caller()


@pytest.fixture
def client(caller: Caller) -> Iterator[TestClient]:
    with _client(caller, _service(FakeLlm())) as c:
        yield c


BODY = {"text": LEASE, "class_dates": [d.isoformat() for d in DATES]}


def test_admin_gets_the_suggested_dates(client: TestClient) -> None:
    response = client.post(URL, json=BODY)
    assert response.status_code == 200, response.text
    body = response.json()
    assert [d["date"] for d in body["no_class"]] == ["2026-12-22", "2026-12-29"]
    assert body["prompt_version"] == "schedule-dates-v1"


@pytest.mark.parametrize("roles", [("coach",), ("parent",), ("billing",)])
def test_non_admins_get_404(client: TestClient, caller: Caller, roles) -> None:
    caller.roles = roles
    assert client.post(URL, json=BODY).status_code == 404


def test_body_is_bounded(client: TestClient) -> None:
    assert client.post(URL, json={**BODY, "text": "x" * 8001}).status_code == 422
    assert client.post(URL, json={**BODY, "class_dates": []}).status_code == 422
    assert client.post(URL, json={**BODY, "academy_id": "acad-b"}).status_code == 422


def test_ai_off_is_a_503(caller: Caller) -> None:
    with _client(caller, _service(DisabledLlmPort())) as c:
        response = c.post(URL, json=BODY)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "Ai.Disabled"


def test_the_route_is_rate_limited() -> None:
    assert ("POST", URL) in _PATH_LIMIT_OVERRIDES
