"""``/admin/crm/nurture-sequence`` (AI strategy Phase 3, C1): the real admin
router over the real ``ManageNurtureSequence`` and ``AcademyNurtureSettings``
on ``mongomock``; only the email notifier's example values are faked."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from types import SimpleNamespace

import mongomock_motor
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.composition.nurture import AcademyNurtureSettings
from backend.v2.contexts.crm.application.use_cases.nurture_sequence import ManageNurtureSequence
from backend.v2.contexts.identity.infrastructure.mongo_academy_repo import MongoAcademyRepository
from backend.v2.interfaces.admin.router import router as admin_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers
from backend.v2.shared.tenancy.context import _current as _tenant

A = "acad-a"
B = "acad-b"
ROUTE = "/api/v2/admin/crm/nurture-sequence"


class ExampleValues:
    async def example_values(self, academy_id: str) -> dict[str, str]:
        return {
            "academy_name": f"Academy {academy_id}",
            "class": "Junior Beginners",
            "seat_band": "Only 3 seats are left.",
            "booking_link": f"https://{academy_id}.example.test/",
        }


class Caller:
    def __init__(self) -> None:
        self.be("staff-a", "admin")

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
def client(caller: Caller) -> Iterator[TestClient]:
    db = mongomock_motor.AsyncMongoMockClient()["nurture_routes"]
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(admin_router, prefix="/api/v2")
    app.state.nurture = SimpleNamespace(
        manage=ManageNurtureSequence(
            AcademyNurtureSettings(MongoAcademyRepository(db)), ExampleValues()
        )
    )

    async def claims() -> AuthClaims:
        _tenant.set(caller.claims.academy_id)
        return caller.claims

    app.dependency_overrides[get_auth_claims] = claims
    asyncio.run(db["academies"].insert_many([{"academy_id": A}, {"academy_id": B}]))
    with TestClient(app) as c:
        yield c


STEPS = [
    {"day": 2, "subject": "Still thinking about {{class}}?", "body": "Hi from {{academy_name}}."},
    {"day": 7, "subject": "", "body": ""},
    {"day": 21, "subject": "Last note", "body": "{{booking_link}}"},
]


def test_default_is_off_with_three_blank_days(client: TestClient) -> None:
    response = client.get(ROUTE)
    assert response.status_code == 200, response.text
    assert response.json() == {
        "enabled": False,
        "enabled_at": None,
        "steps": [
            {"day": 2, "subject": "", "body": ""},
            {"day": 7, "subject": "", "body": ""},
            {"day": 21, "subject": "", "body": ""},
        ],
        "merge_fields": ["academy_name", "class", "seat_band", "booking_link"],
    }


def test_save_switches_it_on_and_reads_back(client: TestClient) -> None:
    saved = client.put(ROUTE, json={"enabled": True, "steps": STEPS})
    assert saved.status_code == 200, saved.text
    body = client.get(ROUTE).json()
    assert body["enabled"] is True and body["enabled_at"] is not None
    assert body["steps"][0]["subject"] == "Still thinking about {{class}}?"
    assert body["steps"][1] == {"day": 7, "subject": "", "body": ""}


def test_another_academy_neither_sees_nor_changes_it(client: TestClient, caller: Caller) -> None:
    assert client.put(ROUTE, json={"enabled": True, "steps": STEPS}).status_code == 200
    caller.be("staff-b", "admin", academy_id=B)
    assert client.get(ROUTE).json()["enabled"] is False
    assert client.put(ROUTE, json={"enabled": False, "steps": []}).status_code == 200
    caller.be("staff-a", "admin")
    assert client.get(ROUTE).json()["enabled"] is True


def test_preview_uses_the_callers_academy(client: TestClient, caller: Caller) -> None:
    caller.be("staff-b", "admin", academy_id=B)
    response = client.post(
        f"{ROUTE}/preview",
        json={"day": 2, "subject": "{{class}} at {{academy_name}}", "body": "{{booking_link}}"},
    )
    assert response.status_code == 200, response.text
    assert response.json() == {
        "subject": f"Junior Beginners at Academy {B}",
        "body_text": f"https://{B}.example.test/",
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"enabled": True, "steps": [{"day": 3, "subject": "s", "body": "b"}]},
        {"enabled": True, "steps": [{"day": 2, "subject": "Hi {{first_name}}", "body": "b"}]},
        {"enabled": True, "steps": [{"day": 2, "subject": "s", "body": ""}]},
    ],
)
def test_invalid_steps_are_422(client: TestClient, payload: dict[str, object]) -> None:
    response = client.put(ROUTE, json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "Crm.InvalidNurtureSequence"
    assert client.get(ROUTE).json()["enabled"] is False


def test_extra_fields_are_refused(client: TestClient) -> None:
    response = client.put(ROUTE, json={"enabled": True, "steps": [], "academy_id": B})
    assert response.status_code == 422


def test_wrong_persona_is_404(client: TestClient, caller: Caller) -> None:
    for roles in (("coach",), ("parent",)):
        caller.be("someone", *roles)
        assert client.get(ROUTE).status_code == 404
        assert client.put(ROUTE, json={"enabled": True, "steps": STEPS}).status_code == 404
        preview = client.post(f"{ROUTE}/preview", json={"day": 2, "subject": "", "body": ""})
        assert preview.status_code == 404
    caller.be("staff-a", "admin")
    assert client.get(ROUTE).json()["enabled"] is False
