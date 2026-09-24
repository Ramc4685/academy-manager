"""Staff money tiers on the admin money routes (#553), per route and per role.

Owner decision 2026-09-22 (roadmap section 6 item 2):

* record a payment the family already made (``record-payment``, ``mark-paid``):
  owner, admin or billing;
* every money-moving route (refund, void, discount, undo-paid, adjustments,
  fees, card charges): owner only;
* front desk: no money write at all.

Every miss is a 404 that never reaches the use case, like every persona guard.
The matrix runs the real admin router with only the auth claims and the use
cases replaced.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from backend.v2.tests.interface.conftest import (  # type: ignore[attr-defined]
    _build_admin_use_cases,
    _claims,
    _make_admin_app,
)
from backend.v2.tests.structural.test_money_route_staff_tiers import MONEY_MOVING_ROUTES

_RECORD_PAYMENT = "/api/v2/admin/billing/invoices/inv-1/record-payment"
_MARK_PAID = "/api/v2/admin/payments/pay-1/mark-paid"
_RECORD_BODY = {"amount_cents": 2_500, "payment_method": "check", "reference_number": "1001"}
_MARK_BODY = {"payment_method": "cash", "notes": "desk", "payment_date": "2026-09-01"}

#: _claims(role) roles: "admin" is a pre-split admin (admin + owner),
#: "admin-only" an admin invited after the split, the rest hold only that role.
RECORDERS = ("admin", "admin-only", "owner", "billing")
NON_RECORDERS = ("front_desk", "coach", "assistant_coach", "parent", "student")
NON_OWNERS = ("admin-only", "billing", "front_desk", "coach", "parent")

_PATH_IDS = {
    "{invoice_id}": "inv-1",
    "{payment_id}": "pay-1",
    "{enrollment_id}": "enr-1",
    "{parent_id}": "parent-1",
}


def _concrete(path: str) -> str:
    for placeholder, value in _PATH_IDS.items():
        path = path.replace(placeholder, value)
    return path


class _Stubs:
    def __init__(self) -> None:
        self.record_manual_payment = AsyncMock(
            return_value={
                "invoice_id": "inv-1",
                "payment_id": "manual-1",
                "invoice_status": "partially_paid",
                "balance_due_cents": 2_500,
            }
        )
        self.mark_paid = AsyncMock(return_value=None)

    def awaited(self) -> bool:
        return self.record_manual_payment.await_count > 0 or self.mark_paid.await_count > 0


@pytest.fixture
def client_for(admin_seed: Any) -> Iterator[Any]:
    clients: list[TestClient] = []

    def _make(role: str) -> tuple[TestClient, _Stubs]:
        stubs = _Stubs()
        use_cases = dataclasses.replace(
            _build_admin_use_cases(admin_seed),
            record_manual_payment=stubs.record_manual_payment,
        )
        # mark_payment_paid is a use case object; swap only its execute.
        use_cases.mark_payment_paid.execute = stubs.mark_paid  # type: ignore[method-assign]
        client = TestClient(_make_admin_app(_claims(role), use_cases))
        client.__enter__()
        clients.append(client)
        return client, stubs

    yield _make
    for client in clients:
        client.__exit__(None, None, None)


@pytest.mark.parametrize("role", RECORDERS)
def test_payment_recorders_can_record_a_manual_payment(client_for, role: str) -> None:
    client, stubs = client_for(role)

    r = client.post(_RECORD_PAYMENT, json=_RECORD_BODY, headers={"Idempotency-Key": "k-1"})

    assert r.status_code == 201, r.text
    kwargs = stubs.record_manual_payment.await_args.kwargs
    assert kwargs["actor_id"] == f"u-{role}"
    assert kwargs["invoice_id"] == "inv-1"


@pytest.mark.parametrize("role", RECORDERS)
def test_payment_recorders_can_mark_a_payment_paid(client_for, role: str) -> None:
    client, stubs = client_for(role)

    r = client.post(_MARK_PAID, json=_MARK_BODY)

    assert r.status_code == 200, r.text
    command = stubs.mark_paid.await_args.args[0]
    assert command.payment_id == "pay-1"
    assert command.recorded_by == f"u-{role}"


@pytest.mark.parametrize("role", NON_RECORDERS)
@pytest.mark.parametrize(
    ("path", "body"),
    [(_RECORD_PAYMENT, _RECORD_BODY), (_MARK_PAID, _MARK_BODY)],
    ids=["record-payment", "mark-paid"],
)
def test_everyone_else_gets_404_on_payment_recording(
    client_for, role: str, path: str, body: dict[str, Any]
) -> None:
    client, stubs = client_for(role)

    r = client.post(path, json=body)

    assert r.status_code == 404
    assert not stubs.awaited()


@pytest.mark.parametrize("role", NON_OWNERS)
@pytest.mark.parametrize(
    ("method", "path"), MONEY_MOVING_ROUTES, ids=lambda v: v if isinstance(v, str) else None
)
def test_money_moving_routes_404_for_every_non_owner(
    client_for, role: str, method: str, path: str
) -> None:
    client, stubs = client_for(role)

    r = client.request(method, _concrete(path), json={})

    assert r.status_code == 404, f"{role} reached {method} {path}: {r.status_code}"
    assert not stubs.awaited()


@pytest.mark.parametrize("role", ("billing", "front_desk"))
@pytest.mark.parametrize(
    ("method", "path"),
    [
        # Operations routes stay admin-only: a staff tier opens only its own.
        ("GET", "/api/v2/admin/payments"),
        ("GET", "/api/v2/admin/finance/expenses"),
        ("POST", "/api/v2/admin/billing/invoices/inv-1/void"),
        ("GET", "/api/v2/admin/families"),
        ("GET", "/api/v2/admin/users"),
    ],
)
def test_staff_tiers_do_not_reach_admin_only_routes(
    client_for, role: str, method: str, path: str
) -> None:
    client, _ = client_for(role)

    r = client.request(method, path, json={"reason": "x"} if method == "POST" else None)

    assert r.status_code == 404


@pytest.mark.parametrize("role", ("billing", "front_desk"))
def test_only_the_owner_grants_a_staff_tier(client_for, role: str) -> None:
    admin_only, _ = client_for("admin-only")
    owner, _ = client_for("admin")

    refused = admin_only.post(
        "/api/v2/admin/users/coach-1/roles", json={"role": role, "reason": "new hire"}
    )
    granted = owner.post(
        "/api/v2/admin/users/coach-1/roles", json={"role": role, "reason": "new hire"}
    )

    assert refused.status_code == 403
    assert "academy owner" in refused.json()["detail"]
    assert granted.status_code == 200, granted.text
    assert role in granted.json()["roles"]


@pytest.mark.parametrize("role", ("billing", "front_desk"))
def test_only_the_owner_creates_a_staff_tier_user(client_for, role: str) -> None:
    admin_only, _ = client_for("admin-only")

    r = admin_only.post(
        "/api/v2/admin/users",
        json={
            "role": role,
            "display_name": "Desk Person",
            "email": "desk-person@example.com",
            "reason": "hire",
        },
    )

    assert r.status_code == 403
