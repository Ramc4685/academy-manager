"""Interface tests for the family Messages tab routes (People CRM Phase 6, L4c).

The real admin router and the real use cases with in-memory sources and the
in-memory log repository (which mirrors the Mongo one, see
``tests/unit/test_crm_family_messages.py``). Checks: the thread shape and
``can_complete``, logging a contact and completing a pending handoff,
validation 422s, another academy's family is a 404, a coach or parent gets
the wrong-persona 404, and only the author or an owner completes.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.contexts.crm.application.family_messages import (
    CompleteFamilyContactLog,
    FamilyMessagesScope,
    GetFamilyMessages,
    LogFamilyContact,
    MessageEntry,
)
from backend.v2.contexts.crm.infrastructure.family_message_sources import ContactLogSource
from backend.v2.interfaces.admin.family_messages_routes import get_family_messages
from backend.v2.interfaces.admin.router import router as admin_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers
from backend.v2.shared.tenancy.context import _current as _tenant
from backend.v2.tests.unit.test_crm_family_messages import Aliases, Directory, FakeLogs

A = "acad-a"
B = "acad-b"
T0 = datetime(2026, 9, 1, 15, 0, tzinfo=UTC)
BASE = "/api/v2/admin/families"


class Emails:
    name = "campaigns"

    async def fetch(self, scope: FamilyMessagesScope) -> Sequence[MessageEntry]:
        return [
            MessageEntry(
                entry_id="campaign:d-1",
                at=T0,
                channel="email",
                source="campaign",
                status="failed",
                summary="Email: Holiday schedule",
                recipient="parent@example.test",
                failed_reason="bounced",
            )
        ]


@dataclass
class Bundle:
    thread: GetFamilyMessages
    log: LogFamilyContact
    complete: CompleteFamilyContactLog


class Caller:
    def __init__(self) -> None:
        self.be("admin", user_id="u-1")

    def be(self, *roles: str, academy_id: str = A, user_id: str = "u-1") -> None:
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
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(admin_router, prefix="/api/v2")
    logs = FakeLogs()
    ids = iter(f"l-{i}" for i in range(1, 100))
    bundle = Bundle(
        thread=GetFamilyMessages(Directory(), Aliases(), [Emails(), ContactLogSource(logs)]),
        log=LogFamilyContact(logs, Directory(), new_id=lambda: next(ids)),
        complete=CompleteFamilyContactLog(logs, Directory()),
    )

    async def claims() -> AuthClaims:
        _tenant.set(caller.claims.academy_id)
        return caller.claims

    app.dependency_overrides[get_auth_claims] = claims
    app.dependency_overrides[get_family_messages] = lambda: bundle
    with TestClient(app) as c:
        yield c


def test_log_then_read_the_thread(client: TestClient) -> None:
    created = client.post(
        f"{BASE}/fb-p-1/messages/log",
        json={"channel": "whatsapp", "status": "not_logged", "note": "See you Saturday"},
    )
    assert created.status_code == 201, created.text
    row = created.json()
    assert row["log_id"] == "l-1"
    assert row["status"] == "not_logged" and row["can_complete"] is True
    assert row["summary"] == "WhatsApp opened, not confirmed as sent"

    body = client.get(f"{BASE}/p-1/messages").json()
    assert body["family_id"] == "p-1"
    assert body["warnings"] == []
    ids = [e["entry_id"] for e in body["entries"]]
    assert set(ids) == {"campaign:d-1", "log:l-1"}
    email = next(e for e in body["entries"] if e["entry_id"] == "campaign:d-1")
    assert email["status"] == "failed" and email["failed_reason"] == "bounced"
    assert email["can_complete"] is False

    done = client.patch(f"{BASE}/p-1/messages/log/l-1", json={"note": "Sent it"})
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "logged"
    assert done.json()["detail"] == "Sent it"
    assert done.json()["can_complete"] is False


def test_a_call_is_logged_directly(client: TestClient) -> None:
    created = client.post(f"{BASE}/p-1/messages/log", json={"channel": "call", "note": "Asked"})
    assert created.status_code == 201
    assert created.json()["summary"] == "Phone call"
    assert created.json()["status"] == "logged"


@pytest.mark.parametrize(
    "payload",
    [
        {"channel": "pigeon"},
        {"channel": "call", "status": "not_logged"},
        {"channel": "sms", "note": "x" * 5000},
        {"channel": "sms", "academy_id": B},
    ],
)
def test_bad_input_is_a_422(client: TestClient, payload: dict[str, Any]) -> None:
    assert client.post(f"{BASE}/p-1/messages/log", json=payload).status_code == 422


def test_another_academys_family_is_a_404(client: TestClient, caller: Caller) -> None:
    caller.be("admin", academy_id=B)
    response = client.get(f"{BASE}/p-1/messages")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "Crm.FamilyNotFound"
    assert client.post(f"{BASE}/p-1/messages/log", json={"channel": "call"}).status_code == 404


def test_unknown_log_is_a_404(client: TestClient) -> None:
    response = client.patch(f"{BASE}/p-1/messages/log/nope", json={})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "Crm.ContactLogNotFound"


def test_only_the_author_or_an_owner_completes(client: TestClient, caller: Caller) -> None:
    client.post(f"{BASE}/p-1/messages/log", json={"channel": "sms", "status": "not_logged"})
    caller.be("admin", user_id="u-2")
    listed = client.get(f"{BASE}/p-1/messages").json()["entries"]
    assert next(e for e in listed if e["log_id"] == "l-1")["can_complete"] is False
    response = client.patch(f"{BASE}/p-1/messages/log/l-1", json={})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "Crm.ContactLogEditForbidden"
    caller.be("admin", "owner", user_id="u-3")
    assert client.patch(f"{BASE}/p-1/messages/log/l-1", json={}).status_code == 200


@pytest.mark.parametrize("roles", [("coach",), ("parent",), ("assistant_coach",), ("student",)])
def test_wrong_persona_gets_the_404(
    client: TestClient, caller: Caller, roles: tuple[str, ...]
) -> None:
    caller.be(*roles)
    assert client.get(f"{BASE}/p-1/messages").status_code == 404
    assert client.post(f"{BASE}/p-1/messages/log", json={"channel": "call"}).status_code == 404
