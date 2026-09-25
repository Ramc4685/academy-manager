"""Admin self-service policy BFF contract tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from backend.v2.composition.billing_rules import _CancellationPolicyAdapter
from backend.v2.contexts.billing.application.use_cases.billing_rules import UpdateBillingRules
from backend.v2.contexts.enrollment.application.use_cases.self_service_policies import (
    GetSelfServicePolicy,
    UpdateSelfServicePolicy,
)
from backend.v2.contexts.enrollment.domain.self_service import ParentSelfServicePolicy

ROUTE = "/api/v2/admin/self-service/policy"


def test_get_self_service_policy_returns_defaults(admin_client):
    admin_client.use_cases.self_service_policy = AsyncMock()
    admin_client.use_cases.self_service_policy.execute.return_value = (
        ParentSelfServicePolicy.default("acad")
    )

    response = admin_client.get("/api/v2/admin/self-service/policy")

    assert response.status_code == 200, response.text
    assert response.json() == {
        "absence_notice_min_hours": 2,
        "makeup_expiry_days": 30,
        "makeup_requires_notice": True,
        "cancellation_minimum_notice_days": 7,
        "cancellation_fee_cents": 0,
        "cancellation_effective_timing": "end_of_period",
    }


def test_put_self_service_policy_rejects_negative_values(admin_client):
    admin_client.use_cases.update_self_service_policy = AsyncMock()

    response = admin_client.put(
        "/api/v2/admin/self-service/policy",
        json={
            "absence_notice_min_hours": -1,
            "makeup_expiry_days": 30,
            "makeup_requires_notice": True,
            "cancellation_minimum_notice_days": 7,
            "cancellation_fee_cents": 0,
            "cancellation_effective_timing": "end_of_period",
        },
    )

    assert response.status_code == 422, response.text
    admin_client.use_cases.update_self_service_policy.execute.assert_not_awaited()


def test_self_service_policy_wrong_persona_404(coach_on_admin_client, parent_on_admin_client):
    assert coach_on_admin_client.get("/api/v2/admin/self-service/policy").status_code == 404
    assert parent_on_admin_client.get("/api/v2/admin/self-service/policy").status_code == 404


# --- Owner gate, bounds, audit and partial writes (money audit X5) ----------


class _PolicyStore:
    """In-memory policy store with the Mongo repo's partial ``$set`` semantics."""

    def __init__(self, policy: ParentSelfServicePolicy) -> None:
        self.policy = policy
        self.field_writes: list[dict[str, Any]] = []

    async def get_or_default(self) -> ParentSelfServicePolicy:
        return self.policy

    async def save(self, policy: ParentSelfServicePolicy) -> None:  # pragma: no cover
        raise AssertionError("whole-object save must not be used")

    async def update_fields(self, fields: dict[str, Any]) -> None:
        self.field_writes.append(dict(fields))
        self.policy = self.policy.model_copy(update=fields)


@dataclass
class _Schedule:
    billing_day: int = 1
    invoice_due_days: int = 7


@dataclass
class _Fees:
    late_fee_cents: int | None = 0
    grace_days: int | None = 0


class _Fn:
    def __init__(self, fn: Any) -> None:
        self.execute = fn


class _Audit:
    def __init__(self) -> None:
        self.entries: list[Any] = []

    async def append(self, entry: Any) -> None:
        self.entries.append(entry)


@dataclass
class _Rules:
    read: Any
    write: Any


def _wire(client: TestClient) -> tuple[_PolicyStore, _Audit]:
    store = _PolicyStore(
        ParentSelfServicePolicy(
            academy_id="acad",
            absence_notice_min_hours=2,
            makeup_expiry_days=30,
            cancellation_minimum_notice_days=7,
            cancellation_fee_cents=1_000,
        )
    )
    audit = _Audit()
    reader = GetSelfServicePolicy(policies=store)
    writer = UpdateSelfServicePolicy(policies=store)
    client.use_cases.self_service_policy = reader  # type: ignore[attr-defined]
    client.use_cases.update_self_service_policy = writer  # type: ignore[attr-defined]

    async def _schedule() -> _Schedule:
        return _Schedule()

    async def _fees(academy_id: str) -> _Fees:
        return _Fees()

    async def _unused(*args: Any, **kwargs: Any) -> Any:  # pragma: no cover
        raise AssertionError("only the cancellation store may be written")

    client.app.state.admin_billing_rules = _Rules(  # type: ignore[attr-defined]
        read=None,
        write=UpdateBillingRules(
            schedule_reader=_Fn(_schedule),
            schedule_writer=_Fn(_unused),
            fees_reader=_Fn(_fees),
            fees_writer=_Fn(_unused),
            cancellation_reader=reader,
            cancellation_writer=_CancellationPolicyAdapter(reader=reader, writer=writer),
            audit=audit,
        ),
    )
    return store, audit


def test_an_admin_without_owner_cannot_change_the_cancellation_fee(admin_only_client):
    store, audit = _wire(admin_only_client)

    response = admin_only_client.put(ROUTE, json={"cancellation_fee_cents": 5_000})

    assert response.status_code == 403, response.text
    assert store.field_writes == []
    assert store.policy.cancellation_fee_cents == 1_000
    assert audit.entries == []


def test_an_admin_without_owner_can_still_save_absence_settings(admin_only_client):
    """An old client that sends the whole object with the cancellation values
    unchanged is not a cancellation change and must not be refused."""
    store, audit = _wire(admin_only_client)

    response = admin_only_client.put(
        ROUTE,
        json={
            "absence_notice_min_hours": 6,
            "makeup_expiry_days": 30,
            "makeup_requires_notice": True,
            "cancellation_minimum_notice_days": 7,
            "cancellation_fee_cents": 1_000,
            "cancellation_effective_timing": "end_of_period",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["absence_notice_min_hours"] == 6
    assert all("cancellation_fee_cents" not in w for w in store.field_writes)
    assert audit.entries == []


@pytest.mark.parametrize(
    ("field", "value"),
    [("cancellation_fee_cents", 100_001), ("cancellation_minimum_notice_days", 91)],
)
def test_cancellation_terms_are_bounded_like_billing_rules(admin_client, field, value):
    store, audit = _wire(admin_client)

    response = admin_client.put(ROUTE, json={field: value, "absence_notice_min_hours": 9})

    assert response.status_code == 422, response.text
    assert field in response.text
    # Nothing lands, not even the valid field sent beside it.
    assert store.field_writes == []
    assert audit.entries == []


def test_an_owner_change_to_the_cancellation_fee_is_audited_and_partial(admin_client):
    store, audit = _wire(admin_client)

    response = admin_client.put(ROUTE, json={"cancellation_fee_cents": 2_500})

    assert response.status_code == 200, response.text
    assert response.json()["cancellation_fee_cents"] == 2_500
    assert response.json()["absence_notice_min_hours"] == 2
    assert store.field_writes == [{"cancellation_fee_cents": 2_500}]
    [entry] = audit.entries
    assert entry.action == "billing_rules_changed"
    assert entry.actor_id == "u-admin"
    assert entry.before == {"cancellation_fee_cents": 1_000}
    assert entry.after == {"cancellation_fee_cents": 2_500}
    assert entry.reason == "Settings -> Self-service"


def test_a_cleared_makeup_expiry_is_rejected(admin_client):
    store, _ = _wire(admin_client)

    response = admin_client.put(ROUTE, json={"makeup_expiry_days": 0})

    assert response.status_code == 422, response.text
    assert store.field_writes == []
