"""Interface tests for family contacts and details (People CRM Phase 4b).

The real admin router, the real use cases, and the store fakes that mirror
the Mongo repositories (unique contact id, partial per-family email index).
The academy is the caller's tenant; a coach or parent gets the wrong-persona
404 (docs/security-matrix.md); another academy's family is a 404; a body that
tries to carry an academy is refused; both switches default to off.
"""

from __future__ import annotations

import itertools
from collections.abc import Iterator
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.contexts.crm.application.use_cases.family_contacts import (
    AddFamilyContact,
    DeleteFamilyContact,
    GetFamilyDetails,
    ListFamilyContacts,
    UpdateFamilyContact,
    UpdateFamilyDetails,
)
from backend.v2.interfaces.admin.family_contacts_routes import get_admin_family_contacts
from backend.v2.interfaces.admin.router import router as admin_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers
from backend.v2.shared.tenancy.context import _current as _tenant
from backend.v2.tests.fixtures.crm_family_contacts_fakes import (
    FakeFamilyContactRepository,
    FakeFamilyDetailsRepository,
)
from backend.v2.tests.fixtures.crm_family_fakes import FakeFamilyDirectory

A = "acad-a"
B = "acad-b"
NOW = datetime(2026, 9, 23, 15, 0, tzinfo=UTC)
BASE = "/api/v2/admin/families"


def _services() -> SimpleNamespace:
    families = FakeFamilyDirectory()
    families.add(A, "p-1", "Testparent One", "fb-p-1")
    families.add(B, "p-b", "Testparent Bee")
    contacts = FakeFamilyContactRepository()
    details = FakeFamilyDetailsRepository()
    ids = (f"c-{n}" for n in itertools.count(1))

    def clock() -> datetime:
        return NOW

    return SimpleNamespace(
        list=ListFamilyContacts(contacts, families),
        add=AddFamilyContact(contacts, families, clock=clock, new_id=lambda: next(ids)),
        update=UpdateFamilyContact(contacts, families, clock=clock),
        delete=DeleteFamilyContact(contacts, families),
        get_details=GetFamilyDetails(details, families),
        update_details=UpdateFamilyDetails(details, families, clock=clock),
    )


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
def client(caller: Caller) -> Iterator[TestClient]:
    services = _services()
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(admin_router, prefix="/api/v2")

    async def claims() -> AuthClaims:
        _tenant.set(caller.claims.academy_id)
        return caller.claims

    app.dependency_overrides[get_auth_claims] = claims
    app.dependency_overrides[get_admin_family_contacts] = lambda: services
    with TestClient(app) as c:
        yield c


def test_add_list_toggle_and_delete_a_contact(client: TestClient) -> None:
    created = client.post(
        f"{BASE}/fb-p-1/contacts",
        json={
            "name": "Second Testparent",
            "email": "Second@Example.test",
            "relationship": "parent",
        },
    )
    assert created.status_code == 201, created.text
    contact = created.json()
    assert contact["parent_id"] == "p-1"
    assert contact["email"] == "second@example.test"
    assert contact["gets_notices"] is False and contact["gets_invoices"] is False

    listed = client.get(f"{BASE}/p-1/contacts").json()
    assert listed["family_id"] == "p-1"
    assert [c["contact_id"] for c in listed["contacts"]] == [contact["contact_id"]]

    url = f"{BASE}/p-1/contacts/{contact['contact_id']}"
    on = client.patch(url, json={"gets_notices": True})
    assert on.status_code == 200 and on.json()["gets_notices"] is True
    assert on.json()["gets_invoices"] is False  # never switched on as a side effect
    invoices = client.patch(url, json={"gets_invoices": True})
    assert invoices.json()["gets_invoices"] is True

    assert client.delete(url).status_code == 204
    assert client.get(f"{BASE}/p-1/contacts").json()["contacts"] == []
    assert client.delete(url).status_code == 404


