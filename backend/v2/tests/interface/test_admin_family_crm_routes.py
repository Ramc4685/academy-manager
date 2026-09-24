"""Interface tests for family notes and follow-ups (People CRM Phase 4a).

The real admin router, the real use cases, and the store fakes that mirror
the Mongo repositories. The academy is the caller's tenant; a coach or parent
gets the wrong-persona 404 (docs/security-matrix.md), another academy's family
is a 404, and a non-author admin gets 403 on edit and delete.
"""

from __future__ import annotations

import itertools
from collections.abc import Iterator
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.contexts.crm.application.use_cases.family_follow_ups import (
    AddFamilyFollowUp,
    ListFamilyFollowUps,
    ListFollowUps,
    UpdateFamilyFollowUp,
)
from backend.v2.contexts.crm.application.use_cases.family_notes import (
    AddFamilyNote,
    DeleteFamilyNote,
    EditFamilyNote,
    ListFamilyNotes,
)
from backend.v2.interfaces.admin.family_crm_routes import get_admin_family_crm
from backend.v2.interfaces.admin.router import router as admin_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers
from backend.v2.shared.tenancy.context import _current as _tenant
from backend.v2.tests.fixtures.crm_family_fakes import (
    FakeFamilyDirectory,
    FakeFamilyFollowUpRepository,
    FakeFamilyNoteRepository,
    FakeStaffDirectory,
    fixed_timezone,
)

A = "acad-a"
B = "acad-b"
NOW = datetime(2026, 9, 23, 15, 0, tzinfo=UTC)


def _services() -> SimpleNamespace:
    families = FakeFamilyDirectory()
    families.add(A, "p-1", "Testparent One", "fb-p-1")
    families.add(B, "p-b", "Testparent Bee")
    staff = FakeStaffDirectory()
    for user in ("u-admin", "u-other", "u-owner"):
        staff.add(A, user)
    staff.add(B, "u-b")
    ids = (f"id-{n}" for n in itertools.count(1))
    notes = FakeFamilyNoteRepository()
    fus = FakeFamilyFollowUpRepository()
    tz = fixed_timezone("America/Chicago")

    def clock() -> datetime:
        return NOW

    def new_id() -> str:
        return next(ids)

    args = (fus, families, staff, tz)
    return SimpleNamespace(
        index=None,
        notes=SimpleNamespace(
            list=ListFamilyNotes(notes, families),
            add=AddFamilyNote(notes, families, clock=clock, new_id=new_id),
            edit=EditFamilyNote(notes, families, clock=clock),
            delete=DeleteFamilyNote(notes, families, clock=clock),
        ),
        follow_ups=SimpleNamespace(
            list=ListFamilyFollowUps(*args, clock=clock),
            add=AddFamilyFollowUp(*args, clock=clock, new_id=new_id),
            update=UpdateFamilyFollowUp(*args, clock=clock),
            queue=ListFollowUps(*args, clock=clock),
        ),
    )


class Caller:
    def __init__(self) -> None:
        self.claims = AuthClaims(
            user_id="u-admin", email="a@example.test", academy_id=A, roles=("admin",)
        )

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
        # What TenancyMiddleware does in production: the tenant ContextVar is
        # the caller's resolved academy for the whole request.
        _tenant.set(caller.claims.academy_id)
        return caller.claims

    app.dependency_overrides[get_auth_claims] = claims
    app.dependency_overrides[get_admin_family_crm] = lambda: services
    with TestClient(app) as c:
        yield c


BASE = "/api/v2/admin/families"


def test_add_list_edit_delete_a_note(client: TestClient, caller: Caller) -> None:
    created = client.post(f"{BASE}/fb-p-1/notes", json={"body": "  Prefers texts  "})
    assert created.status_code == 201, created.text
    note = created.json()
    assert note["parent_id"] == "p-1"
    assert note["body"] == "Prefers texts"
    assert note["can_edit"] is True and note["edited"] is False

    listed = client.get(f"{BASE}/p-1/notes").json()
    assert listed["family_id"] == "p-1"
    assert [n["note_id"] for n in listed["notes"]] == [note["note_id"]]

    caller.be("u-other", "admin")
    assert client.get(f"{BASE}/p-1/notes").json()["notes"][0]["can_edit"] is False
    denied = client.patch(f"{BASE}/p-1/notes/{note['note_id']}", json={"body": "x"})
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "Crm.NoteEditForbidden"
    assert client.delete(f"{BASE}/p-1/notes/{note['note_id']}").status_code == 403

    caller.be("u-admin", "admin")
    edited = client.patch(f"{BASE}/p-1/notes/{note['note_id']}", json={"body": "Texts only"})
    assert edited.status_code == 200 and edited.json()["body"] == "Texts only"

    caller.be("u-owner", "admin", "owner")
    assert client.delete(f"{BASE}/p-1/notes/{note['note_id']}").status_code == 204
    assert client.get(f"{BASE}/p-1/notes").json()["notes"] == []
    assert client.delete(f"{BASE}/p-1/notes/{note['note_id']}").status_code == 404


