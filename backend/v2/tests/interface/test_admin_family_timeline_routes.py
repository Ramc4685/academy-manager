"""Interface tests for ``GET /admin/families/{id}/timeline`` (People CRM Phase 5).

The real admin router and the real ``GetFamilyTimeline`` with in-memory
sources. Checks: the page shape and cursor paging, another academy's family
is a 404, a coach or parent gets the wrong-persona 404, a bad cursor is a
422, and a caller who may not see money gets the money rows without amounts
(#553).
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.contexts.crm.application.timeline import (
    FamilyTimelineScope,
    GetFamilyTimeline,
    TimelineEntry,
    TimelineSourceResult,
)
from backend.v2.contexts.crm.domain.family_index import FamilyChild, FamilyRecord
from backend.v2.interfaces.admin import family_timeline_routes
from backend.v2.interfaces.admin.family_timeline_routes import get_family_timeline
from backend.v2.interfaces.admin.router import router as admin_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers
from backend.v2.shared.tenancy.context import _current as _tenant

A = "acad-a"
B = "acad-b"
T0 = datetime(2026, 9, 1, 15, 0, tzinfo=UTC)
BASE = "/api/v2/admin/families"


class Directory:
    async def find_record(self, academy_id: str, family_id: str) -> FamilyRecord | None:
        if (academy_id, family_id) != (A, "p-1"):
            return None
        return FamilyRecord(
            family_id="p-1",
            parent_name="Testparent One",
            email=None,
            phone=None,
            has_account=True,
            children=(FamilyChild(student_id="s-1", name="Kid Alpha", lifecycle="active"),),
            stage="active",
        )

    async def names(self, academy_id: str) -> Mapping[str, str | None]:
        return {}


class Aliases:
    async def resolve_parent_aliases(self, raw_ids: Sequence[str]) -> Mapping[str, Any]:
        return {}


class Entries:
    name = "fixed"

    async def fetch(self, scope: FamilyTimelineScope) -> TimelineSourceResult:
        entries = [
            TimelineEntry(
                entry_id=f"n{i}",
                at=T0 - timedelta(days=i),
                kind="crm",
                code="crm:note_added",
                summary="Team note added",
                source="crm",
                detail=f"note {i}",
            )
            for i in range(3)
        ]
        entries.append(
            TimelineEntry(
                entry_id="pay",
                at=T0 + timedelta(hours=1),
                kind="money",
                code="payment_received",
                summary="$60 received · Visa ••4242",
                source="billing",
                amount_cents=6000,
                refunded_cents=0,
            )
        )
        return TimelineSourceResult(entries=entries)


class Caller:
    def __init__(self) -> None:
        self.claims = AuthClaims(
            user_id="u-admin", email="a@example.test", academy_id=A, roles=("admin",)
        )

    def be(self, *roles: str, academy_id: str = A) -> None:
        self.claims = AuthClaims(
            user_id="u-x",
            email="x@example.test",
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

    async def claims() -> AuthClaims:
        _tenant.set(caller.claims.academy_id)
        return caller.claims

    app.dependency_overrides[get_auth_claims] = claims
    app.dependency_overrides[get_family_timeline] = lambda: GetFamilyTimeline(
        Directory(), Aliases(), [Entries()]
    )
    with TestClient(app) as c:
        yield c


def test_pages_the_timeline_newest_first(client: TestClient) -> None:
    first = client.get(f"{BASE}/p-1/timeline", params={"limit": 2})
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["family_id"] == "p-1"
    assert body["money_visible"] is True
    assert [e["entry_id"] for e in body["entries"]] == ["pay", "n0"]
    assert body["entries"][0]["amount_cents"] == 6000
    assert body["entries"][1]["detail"] == "note 0"
    second = client.get(
        f"{BASE}/p-1/timeline", params={"limit": 2, "before": body["next_cursor"]}
    ).json()
    assert [e["entry_id"] for e in second["entries"]] == ["n1", "n2"]
    assert second["next_cursor"] is None


def test_another_academys_family_is_a_404(client: TestClient, caller: Caller) -> None:
    caller.be("admin", academy_id=B)
    response = client.get(f"{BASE}/p-1/timeline")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "Crm.FamilyNotFound"


@pytest.mark.parametrize("roles", [("coach",), ("parent",), ("assistant_coach",), ("student",)])
def test_wrong_persona_gets_the_404(
    client: TestClient, caller: Caller, roles: tuple[str, ...]
) -> None:
    caller.be(*roles)
    assert client.get(f"{BASE}/p-1/timeline").status_code == 404


def test_a_bad_cursor_is_a_422(client: TestClient) -> None:
    assert client.get(f"{BASE}/p-1/timeline", params={"before": "nope"}).status_code == 422


def test_money_is_redacted_for_a_caller_who_may_not_see_it(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(family_timeline_routes, "can_view_family_money", lambda _claims: False)
    body = client.get(f"{BASE}/p-1/timeline").json()
    assert body["money_visible"] is False
    pay = body["entries"][0]
    assert pay["entry_id"] == "pay"
    assert pay["amount_cents"] is None and pay["refunded_cents"] is None
    assert pay["summary"] == "Payment received · Visa ••4242"
    assert "$" not in str(body)
