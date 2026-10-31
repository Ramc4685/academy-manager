"""Interface tests for ``POST /admin/people/duplicate-check`` (People CRM Phase 4c).

The real admin router with a recording stand-in for ``FindPossibleDuplicates``
(its behaviour, tenancy and indexes are proven on a real ``mongod`` in
``contract/test_crm_duplicate_check_real_mongo.py``). Checks the persona gate
(a coach or parent gets the wrong-persona 404, docs/security-matrix.md), that
the academy is the caller's tenant and never the body's, the response shape,
and that the path is rate-limited.
"""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.contexts.crm.application.use_cases.find_possible_duplicates import (
    DuplicateCheckQuery,
)
from backend.v2.contexts.crm.domain.duplicates import DuplicateMatch
from backend.v2.interfaces.admin.people_duplicate_routes import get_admin_people_duplicates
from backend.v2.interfaces.admin.router import router as admin_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers
from backend.v2.shared.http.rate_limit import _PATH_LIMIT_OVERRIDES
from backend.v2.shared.tenancy.context import _current as _tenant

A = "acad-a"
URL = "/api/v2/admin/people/duplicate-check"


class _RecordingFind:
    def __init__(self) -> None:
        self.calls: list[tuple[str, DuplicateCheckQuery]] = []

    async def execute(self, academy_id: str, query: DuplicateCheckQuery) -> list[DuplicateMatch]:
        self.calls.append((academy_id, query))
        if not (query.email or query.phone or query.name):
            return []
        return [
            DuplicateMatch(
                kind="family",
                record_id="p-1",
                display_name="Testparent One",
                email_masked="te***@example.test",
                phone_masked="•••-2030",
                link="/admin/families/p-1",
                matched_on=("email", "phone"),
            )
        ]


class Caller:
    def __init__(self) -> None:
        self.be("u-admin", "admin")

    def be(self, user_id: str, *roles: str, academy_id: str = A) -> None:
        self.claims = AuthClaims(
            user_id=user_id,
            email=f"{user_id}@example.test",
            academy_id=academy_id,
            roles=roles,  # type: ignore[arg-type]
        )


@pytest.fixture
def caller() -> Caller:
    return Caller()


@pytest.fixture
def find() -> _RecordingFind:
    return _RecordingFind()


@pytest.fixture
def client(caller: Caller, find: _RecordingFind) -> Iterator[TestClient]:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(admin_router, prefix="/api/v2")

    async def claims() -> AuthClaims:
        _tenant.set(caller.claims.academy_id)
        return caller.claims

    app.dependency_overrides[get_auth_claims] = claims
    app.dependency_overrides[get_admin_people_duplicates] = lambda: SimpleNamespace(find=find)
    with TestClient(app) as c:
        yield c


def test_admin_gets_masked_matches_for_the_tenant(client: TestClient, find: Any) -> None:
    response = client.post(
        URL, json={"email": "Test@Example.test", "phone": "555-010-2030", "name": None}
    )
    assert response.status_code == 200
    assert response.json() == {
        "matches": [
            {
                "kind": "family",
                "display_name": "Testparent One",
                "email_masked": "te***@example.test",
                "phone_masked": "•••-2030",
                "link": "/admin/families/p-1",
                "matched_on": ["email", "phone"],
            }
        ]
    }
    assert find.calls == [
        (A, DuplicateCheckQuery(email="Test@Example.test", phone="555-010-2030", name=None))
    ]


def test_empty_body_answers_no_matches(client: TestClient) -> None:
    response = client.post(URL, json={})
    assert response.status_code == 200
    assert response.json() == {"matches": []}


@pytest.mark.parametrize("role", ["coach", "parent", "assistant_coach"])
def test_non_admin_gets_the_wrong_persona_404(
    client: TestClient, caller: Caller, find: Any, role: str
) -> None:
    caller.be("u-other", role)
    response = client.post(URL, json={"email": "someone@example.test"})
    assert response.status_code == 404
    assert find.calls == []


def test_the_body_cannot_carry_an_academy(client: TestClient, find: Any) -> None:
    response = client.post(URL, json={"email": "x@example.test", "academy_id": "acad-b"})
    assert response.status_code == 422
    assert find.calls == []


def test_oversized_fields_are_refused(client: TestClient) -> None:
    assert client.post(URL, json={"phone": "5" * 65}).status_code == 422


def test_the_route_is_rate_limited() -> None:
    assert ("POST", URL) in _PATH_LIMIT_OVERRIDES
