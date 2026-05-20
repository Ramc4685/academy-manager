from __future__ import annotations


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


def test_admin_approve_withdrawal_credit(admin_client) -> None:
    response = admin_client.post(
        "/api/v2/admin/enrollments/enroll-1/withdrawal-credit/approve",
        json={
            "withdrawal_date": "2026-05-20T00:00:00Z",
            "admin_note": "Relocation",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "APPROVED",
        "credit_amount_cents": 3750,
        "credit_balance_cents": 3750,
    }


def test_parent_cannot_use_admin_withdrawal_credit(parent_on_admin_client) -> None:
    response = parent_on_admin_client.post(
        "/api/v2/admin/enrollments/enroll-1/withdrawal-credit/preview",
        json={"withdrawal_date": "2026-05-20T00:00:00Z"},
    )

    assert response.status_code == 404
