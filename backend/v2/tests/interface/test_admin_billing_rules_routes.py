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
    cancellation_effective_timing: str = "end_of_period"


@dataclass
class _Departure:
    drop_default_outcome: str = "no_credit_mid_month"


@dataclass
class _Ach:
    ach_discount_enabled: bool = False
    ach_discount_percent: float = 0
    max_ach_discount_percent: float = 3.0


class _Stores:
    def __init__(self) -> None:
        self.ach = _Ach()
        self.schedule = _Schedule(1, 7)
        self.fees = _Fees(0, 0)
        self.policy = _Policy(14, 0)
        self.departure = _Departure()
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
        self,
        *,
        cancellation_minimum_notice_days: int | None = None,
        cancellation_fee_cents: int | None = None,
        cancellation_effective_timing: str | None = None,
    ) -> _Policy:
        self.policy = _Policy(
            self.policy.cancellation_minimum_notice_days
            if cancellation_minimum_notice_days is None
            else cancellation_minimum_notice_days,
            self.policy.cancellation_fee_cents
            if cancellation_fee_cents is None
            else cancellation_fee_cents,
            self.policy.cancellation_effective_timing
            if cancellation_effective_timing is None
            else cancellation_effective_timing,
        )
        return self.policy

    async def read_departure(self) -> _Departure:
        return self.departure

    async def write_departure(self, *, drop_default_outcome: str | None = None) -> _Departure:
        self.departure = _Departure(
            self.departure.drop_default_outcome
            if drop_default_outcome is None
            else drop_default_outcome
        )
        return self.departure

    async def read_ach(self) -> _Ach:
        return self.ach

    async def write_ach(self, *, enabled: bool, percent: float) -> _Ach:
        self.ach = _Ach(enabled, percent, self.ach.max_ach_discount_percent)
        return self.ach

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
            drop_outcome=_Adapter(stores.read_departure),
            ach=_Adapter(stores.read_ach),
        ),
        write=UpdateBillingRules(
            schedule_reader=_Adapter(stores.read_schedule),
            schedule_writer=_Adapter(stores.write_schedule),
            fees_reader=_Adapter(stores.read_fees),
            fees_writer=_Adapter(stores.write_fees),
            cancellation_reader=_Adapter(stores.read_policy),
            cancellation_writer=_Adapter(stores.write_policy),
            drop_outcome_reader=_Adapter(stores.read_departure),
            drop_outcome_writer=_Adapter(stores.write_departure),
            ach_reader=_Adapter(stores.read_ach),
            ach_writer=_Adapter(stores.write_ach),
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
        # Issue #774: only the list-valued reminder_days row fills `values`.
        "values": None,
        "unit": "day_of_month",
        "min_value": 1,
        "max_value": 28,
        "enabled": None,
        "percent": None,
        "max_percent": None,
        "display": None,
        "detail": None,
        "choice": None,
        "choices": None,
    }
    assert _row(payload, "cancellation_effective_timing") == {
        "key": "cancellation_effective_timing",
        "label": "When a cancellation takes effect",
        "editable": True,
        "value": None,
        "values": None,
        "unit": None,
        "min_value": None,
        "max_value": None,
        "enabled": None,
        "percent": None,
        "max_percent": None,
        "display": None,
        "detail": None,
        "choice": "end_of_period",
        "choices": ["immediate", "end_of_period"],
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


def test_get_includes_drop_default_outcome_row() -> None:
    stores = _Stores()
    response = _client("admin", stores).get(ROUTE)

    assert response.status_code == 200, response.text
    row = _row(response.json(), "drop_default_outcome")
    assert row["editable"] is True
    assert row["choice"] == "no_credit_mid_month"
    assert row["choices"] == ["no_credit_mid_month", "credit_mid_month", "no_credit_end_of_period"]


def test_put_saves_drop_default_outcome_and_audits_it() -> None:
    stores = _Stores()
    response = _client("owner", stores).put(
        ROUTE, json={"drop_default_outcome": "credit_mid_month"}
    )

    assert response.status_code == 200, response.text
    assert stores.departure.drop_default_outcome == "credit_mid_month"
    assert stores.audit[-1].after == {"drop_default_outcome": "credit_mid_month"}


def test_put_drop_default_outcome_is_owner_only() -> None:
    stores = _Stores()
    response = _client("admin", stores).put(
        ROUTE, json={"drop_default_outcome": "credit_mid_month"}
    )

    assert response.status_code == 404
    assert stores.departure == _Departure()


def test_get_includes_the_ach_discount_row_for_an_admin() -> None:
    stores = _Stores()
    row = _row(_client("admin", stores).get(ROUTE).json(), "ach_discount")
    assert row["editable"] is True
    assert (row["enabled"], row["percent"], row["max_percent"]) == (False, 0.0, 3.0)
    assert "autopay" in row["detail"].lower()


def test_put_saves_ach_discount_and_audits_before_after() -> None:
    stores = _Stores()
    response = _client("owner", stores).put(
        ROUTE, json={"ach_discount": {"enabled": True, "percent": 2}}
    )

    assert response.status_code == 200, response.text
    assert stores.ach.ach_discount_enabled is True
    assert stores.ach.ach_discount_percent == 2
    entry = stores.audit[-1]
    assert entry.before == {"ach_discount": {"enabled": False, "percent": 0.0}}
    assert entry.after == {"ach_discount": {"enabled": True, "percent": 2.0}}


def test_put_ach_discount_is_owner_only() -> None:
    stores = _Stores()
    response = _client("admin", stores).put(
        ROUTE, json={"ach_discount": {"enabled": True, "percent": 2}}
    )

    assert response.status_code == 404
    assert stores.ach == _Ach()
    assert stores.audit == []


@pytest.mark.parametrize("percent", [0, 3.5, -1])
def test_put_ach_discount_422s_outside_the_ceiling(percent: float) -> None:
    stores = _Stores()
    response = _client("owner", stores).put(
        ROUTE, json={"ach_discount": {"enabled": True, "percent": percent}}
    )

    assert response.status_code == 422, response.text
    assert "ach_discount_percent" in response.text
    assert stores.ach == _Ach()


def test_put_ach_discount_rejects_an_attempt_to_write_the_ceiling() -> None:
    stores = _Stores()
    response = _client("owner", stores).put(
        ROUTE,
        json={"ach_discount": {"enabled": True, "percent": 2, "max_ach_discount_percent": 50}},
    )

    assert response.status_code == 422, response.text
    assert stores.ach == _Ach()
    top = _client("owner", stores).put(ROUTE, json={"max_ach_discount_percent": 50})
    assert top.status_code in (200, 422)
    assert stores.ach.max_ach_discount_percent == 3.0