def test_note_validation_and_no_academy_from_the_body(client: TestClient) -> None:
    empty = client.post(f"{BASE}/p-1/notes", json={"body": "   "})
    assert empty.status_code == 422
    assert empty.json()["error"]["code"] == "Crm.InvalidFamilyNote"
    forged = client.post(f"{BASE}/p-1/notes", json={"body": "hi", "academy_id": B})
    assert forged.status_code == 422  # extra fields are refused, never trusted
    assert client.post(f"{BASE}/p-1/notes", json={"body": "a" * 9000}).status_code == 422


def test_cross_tenant_family_is_404(client: TestClient, caller: Caller) -> None:
    assert client.get(f"{BASE}/p-b/notes").status_code == 404
    assert client.post(f"{BASE}/p-b/notes", json={"body": "x"}).status_code == 404
    assert client.get(f"{BASE}/p-b/follow-ups").status_code == 404
    created = client.post(f"{BASE}/p-1/notes", json={"body": "A's note"}).json()

    caller.be("u-b", "admin", "owner", academy_id=B)
    assert client.get(f"{BASE}/p-1/notes").status_code == 404
    assert (
        client.patch(f"{BASE}/p-1/notes/{created['note_id']}", json={"body": "x"}).status_code
        == 404
    )
    assert client.delete(f"{BASE}/p-1/notes/{created['note_id']}").status_code == 404
    assert client.get("/api/v2/admin/follow-ups?assignee=all").json()["follow_ups"] == []


@pytest.mark.parametrize("roles", [("coach",), ("parent",), ("assistant_coach",), ("student",)])
def test_non_admin_personas_get_404(client: TestClient, caller: Caller, roles) -> None:
    caller.be("u-x", *roles)
    calls = [
        client.get(f"{BASE}/p-1/notes"),
        client.post(f"{BASE}/p-1/notes", json={"body": "x"}),
        client.patch(f"{BASE}/p-1/notes/n-1", json={"body": "x"}),
        client.delete(f"{BASE}/p-1/notes/n-1"),
        client.get(f"{BASE}/p-1/follow-ups"),
        client.post(
            f"{BASE}/p-1/follow-ups",
            json={"title": "x", "due_on": "2026-09-30", "assignee_user_id": "u-x"},
        ),
        client.patch(f"{BASE}/p-1/follow-ups/f-1", json={"status": "done"}),
        client.get("/api/v2/admin/follow-ups"),
    ]
    assert [r.status_code for r in calls] == [404] * len(calls)


def test_follow_up_lifecycle_and_my_queue(client: TestClient, caller: Caller) -> None:
    created = client.post(
        f"{BASE}/p-1/follow-ups",
        json={"title": "Call about trial", "due_on": "2026-09-22", "assignee_user_id": "u-admin"},
    )
    assert created.status_code == 201, created.text
    row = created.json()
    assert row["bucket"] == "overdue" and row["status"] == "open"
    client.post(
        f"{BASE}/p-1/follow-ups",
        json={"title": "Other's task", "due_on": "2026-09-23", "assignee_user_id": "u-other"},
    )
    bad = client.post(
        f"{BASE}/p-1/follow-ups",
        json={"title": "x", "due_on": "2026-09-23", "assignee_user_id": "u-b"},
    )
    assert bad.status_code == 422 and bad.json()["error"]["details"]["field"] == "assignee"

    mine = client.get("/api/v2/admin/follow-ups?assignee=me&bucket=overdue").json()
    assert mine["today"] == "2026-09-23"
    assert [f["follow_up_id"] for f in mine["follow_ups"]] == [row["follow_up_id"]]
    assert mine["follow_ups"][0]["family_name"] == "Testparent One"
    everyone = client.get("/api/v2/admin/follow-ups?assignee=all").json()
    assert len(everyone["follow_ups"]) == 2
    assert client.get("/api/v2/admin/follow-ups?bucket=later").status_code == 422

    done = client.patch(f"{BASE}/p-1/follow-ups/{row['follow_up_id']}", json={"status": "done"})
    assert done.status_code == 200
    assert done.json()["status"] == "done" and done.json()["done_by"] == "u-admin"
    assert (
        client.get("/api/v2/admin/follow-ups?assignee=me&bucket=overdue").json()["follow_ups"] == []
    )
    family = client.get(f"{BASE}/p-1/follow-ups").json()
    assert family["family_id"] == "p-1"
    assert {f["bucket"] for f in family["follow_ups"]} == {"done", "today"}
    assert (
        client.patch(f"{BASE}/p-1/follow-ups/missing", json={"status": "done"}).status_code == 404
    )


def test_family_notes_services_missing_is_503() -> None:
    app = FastAPI()
    app.include_router(admin_router, prefix="/api/v2")
    app.state.admin_family_index = SimpleNamespace(index=None)
    app.dependency_overrides[get_auth_claims] = lambda: AuthClaims(
        user_id="u", email="u@example.test", academy_id=A, roles=("admin",)
    )
    with TestClient(app) as c:
        assert c.get(f"{BASE}/p-1/notes").status_code == 503


def test_due_on_must_be_a_date(client: TestClient) -> None:
    r = client.post(
        f"{BASE}/p-1/follow-ups",
        json={"title": "x", "due_on": "next week", "assignee_user_id": "u-admin"},
    )
    assert r.status_code == 422
    assert date.fromisoformat("2026-09-23")  # sanity: ISO dates are the wire format
