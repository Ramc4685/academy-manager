"""Money is owner-only (Settings overhaul Phase 1 PR 5).

Only the academy owner may change what families are charged or when a billing
month starts. This file walks every admin write path that does that and pins
two contracts:

* **Owner-only routes** (the whole route sets money) sit behind
  ``require_owner`` and 404 for an admin without ``owner``, like every other
  owner-only route (``owner_gate.OWNER_ONLY_ROUTE_PATHS``).
* **Mixed forms** (the class form, the Academy panel) stay admin routes; an
  admin is refused with **403** and a plain message only when the request
  changes a money field. Resubmitting the stored value is not a change.

The Self-service tab no longer writes the cancellation fee or notice at all;
see ``test_admin_self_service_policies.py``.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

import backend.v2.composition.admin as admin_composition
from backend.v2.contexts.identity.application.get_academy_use_case import GetAcademyOutput
from backend.v2.interfaces.admin.owner_gate import (
    CURRENCY_CHANGE_FORBIDDEN,
    OWNER_ONLY_ROUTE_PATHS,
    PRICE_CHANGE_FORBIDDEN,
    TIMEZONE_CHANGE_FORBIDDEN,
)
from backend.v2.tests.interface.test_admin_session_types import _install_session_type_fakes
from backend.v2.tests.interface.test_admin_sessions import (
    _FrozenAdminDateTime,
    _mongo_admin_app,
)

_ADMIN = "/api/v2/admin"

#: Every admin write that sets a price, fee, discount or billing timing and is
#: owner-only as a whole route. Each must be in OWNER_ONLY_ROUTE_PATHS, which
#: ``tests/structural/test_owner_gate_policy.py`` ties to ``require_owner``.
OWNER_ONLY_MONEY_WRITES: tuple[tuple[str, str], ...] = (
    # Price list (new in PR 5).
    ("POST", "/session-types"),
    ("PATCH", "/session-types/type-new"),
    ("DELETE", "/session-types/type-new"),
    # Already owner-only before PR 5, listed so the walk is complete.
    ("PUT", "/billing/rules"),  # late fee, grace, cancellation fee + notice
    ("PATCH", "/academy/fees"),  # late fee (legacy route)
    ("PUT", "/billing/settings/invoice-schedule"),  # billing day, due days
    ("POST", "/billing/products"),
    ("PATCH", "/billing/products/prod-1"),
    ("DELETE", "/billing/products/prod-1"),
    ("POST", "/billing-enrollments/bill-1/override"),  # per-student price
    ("POST", "/enrollments/enr-1/fee"),  # per-enrollment fee
    ("PUT", "/enrollments/enr-1/tuition-discount"),
    ("DELETE", "/enrollments/enr-1/tuition-discount"),
    ("POST", "/payments/pay-1/discount"),
)


def _template(path: str) -> str:
    replacements = {
        "type-new": "{session_type_id}",
        "prod-1": "{product_id}",
        "bill-1": "{enrollment_id}",
        "enr-1": "{enrollment_id}",
        "pay-1": "{payment_id}",
    }
    for concrete, placeholder in replacements.items():
        path = path.replace(concrete, placeholder)
    return f"{_ADMIN}{path}"


@pytest.mark.parametrize(("method", "path"), OWNER_ONLY_MONEY_WRITES)
def test_every_owner_only_money_write_is_declared_owner_only(method: str, path: str) -> None:
    assert (method, _template(path)) in OWNER_ONLY_ROUTE_PATHS


@pytest.mark.parametrize(("method", "path"), OWNER_ONLY_MONEY_WRITES)
def test_an_admin_without_owner_is_refused_every_owner_only_money_write(
    admin_only_client: TestClient, method: str, path: str
) -> None:
    response = admin_only_client.request(method, f"{_ADMIN}{path}", json={})
    assert response.status_code == 404, response.text


def test_the_owner_can_write_the_price_list(admin_client: TestClient) -> None:
    _install_session_type_fakes(admin_client)

    created = admin_client.post(
        f"{_ADMIN}/session-types",
        json={"name": "Elite", "price_cents": 20_000, "billing_period": "monthly"},
    )
    updated = admin_client.patch(f"{_ADMIN}/session-types/type-new", json={"price_cents": 21_000})
    deleted = admin_client.delete(f"{_ADMIN}/session-types/type-new")

    assert created.status_code == 201, created.text
    assert updated.status_code == 200, updated.text
    assert deleted.status_code == 204, deleted.text


def test_an_admin_without_owner_can_still_read_the_price_list(
    admin_only_client: TestClient,
) -> None:
    _install_session_type_fakes(admin_only_client)
    response = admin_only_client.get(f"{_ADMIN}/session-types")
    assert response.status_code == 200, response.text


# --- Class monthly fee (mixed form) -----------------------------------------

_CLASS = {
    "coach_id": "coach-fee",
    "title": "Beginner Monthly",
    "location": "Court 1",
    "days_of_week": ["Wed"],
    "start_time": "18:00",
    "end_time": "18:45",
    "timezone": "America/Chicago",
    "capacity": 15,
}


@pytest.fixture
def mongo_db(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setattr(admin_composition, "datetime", _FrozenAdminDateTime)
    mongomock_motor = pytest.importorskip("mongomock_motor")
    return mongomock_motor.AsyncMongoMockClient()["money-owner-only"]


def _create_class(db: Any, **extra: Any) -> dict[str, Any]:
    with TestClient(_mongo_admin_app(db)) as owner:
        response = owner.post(f"{_ADMIN}/sessions", json={**_CLASS, **extra})
    assert response.status_code == 200, response.text
    return response.json()


async def _stored(db: Any, session_id: str) -> dict[str, Any]:
    row = await db.sessions.find_one({"academy_id": "academy-b", "session_id": session_id})
    assert row is not None
    return row


@pytest.mark.parametrize("amount_cents", [6_000, 0])
def test_an_admin_cannot_create_a_priced_class(mongo_db: Any, amount_cents: int) -> None:
    with TestClient(_mongo_admin_app(mongo_db, roles=("admin",))) as admin:
        response = admin.post(f"{_ADMIN}/sessions", json={**_CLASS, "amount_cents": amount_cents})

    assert response.status_code == 403, response.text
    assert response.json()["detail"] == PRICE_CHANGE_FORBIDDEN


@pytest.mark.asyncio
async def test_an_admin_can_create_an_unpriced_class(mongo_db: Any) -> None:
    """No fee is what an owner's class starts with too; the owner prices it."""
    with TestClient(_mongo_admin_app(mongo_db, roles=("admin",))) as admin:
        response = admin.post(f"{_ADMIN}/sessions", json=_CLASS)

    assert response.status_code == 200, response.text
    assert response.json()["amount_cents"] is None


