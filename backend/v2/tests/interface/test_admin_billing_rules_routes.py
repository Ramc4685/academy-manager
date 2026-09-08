"""Interface tests for ``/admin/billing/rules``.

``GET`` is admin persona; ``PUT`` is owner only and 404s for a post-split
admin (the deliberate wrong-persona shape — see ``docs/security-matrix.md``).
The use cases themselves are covered by
``tests/application/test_billing_rules.py``; here they are real objects over
in-memory fakes so the wiring, the 422 shape and the owner gate are exercised
end to end.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.contexts.billing.application.use_cases.billing_rules import (
    BuildBillingRulesView,
    UpdateBillingRules,
)
from backend.v2.interfaces.admin.billing_rules_routes import get_admin_billing_rules
from backend.v2.interfaces.admin.router import router as admin_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers

ROUTE = "/api/v2/admin/billing/rules"


@dataclass
class _Schedule:
    billing_day: int
    invoice_due_days: int


@dataclass
class _Fees:
    late_fee_cents: int | None
    grace_days: int | None


@dataclass
class _Policy:
    cancellation_minimum_notice_days: int
    cancellation_fee_cents: int


class _Stores:
    def __init__(self) -> None:
        self.schedule = _Schedule(1, 7)
        self.fees = _Fees(0, 0)
        self.policy = _Policy(14, 0)
        self.audit: list[Any] = []

    async def read_schedule(self) -> _Schedule:
        return self.schedule

    async def write_schedule(self, cmd: Any) -> _Schedule:
        self.schedule = _Schedule(cmd.billing_day, cmd.invoice_due_days)
        return self.schedule

    async def read_fees(self, academy_id: str) -> _Fees:
        return self.fees

    async def write_fees(self, academy_id: str, fields: dict[str, Any]) -> _Fees:
        self.fees = _Fees(
            fields.get("late_fee_cents", self.fees.late_fee_cents),
            fields.get("grace_days", self.fees.grace_days),
        )
        return self.fees

    async def read_policy(self) -> _Policy:
        return self.policy

    async def write_policy(
        self, *, cancellation_minimum_notice_days: int, cancellation_fee_cents: int
    ) -> _Policy:
        self.policy = _Policy(cancellation_minimum_notice_days, cancellation_fee_cents)
        return self.policy

    async def append(self, entry: Any) -> None:
        self.audit.append(entry)


class _Adapter:
    def __init__(self, fn: Any) -> None:
        self.execute = fn


@dataclass
class _Rules:
    read: Any
    write: Any


def _rules(stores: _Stores) -> _Rules:
    return _Rules(
        read=BuildBillingRulesView(
            schedule=_Adapter(stores.read_schedule),
            fees=_Adapter(stores.read_fees),
            cancellation=_Adapter(stores.read_policy),
        ),
        write=UpdateBillingRules(
            schedule_reader=_Adapter(stores.read_schedule),
            schedule_writer=_Adapter(stores.write_schedule),
            fees_reader=_Adapter(stores.read_fees),
            fees_writer=_Adapter(stores.write_fees),
            cancellation_reader=_Adapter(stores.read_policy),
            cancellation_writer=_Adapter(stores.write_policy),
            audit=stores,
        ),
    )


def _claims(role: str) -> AuthClaims:
    roles: tuple[str, ...] = ("admin", "owner") if role == "owner" else (role,)
    return AuthClaims(
        user_id=f"u-{role}",
        email=f"{role}@example.com",
        academy_id="acad",
        roles=roles,  # type: ignore[arg-type]
    )


def _client(role: str, stores: _Stores) -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(admin_router, prefix="/api/v2")
    app.dependency_overrides[get_auth_claims] = lambda: _claims(role)
    app.dependency_overrides[get_admin_billing_rules] = lambda: _rules(stores)
    return TestClient(app)


def _row(payload: dict[str, Any], key: str) -> dict[str, Any]:
    for group in payload["groups"]:
        for row in group["rows"]:
            if row["key"] == key:
                return row
    raise KeyError(key)


def test_get_returns_the_four_boxes_for_an_admin() -> None:
    stores = _Stores()
    response = _client("admin", stores).get(ROUTE)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert [group["key"] for group in payload["groups"]] == [
        "monthly_invoicing",
        "late_payments",
        "leaving_and_pausing",
        "parent_messages",
    ]
    assert _row(payload, "billing_day") == {
        "key": "billing_day",
        "label": "Invoice day of month",
        "editable": True,
        "value": 1,
        "unit": "day_of_month",
        "min_value": 1,
        "max_value": 28,
        "display": None,
        "detail": None,
    }
    assert _row(payload, "retry_schedule")["editable"] is False


def test_get_wrong_persona_404() -> None:
    assert _client("coach", _Stores()).get(ROUTE).status_code == 404


def test_put_saves_only_the_changed_fields_for_an_owner() -> None:
    stores = _Stores()
    response = _client("owner", stores).put(
        ROUTE, json={"billing_day": 1, "late_fee_cents": 2500, "reason": "autumn review"}
    )

    assert response.status_code == 200, response.text
    assert _row(response.json(), "late_fee_cents")["value"] == 2500
    assert stores.schedule == _Schedule(1, 7)
    assert stores.fees.late_fee_cents == 2500
    assert len(stores.audit) == 1
    entry = stores.audit[0]
    assert entry.action == "billing_rules_changed"
    assert entry.actor_id == "u-owner"
    assert entry.reason == "autumn review"
    assert entry.after == {"late_fee_cents": 2500}


def test_put_is_owner_only_and_404s_for_an_admin_without_owner() -> None:
    stores = _Stores()
    response = _client("admin", stores).put(ROUTE, json={"billing_day": 9})

    assert response.status_code == 404
    assert stores.schedule == _Schedule(1, 7)
    assert stores.audit == []


def test_put_wrong_persona_404() -> None:
    assert _client("coach", _Stores()).put(ROUTE, json={"billing_day": 9}).status_code == 404


def test_put_no_op_writes_no_audit_entry() -> None:
    stores = _Stores()
    response = _client("owner", stores).put(ROUTE, json={"billing_day": 1, "invoice_due_days": 7})

    assert response.status_code == 200, response.text
    assert stores.audit == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("billing_day", 29),
        ("invoice_due_days", 61),
        ("grace_days", 61),
        ("late_fee_cents", -1),
        ("cancellation_minimum_notice_days", 91),
        ("cancellation_fee_cents", 100_001),
    ],
)
def test_put_422s_per_bound_and_names_the_field(field: str, value: int) -> None:
    stores = _Stores()
    response = _client("owner", stores).put(ROUTE, json={field: value})

    assert response.status_code == 422, response.text
    assert field in response.text
    assert stores.audit == []
    assert stores.schedule == _Schedule(1, 7)
    assert stores.fees == _Fees(0, 0)
    assert stores.policy == _Policy(14, 0)


def test_put_rejects_a_bad_field_before_saving_a_good_one() -> None:
    """A bad late fee must not leave a saved billing day behind it."""
    stores = _Stores()
    response = _client("owner", stores).put(ROUTE, json={"billing_day": 15, "late_fee_cents": -1})

    assert response.status_code == 422, response.text
    assert stores.schedule == _Schedule(1, 7)
