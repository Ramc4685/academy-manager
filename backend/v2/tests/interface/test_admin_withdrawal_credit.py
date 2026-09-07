"""Withdrawal credit routes (issue #670: one withdraw path).

The old owner-only ``.../withdrawal-credit/approve`` route is gone; the credit
outcome now rides ``POST /enrollments/{id}/withdraw`` with an action-level
owner check. The preview route is unchanged.
"""

from __future__ import annotations

from typing import Any


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
    assert event.event_type == "withdrawn"
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
    assert len([e for e in seed["enrollment_events"].rows if e.event_type == "withdrawn"]) == 1


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