@pytest.mark.asyncio
async def test_an_admin_cannot_change_a_class_fee(mongo_db: Any) -> None:
    created = _create_class(mongo_db, amount_cents=6_000)

    with TestClient(_mongo_admin_app(mongo_db, roles=("admin",))) as admin:
        raised = admin.patch(
            f"{_ADMIN}/sessions/{created['session_id']}", json={"amount_cents": 7_500}
        )
        cleared = admin.patch(
            f"{_ADMIN}/sessions/{created['session_id']}", json={"amount_cents": None}
        )

    assert raised.status_code == 403, raised.text
    assert raised.json()["detail"] == PRICE_CHANGE_FORBIDDEN
    assert cleared.status_code == 403, cleared.text
    assert (await _stored(mongo_db, created["session_id"]))["amount_cents"] == 6_000
    assert await mongo_db.billing_audit_log.count_documents({}) == 0


@pytest.mark.asyncio
async def test_an_admin_full_form_resubmit_with_the_fee_unchanged_saves(mongo_db: Any) -> None:
    created = _create_class(mongo_db, amount_cents=6_000)

    with TestClient(_mongo_admin_app(mongo_db, roles=("admin",))) as admin:
        response = admin.patch(
            f"{_ADMIN}/sessions/{created['session_id']}",
            json={**_CLASS, "title": "Beginner Monthly (Wed)", "amount_cents": 6_000},
        )

    assert response.status_code == 200, response.text
    stored = await _stored(mongo_db, created["session_id"])
    assert stored["title"] == "Beginner Monthly (Wed)"
    assert stored["amount_cents"] == 6_000
    assert await mongo_db.billing_audit_log.count_documents({}) == 0


@pytest.mark.asyncio
async def test_an_admin_resubmitting_an_unpriced_class_saves(mongo_db: Any) -> None:
    created = _create_class(mongo_db)

    with TestClient(_mongo_admin_app(mongo_db, roles=("admin",))) as admin:
        response = admin.patch(
            f"{_ADMIN}/sessions/{created['session_id']}",
            json={"capacity": 12, "amount_cents": None},
        )

    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_an_owner_fee_change_saves_and_is_audited(mongo_db: Any) -> None:
    created = _create_class(mongo_db, amount_cents=6_000)

    with TestClient(_mongo_admin_app(mongo_db)) as owner:
        response = owner.patch(
            f"{_ADMIN}/sessions/{created['session_id']}",
            json={"amount_cents": 7_500, "reason": "new season price"},
        )

    assert response.status_code == 200, response.text
    assert (await _stored(mongo_db, created["session_id"]))["amount_cents"] == 7_500
    entry = await mongo_db.billing_audit_log.find_one({"academy_id": "academy-b"})
    assert entry is not None
    assert entry["action"] == "session_fee_changed"
    assert entry["actor_id"] == "admin-1"
    assert entry["reason"] == "new season price"
    assert entry["before"] == {"session_id": created["session_id"], "amount_cents": 6_000}
    assert entry["after"] == {"session_id": created["session_id"], "amount_cents": 7_500}


