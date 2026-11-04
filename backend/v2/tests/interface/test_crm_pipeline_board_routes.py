"""Interface tests for the Pipeline board read and quick add (People CRM L3b).

The real admin router with the real ``GetPipelineBoard`` and ``CreateContact``
over an in-memory contact store that mirrors the Mongo repository's semantics
(tenant-scoped reads, newest first, staff rows inserted every time); the
store itself is proven on a real ``mongod`` in
``contract/test_crm_pipeline_board_real_mongo.py``.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.contexts.crm.application.pipeline_board import GetPipelineBoard
from backend.v2.contexts.crm.application.use_cases.create_contact import CreateContact
from backend.v2.contexts.crm.domain.family_index import FamilyIndex, FamilyRecord
from backend.v2.contexts.crm.domain.models import CrmContact
from backend.v2.interfaces.admin import pipeline_routes
from backend.v2.interfaces.admin.router import router as admin_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers
from backend.v2.shared.tenancy import current_academy_id
from backend.v2.shared.tenancy.context import _current as _tenant

A = "acad-a"
B = "acad-b"
NOW = datetime(2026, 9, 24, 18, 30, tzinfo=UTC)
BOARD = "/api/v2/admin/crm/pipeline"
ADD = "/api/v2/admin/crm/contacts"


class ContactStore:
    """Tenant-scoped like ``MongoCrmContactRepository``; the academy is always
    the tenant context's, never the row's."""

    def __init__(self) -> None:
        self.rows: list[CrmContact] = []

    async def add_if_absent(self, contact: CrmContact) -> tuple[CrmContact, bool]:
        academy = current_academy_id()
        if contact.dedupe_key is not None:
            for row in self.rows:
                if row.academy_id == academy and row.dedupe_key == contact.dedupe_key:
                    return row, False
        stored = contact.model_copy(update={"academy_id": academy})
        self.rows.append(stored)
        return stored, True

    async def get(self, contact_id: str) -> CrmContact | None:
        academy = current_academy_id()
        return next(
            (r for r in self.rows if r.academy_id == academy and r.contact_id == contact_id), None
        )

    async def find_by_dedupe_key(self, dedupe_key: str) -> CrmContact | None:
        academy = current_academy_id()
        return next(
            (r for r in self.rows if r.academy_id == academy and r.dedupe_key == dedupe_key), None
        )

    async def list_by_pipeline_status(self, status=None, *, limit: int = 200):
        academy = current_academy_id()
        rows = [
            r
            for r in self.rows
            if r.academy_id == academy and (status is None or r.pipeline_status == status)
        ]
        return sorted(rows, key=lambda r: r.created_at, reverse=True)[:limit]


class Families:
    async def build(self, academy_id: str) -> FamilyIndex:
        families = (
            FamilyRecord(
                family_id=f"fam-{academy_id}",
                parent_name="Sample Family",
                email=None,
                phone=None,
                has_account=True,
                children=(),
                stage="trial",
            ),
        )
        return FamilyIndex(academy_id=academy_id, generated_at=NOW, families=families)


class Caller:
    def __init__(self) -> None:
        self.be("staff-1", "admin")

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
def store() -> ContactStore:
    return ContactStore()


@pytest.fixture
def client(caller: Caller, store: ContactStore) -> Iterator[TestClient]:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(admin_router, prefix="/api/v2")
    board = GetPipelineBoard(store, Families(), clock=lambda: NOW + timedelta(days=2))
    create = CreateContact(store, clock=lambda: NOW)

    async def claims() -> AuthClaims:
        _tenant.set(caller.claims.academy_id)
        return caller.claims

    app.dependency_overrides[get_auth_claims] = claims
    app.dependency_overrides[pipeline_routes.get_pipeline_board] = lambda: board
    app.dependency_overrides[pipeline_routes.get_quick_add] = lambda: create
    with TestClient(app) as c:
        yield c


def _add(client: TestClient, **body: object):
    payload: dict[str, object] = {
        "name": "Sample Parent",
        "phone": "(555) 010-2030",
        "child_name": "Sample Kid",
        "child_age": "8",
        "source": "whatsapp_or_phone",
    }
    payload.update(body)
    return client.post(ADD, json=payload)


def test_quick_add_creates_an_inquiry_card(client: TestClient, store: ContactStore) -> None:
    response = _add(client)
    assert response.status_code == 201, response.text
    card = response.json()
    assert card["kind"] == "contact"
    assert card["column"] == "inquiry"
    assert card["move_targets"] == ["trial_booked"]
    assert (card["name"], card["child"], card["child_age"]) == ("Sample Parent", "Sample Kid", "8")
    assert "academy_id" not in card and "phone_digits" not in card
    row = store.rows[0]
    assert (row.academy_id, row.created_by, row.pipeline_status) == (A, "staff-1", "lead")
    assert row.consent.marketing is False and row.consent.contact_about_request is True


def test_quick_add_refuses_website_source_extra_fields_and_no_reach(client: TestClient) -> None:
    assert _add(client, source="website").status_code == 422
    assert _add(client, academy_id=B).status_code == 422
    assert _add(client, pipeline_status="enrolled").status_code == 422
    no_reach = _add(client, phone=None)
    assert no_reach.status_code == 422
    assert no_reach.json()["error"]["code"] == "Crm.InvalidContact"


def test_board_merges_contacts_and_families_per_tenant(client: TestClient, caller: Caller) -> None:
    assert _add(client).status_code == 201
    caller.be("staff-b", "admin", academy_id=B)
    assert _add(client, name="Other Academy Parent").status_code == 201

    caller.be("staff-1", "admin")
    response = client.get(BOARD)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["warnings"] == []
    cards = {card["card_id"].split(":")[0]: card for card in body["cards"]}
    assert len(body["cards"]) == 2
    assert cards["contact"]["name"] == "Sample Parent"
    assert cards["contact"]["lead_age_days"] == 2
    assert cards["family"] == {
        **cards["family"],
        "family_id": f"fam-{A}",
        "column": "trial_booked",
        "move_targets": [],
    }


def test_wrong_persona_is_404(client: TestClient, caller: Caller) -> None:
    for roles in (("coach",), ("parent",)):
        caller.be("someone", *roles)
        assert client.get(BOARD).status_code == 404
        assert _add(client).status_code == 404
