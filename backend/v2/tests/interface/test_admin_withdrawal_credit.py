"""Withdrawal credit routes (issue #670: one withdraw path).

The old owner-only ``.../withdrawal-credit/approve`` route is gone; the credit
outcome now rides ``POST /enrollments/{id}/withdraw`` with an action-level
owner check. The preview route is unchanged.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient


def _enroll(client: Any) -> str:
    created = client.post(
        "/api/v2/admin/enrollments",
        json={
            "session_id": "sess-1",
            "student_id": "st-1",
            "parent_id": "p-1",
            "full_name": "Alice",
        },
    )
    assert created.status_code == 200, created.text
    return created.json()["enrollment_id"]


def _withdraw(client: Any, enrollment_id: str, outcome: str, reason: str = "Relocation"):
    return client.post(
        f"/api/v2/admin/enrollments/{enrollment_id}/withdraw",
        json={"effective_date": "2026-05-20", "reason": reason, "outcome": outcome},
    )


def test_admin_preview_withdrawal_credit(admin_client) -> None:
    response = admin_client.post(
        "/api/v2/admin/enrollments/enroll-1/withdrawal-credit/preview",
        json={"withdrawal_date": "2026-05-20T00:00:00Z"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["credit_amount_cents"] == 3750
    assert body["display_amount"] == "$37.50"
    assert body["total_classes"] == 8
    assert body["unused_classes"] == 3


def test_owner_withdraw_with_credit_issues_one_credit_through_the_single_path(
    admin_client,
) -> None:
    enrollment_id = _enroll(admin_client)
    seats_before = admin_client.seed["sessions"].reserved.get("sess-1", 0)

    response = _withdraw(admin_client, enrollment_id, "credit")

    assert response.status_code == 204, response.text
    seed = admin_client.seed
    assert seed["enrollments"].rows[enrollment_id].status == "withdrawn"
    decision = seed["withdrawal_decision"]
    assert [c["outcome"] for c in decision.calls] == ["credit"]
    assert decision.calls[0]["actor_id"] == "u-admin"
    assert decision.calls[0]["reason"] == "Relocation"
    assert decision.calls[0]["effective_at"].date().isoformat() == "2026-05-20"
    event = seed["enrollment_events"].rows[-1]
    assert event.event_type == "dropped"  # Issue #699: renamed from "withdrawn"
    assert event.billing_policy == "early_withdrawal_credit"
    assert event.billing_result.startswith("credit_approved")
    assert event.credit_id == f"credit-{enrollment_id}"
    # the seat is released and offered to the waitlist
    assert seed["sessions"].reserved["sess-1"] == seats_before - 1
    cancelled = [e for e in seed["outbox"].events if e.name == "Enrollment.EnrollmentCancelled"]
    assert [e.payload.enrollment_id for e in cancelled] == [enrollment_id]


def test_second_withdraw_is_a_409_conflict(admin_client) -> None:
    enrollment_id = _enroll(admin_client)
    assert _withdraw(admin_client, enrollment_id, "credit").status_code == 204

    response = _withdraw(admin_client, enrollment_id, "refund")

    assert response.status_code == 409, response.text
    body = response.json()["error"]
    assert body["code"] == "Enrollment.NotWithdrawable"
    assert "already withdrawn" in body["message"]
    seed = admin_client.seed
    assert len(seed["withdrawal_decision"].calls) == 1
    assert len([e for e in seed["enrollment_events"].rows if e.event_type == "dropped"]) == 1  # Issue #699


def test_plain_admin_cannot_withdraw_with_credit_outcome(admin_only_client) -> None:
    """Same answer the old owner-only approve route gave: 404, nothing written."""
    enrollment_id = _enroll(admin_only_client)

    response = _withdraw(admin_only_client, enrollment_id, "credit")

    assert response.status_code == 404
    seed = admin_only_client.seed
    assert seed["enrollments"].rows[enrollment_id].status == "active"
    assert seed["withdrawal_decision"].calls == []


def test_plain_admin_can_still_withdraw_with_refund_or_adjustment(admin_only_client) -> None:
    enrollment_id = _enroll(admin_only_client)

    response = _withdraw(admin_only_client, enrollment_id, "adjustment")

    assert response.status_code == 204, response.text
    event = admin_only_client.seed["enrollment_events"].rows[-1]
    assert event.billing_policy == "withdrawal_adjustment"
    assert event.billing_result.startswith("adjustment_manual")
    assert event.credit_id is None


def test_old_approve_route_is_gone(admin_client) -> None:
    response = admin_client.post(
        "/api/v2/admin/enrollments/enroll-1/withdrawal-credit/approve",
        json={"withdrawal_date": "2026-05-20T00:00:00Z", "admin_note": "Relocation"},
    )

    assert response.status_code == 404


def test_parent_cannot_use_admin_withdrawal_credit(parent_on_admin_client) -> None:
    response = parent_on_admin_client.post(
        "/api/v2/admin/enrollments/enroll-1/withdrawal-credit/preview",
        json={"withdrawal_date": "2026-05-20T00:00:00Z"},
    )

    assert response.status_code == 404


# --- the route over the REAL composed decision adapter (issue #670 review) ---
#
# Every test above stubs the decision port, so the route never met the real
# `RecordWithdrawalDecision`. That is exactly how "withdraw 404s for a family
# with no legacy paid payment" shipped green. These two run the composed
# adapter over mongomock repos behind the real route.


@pytest.fixture
def real_decision_client(admin_seed, request) -> Iterator[Any]:
    from mongomock_motor import AsyncMongoMockClient  # type: ignore[import-not-found]

    from backend.v2.composition.lifecycle_billing import compose_withdrawal_decision
    from backend.v2.contexts.billing.infrastructure.mongo_credit_ledger_repo import (
        MongoCreditLedgerRepository,
    )
    from backend.v2.contexts.billing.infrastructure.mongo_payment_repo import (
        MongoPaymentRepository,
    )
    from backend.v2.tests.interface.conftest import (  # type: ignore[attr-defined]
        _build_admin_use_cases,
        _claims,
        _make_admin_app,
    )

    db = AsyncMongoMockClient()["withdraw_decision_db"]
    seed_payment = request.param if hasattr(request, "param") else False
    adapter = compose_withdrawal_decision(
        payments=MongoPaymentRepository(db),
        credits=MongoCreditLedgerRepository(db),
        subscriptions=_NoSubscriptions(),
        stripe=_UnusedStripe(),
    )
    admin_seed["withdrawal_decision"] = _TenantScoped(adapter, "acad", db, seed_payment)
    uc = _build_admin_use_cases(admin_seed)
    app = _make_admin_app(_claims("admin"), uc)
    with TestClient(app) as client:
        client.seed = admin_seed  # type: ignore[attr-defined]
        client.db = db  # type: ignore[attr-defined]
        yield client


class _NoSubscriptions:
    async def latest_for_enrollment(self, _enrollment_id: str):
        return None

    async def save(self, subscription) -> None:  # pragma: no cover - never reached
        raise AssertionError("no legacy subscription in these fixtures")


class _UnusedStripe:
    async def cancel_subscription(self, _id: str, *, at_period_end: bool):  # pragma: no cover
        raise AssertionError("no legacy subscription in these fixtures")


class _TenantScoped:
    """Set the tenant the way the auth middleware does, then delegate to the
    real adapter (TestClient runs the app on its own loop, so a ContextVar set
    in the test body would not reach it). Seeds the paid payment on first use
    so the enrollment id the route generated is known."""

    def __init__(self, adapter: Any, academy_id: str, db: Any, seed_payment: bool) -> None:
        self._adapter = adapter
        self._academy_id = academy_id
        self._db = db
        self._seed_payment = seed_payment

    async def record_withdrawal_decision(self, **kwargs: Any) -> dict[str, Any]:
        from backend.v2.shared.tenancy import tenant_scope

        with tenant_scope(self._academy_id):
            if self._seed_payment:
                await self._insert_paid_payment(kwargs["enrollment"].enrollment_id)
            return await self._adapter.record_withdrawal_decision(**kwargs)

    async def _insert_paid_payment(self, enrollment_id: str) -> None:
        await self._db["payments"].insert_one(
            {
                "payment_id": "pay-1",
                "academy_id": self._academy_id,
                "parent_id": "p-1",
                "session_id": "sess-1",
                "enrollment_id": enrollment_id,
                "calculation_snapshot_id": "snap-1",
                "amount_cents": 4000,
                "refunded_cents": 0,
                "status": "succeeded",
                "created_at": datetime(2026, 5, 16, tzinfo=UTC),
                "updated_at": datetime(2026, 5, 16, tzinfo=UTC),
            }
        )
        await self._db["billing_calculation_snapshots"].insert_one(
            {
                "academy_id": self._academy_id,
                "snapshot_id": "snap-1",
                "monthly_price_cents": 10_000,
                "billing_period_start": datetime(2026, 5, 1, tzinfo=UTC),
                "billing_period_end": datetime(2026, 6, 1, tzinfo=UTC),
                "billing_period_label": "2026-05",
                "timezone": "America/Chicago",
                "total_eligible_classes": 8,
                "billable_remaining_classes": 3,
                "proration_ratio": "3/8",
                "final_amount_cents": 4000,
                "included_occurrence_ids": [
                    "sess-1:2026-05-22:18:00",
                    "sess-1:2026-05-26:18:00",
                ],
                "excluded_occurrences": {},
                "calculated_at": datetime(2026, 5, 16, tzinfo=UTC),
                "calculated_by": "p-1",
            }
        )


@pytest.mark.parametrize("real_decision_client", [False], indirect=True)
def test_ledger_only_family_withdraws_with_a_credit_none_event(real_decision_client) -> None:
    """The P1 regression: a family with no legacy paid payment used to get a
    404 Billing.PaymentNotFound and stay enrolled, seat held, still invoiced."""
    client = real_decision_client
    enrollment_id = _enroll(client)
    seats_before = client.seed["sessions"].reserved.get("sess-1", 0)

    response = _withdraw(client, enrollment_id, "credit")

    assert response.status_code == 204, response.text
    assert client.seed["enrollments"].rows[enrollment_id].status == "withdrawn"
    assert client.seed["sessions"].reserved["sess-1"] == seats_before - 1
    event = client.seed["enrollment_events"].rows[-1]
    assert event.event_type == "dropped"  # Issue #699: renamed from "withdrawn"
    assert event.billing_policy == "early_withdrawal_credit"
    assert event.billing_result.startswith("credit_none")
    assert event.credit_id is None
    assert event.metadata["no_credit_reason"] == "no_paid_tuition_snapshot"


@pytest.mark.parametrize("real_decision_client", [True], indirect=True)
def test_paid_family_withdraws_with_one_real_ledger_credit(real_decision_client) -> None:
    client = real_decision_client
    enrollment_id = _enroll(client)

    response = _withdraw(client, enrollment_id, "credit")

    assert response.status_code == 204, response.text
    event = client.seed["enrollment_events"].rows[-1]
    assert event.billing_result.startswith("credit_approved")
    assert event.credit_id is not None