@pytest.mark.asyncio
async def test_an_owner_edit_that_keeps_the_fee_writes_no_audit(mongo_db: Any) -> None:
    created = _create_class(mongo_db, amount_cents=6_000)

    with TestClient(_mongo_admin_app(mongo_db)) as owner:
        response = owner.patch(
            f"{_ADMIN}/sessions/{created['session_id']}",
            json={"capacity": 10, "amount_cents": 6_000},
        )

    assert response.status_code == 200, response.text
    assert await mongo_db.billing_audit_log.count_documents({}) == 0


# --- Academy timezone and currency (mixed form) ------------------------------


class _AuditSpy:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def execute(self, **kwargs: Any) -> bool:
        self.calls.append(kwargs)
        return True


def _stored_academy(client: TestClient, **overrides: Any) -> _AuditSpy:
    current = GetAcademyOutput(
        academy_id="acad",
        display_name="Court 7",
        timezone="America/Chicago",
        currency="USD",
    )
    client.use_cases.get_academy_use_case.execute = AsyncMock(return_value=current)  # type: ignore[attr-defined]
    client.use_cases.update_academy_use_case.execute = AsyncMock(  # type: ignore[attr-defined]
        return_value=GetAcademyOutput(
            academy_id="acad",
            display_name="Court 7",
            timezone=overrides.get("timezone", "America/Chicago"),
            currency=overrides.get("currency", "USD"),
        )
    )
    spy = _AuditSpy()
    client.use_cases.record_money_setting_change = spy  # type: ignore[attr-defined]
    return spy


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({"timezone": "America/New_York"}, TIMEZONE_CHANGE_FORBIDDEN),
        ({"timezone": None}, TIMEZONE_CHANGE_FORBIDDEN),
        ({"currency": "CAD"}, CURRENCY_CHANGE_FORBIDDEN),
        ({"display_name": "Court 8", "timezone": "UTC"}, TIMEZONE_CHANGE_FORBIDDEN),
    ],
)
def test_an_admin_cannot_change_the_timezone_or_currency(
    admin_only_client: TestClient, body: dict[str, Any], message: str
) -> None:
    spy = _stored_academy(admin_only_client)

    response = admin_only_client.patch(f"{_ADMIN}/academy", json=body)

    assert response.status_code == 403, response.text
    assert response.json()["detail"] == message
    admin_only_client.use_cases.update_academy_use_case.execute.assert_not_awaited()  # type: ignore[attr-defined]
    assert spy.calls == []


def test_an_admin_resubmitting_the_stored_timezone_and_currency_saves(
    admin_only_client: TestClient,
) -> None:
    _stored_academy(admin_only_client)

    response = admin_only_client.patch(
        f"{_ADMIN}/academy",
        json={"display_name": "Court 8", "timezone": "America/Chicago", "currency": "usd"},
    )

    assert response.status_code == 200, response.text
    admin_only_client.use_cases.update_academy_use_case.execute.assert_awaited_once()  # type: ignore[attr-defined]


def test_an_admin_can_still_edit_the_other_academy_fields(admin_only_client: TestClient) -> None:
    _stored_academy(admin_only_client)

    response = admin_only_client.patch(f"{_ADMIN}/academy", json={"hours_text": "Mon-Fri 4-8"})

    assert response.status_code == 200, response.text


def test_an_owner_timezone_change_saves_and_is_audited(admin_client: TestClient) -> None:
    spy = _stored_academy(admin_client, timezone="America/New_York")

    response = admin_client.patch(f"{_ADMIN}/academy", json={"timezone": "America/New_York"})

    assert response.status_code == 200, response.text
    assert response.json()["timezone"] == "America/New_York"
    [call] = spy.calls
    assert call["action"] == "academy_timezone_changed"
    assert call["before"] == {"timezone": "America/Chicago"}
    assert call["after"] == {"timezone": "America/New_York"}
    assert call["actor_id"] == "u-admin"


def test_an_owner_currency_change_saves(admin_client: TestClient) -> None:
    spy = _stored_academy(admin_client, currency="CAD")

    response = admin_client.patch(f"{_ADMIN}/academy", json={"currency": "CAD"})

    assert response.status_code == 200, response.text
    assert spy.calls == []
