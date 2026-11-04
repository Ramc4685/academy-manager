"""Admin self-service policy BFF contract tests."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

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
        "can_report_absence": True,
        "can_request_makeup": True,
        "can_request_pause": True,
        "can_request_cancel": True,
        "can_claim_waitlist_offer": True,
        "payment_instructions": "",
        "welcome_email_absence_policy_default": "",
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


# --- Cancellation terms live only in Billing rules (Settings overhaul PR 5) --


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


def _wire(client: TestClient) -> _PolicyStore:
    store = _PolicyStore(
        ParentSelfServicePolicy(
            academy_id="acad",
            absence_notice_min_hours=2,
            makeup_expiry_days=30,
            cancellation_minimum_notice_days=7,
            cancellation_fee_cents=1_000,
        )
    )
    client.use_cases.self_service_policy = GetSelfServicePolicy(policies=store)  # type: ignore[attr-defined]
    client.use_cases.update_self_service_policy = UpdateSelfServicePolicy(policies=store)  # type: ignore[attr-defined]
    return store


@pytest.mark.parametrize("client_fixture", ["admin_client", "admin_only_client"])
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("cancellation_fee_cents", 5_000),
        ("cancellation_minimum_notice_days", 3),
        ("cancellation_effective_timing", "immediate"),
    ],
)
def test_self_service_no_longer_changes_the_cancellation_terms(
    request: pytest.FixtureRequest, client_fixture: str, field: str, value: int
) -> None:
    """Owner or not: Billing rules is the one place these are changed."""
    client = request.getfixturevalue(client_fixture)
    store = _wire(client)

    response = client.put(ROUTE, json={field: value, "absence_notice_min_hours": 9})

    assert response.status_code == 422, response.text
    assert response.json()["detail"]["field"] == field
    assert "Billing rules" in response.json()["detail"]["message"]
    # Nothing lands, not even the valid field sent beside it.
    assert store.field_writes == []
    assert store.policy.cancellation_fee_cents == 1_000
    assert store.policy.cancellation_minimum_notice_days == 7
    assert store.policy.cancellation_effective_timing == "end_of_period"


@pytest.mark.parametrize("client_fixture", ["admin_client", "admin_only_client"])
def test_a_full_resubmit_with_the_cancellation_terms_unchanged_still_saves(
    request: pytest.FixtureRequest, client_fixture: str
) -> None:
    """An old client that sends the whole object is not refused."""
    client = request.getfixturevalue(client_fixture)
    store = _wire(client)

    response = client.put(
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
    assert response.json()["cancellation_fee_cents"] == 1_000
    assert all("cancellation_fee_cents" not in w for w in store.field_writes)
    assert all("cancellation_minimum_notice_days" not in w for w in store.field_writes)
    assert all("cancellation_effective_timing" not in w for w in store.field_writes)


def test_put_can_turn_a_switch_off_without_touching_cancellation_terms(admin_only_client):
    store = _wire(admin_only_client)

    response = admin_only_client.put(ROUTE, json={"can_report_absence": False})

    assert response.status_code == 200, response.text
    assert response.json()["can_report_absence"] is False
    assert response.json()["can_request_makeup"] is True
    assert store.field_writes == [{"can_report_absence": False}]


def test_put_saves_and_clears_payment_instructions(admin_client):
    _wire(admin_client)

    on = admin_client.put(ROUTE, json={"payment_instructions": "Pay Sam by Venmo @sam-academy."})
    assert on.status_code == 200, on.text
    assert on.json()["payment_instructions"] == "Pay Sam by Venmo @sam-academy."

    cleared = admin_client.put(ROUTE, json={"payment_instructions": ""})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["payment_instructions"] == ""


def test_put_rejects_payment_instructions_over_max_length(admin_client):
    _wire(admin_client)

    response = admin_client.put(ROUTE, json={"payment_instructions": "x" * 1001})

    assert response.status_code == 422, response.text


def test_an_admin_without_owner_cannot_change_payment_instructions(admin_only_client):
    store = _wire(admin_only_client)

    response = admin_only_client.put(
        ROUTE, json={"payment_instructions": "Pay Sam by Venmo @sam-academy."}
    )

    assert response.status_code == 403, response.text
    assert response.json()["detail"] == "Only the academy owner can change payment instructions."
    assert store.field_writes == []


def test_an_admin_without_owner_can_resend_the_same_payment_instructions(admin_only_client):
    """Sending the unchanged value back is not a change and must not be refused."""
    store = _wire(admin_only_client)

    response = admin_only_client.put(
        ROUTE,
        json={
            "payment_instructions": store.policy.payment_instructions,
            "can_report_absence": False,
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["can_report_absence"] is False
    assert store.field_writes == [{"can_report_absence": False}]


def test_a_cleared_makeup_expiry_is_rejected(admin_client):
    store = _wire(admin_client)

    response = admin_client.put(ROUTE, json={"makeup_expiry_days": 0})

    assert response.status_code == 422, response.text
    assert store.field_writes == []