def test_validation_is_field_level_and_duplicate_email_is_409(client: TestClient) -> None:
    bad = client.post(f"{BASE}/p-1/contacts", json={"name": "X", "email": "nope"})
    assert bad.status_code == 422
    assert bad.json()["error"]["code"] == "Crm.InvalidFamilyContact"
    assert bad.json()["error"]["details"]["field"] == "email"

    no_mail = client.post(
        f"{BASE}/p-1/contacts", json={"name": "X", "phone": "555-010-0001", "gets_notices": True}
    )
    assert no_mail.status_code == 422
    assert no_mail.json()["error"]["details"]["field"] == "gets_notices"

    ok = client.post(f"{BASE}/p-1/contacts", json={"name": "X", "email": "x@example.test"})
    assert ok.status_code == 201
    dup = client.post(f"{BASE}/p-1/contacts", json={"name": "Y", "email": "X@example.test"})
    assert dup.status_code == 409
    assert dup.json()["error"]["code"] == "Crm.DuplicateFamilyContactEmail"

    forged = client.post(
        f"{BASE}/p-1/contacts", json={"name": "Z", "email": "z@example.test", "academy_id": B}
    )
    assert forged.status_code == 422  # extra fields are refused, never trusted
    null_switch = client.patch(
        f"{BASE}/p-1/contacts/{ok.json()['contact_id']}", json={"gets_notices": None}
    )
    assert null_switch.status_code == 422


def test_details_read_and_partial_patch(client: TestClient) -> None:
    empty = client.get(f"{BASE}/fb-p-1/details")
    assert empty.status_code == 200
    assert empty.json() == {
        "family_id": "p-1",
        "address": None,
        "preferred_channel": None,
        "heard_about_us": None,
        "tags": [],
        "updated_by": None,
        "updated_at": None,
    }
    saved = client.patch(
        f"{BASE}/p-1/details",
        json={"address": "1 Test Street", "preferred_channel": "whatsapp", "tags": ["VIP"]},
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["address"] == "1 Test Street" and body["preferred_channel"] == "whatsapp"
    assert body["updated_by"] == "u-admin"
    cleared = client.patch(f"{BASE}/p-1/details", json={"address": None}).json()
    assert cleared["address"] is None and cleared["tags"] == ["VIP"]
    bad = client.patch(f"{BASE}/p-1/details", json={"preferred_channel": "fax"})
    assert bad.status_code == 422
    assert bad.json()["error"]["details"]["field"] == "preferred_channel"
    assert client.patch(f"{BASE}/p-1/details", json={"balance_cents": 0}).status_code == 422


def test_cross_tenant_family_is_404(client: TestClient, caller: Caller) -> None:
    assert client.get(f"{BASE}/p-b/contacts").status_code == 404
    assert (
        client.post(f"{BASE}/p-b/contacts", json={"name": "X", "email": "x@example.test"})
    ).status_code == 404
    assert client.get(f"{BASE}/p-b/details").status_code == 404
    created = client.post(
        f"{BASE}/p-1/contacts", json={"name": "A's contact", "email": "a@example.test"}
    ).json()

    caller.be("u-b", "admin", "owner", academy_id=B)
    assert client.get(f"{BASE}/p-1/contacts").status_code == 404
    assert client.patch(f"{BASE}/p-1/details", json={"address": "x"}).status_code == 404
    assert (
        client.patch(
            f"{BASE}/p-b/contacts/{created['contact_id']}", json={"gets_notices": True}
        ).status_code
        == 404
    )
    assert client.delete(f"{BASE}/p-b/contacts/{created['contact_id']}").status_code == 404


@pytest.mark.parametrize("role", ["coach", "parent"])
def test_other_personas_get_404(client: TestClient, caller: Caller, role: str) -> None:
    caller.be("u-x", role)
    assert client.get(f"{BASE}/p-1/contacts").status_code == 404
    assert (
        client.post(f"{BASE}/p-1/contacts", json={"name": "X", "email": "x@example.test"})
    ).status_code == 404
    assert client.get(f"{BASE}/p-1/details").status_code == 404
    assert client.patch(f"{BASE}/p-1/details", json={"address": "x"}).status_code == 404


def test_services_are_composed_once_from_app_state() -> None:
    """Without an override the dependency composes on first use and caches."""
    from motor.motor_asyncio import AsyncIOMotorClient

    app = FastAPI()
    app.state.db = AsyncIOMotorClient("mongodb://127.0.0.1:1", connect=False)["x"]
    request = SimpleNamespace(app=app)
    first = get_admin_family_contacts(request)  # type: ignore[arg-type]
    assert get_admin_family_contacts(request) is first  # type: ignore[arg-type]
    assert app.state.admin_family_contacts is first

    bare = FastAPI()
    with pytest.raises(Exception) as err:
        get_admin_family_contacts(SimpleNamespace(app=bare))  # type: ignore[arg-type]
    assert getattr(err.value, "status_code", None) == 503
