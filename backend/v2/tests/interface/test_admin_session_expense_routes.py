from __future__ import annotations


def test_patch_session_edits_supported_fields(admin_client):
    response = admin_client.patch(
        "/api/v2/admin/sessions/sess-1",
        json={
            "title": "Junior Advanced",
            "capacity": 10,
            "location": "Court 3",
            "start_at": "2026-05-16T09:30:00Z",
            "end_at": "2026-05-16T11:00:00Z",
            "coach_id": "coach-2",
            "reason": "schedule cleanup",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["session_id"] == "sess-1"
    assert body["title"] == "Junior Advanced"
    assert body["capacity"] == 10
    assert body["location"] == "Court 3"
    assert body["coach_id"] == "coach-2"
    assert "monthly_price_cents" not in body


def test_patch_session_wrong_persona_404(coach_on_admin_client):
    response = coach_on_admin_client.patch(
        "/api/v2/admin/sessions/sess-1",
        json={"title": "Blocked"},
    )

    assert response.status_code == 404


def test_patch_session_validation_failure_returns_422(admin_client):
    response = admin_client.patch(
        "/api/v2/admin/sessions/sess-1",
        json={"capacity": 0},
    )

    assert response.status_code == 422


def test_patch_expense_edits_existing_entry(admin_client):
    created = admin_client.post(
        "/api/v2/admin/finance/expenses",
        json={"category": "equipment", "amount_cents": 4500, "note": "Shuttles"},
    )
    expense_id = created.json()["expense_id"]

    response = admin_client.patch(
        f"/api/v2/admin/finance/expenses/{expense_id}",
        json={
            "category": "marketing",
            "amount_cents": 9900,
            "note": "Tournament flyers",
            "incurred_on": "2026-05-21T00:00:00Z",
            "reason": "receipt correction",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["expense_id"] == expense_id
    assert body["category"] == "marketing"
    assert body["amount_cents"] == 9900
    assert body["note"] == "Tournament flyers"


def test_delete_expense_soft_deletes_and_hides_from_list(admin_client):
    created = admin_client.post(
        "/api/v2/admin/finance/expenses",
        json={"category": "rent", "amount_cents": 250000, "note": "May rent"},
    )
    expense_id = created.json()["expense_id"]

    response = admin_client.request(
        "DELETE",
        f"/api/v2/admin/finance/expenses/{expense_id}",
        json={"reason": "duplicate receipt"},
    )

    assert response.status_code == 204, response.text
    listing = admin_client.get("/api/v2/admin/finance/expenses").json()
    assert all(expense["expense_id"] != expense_id for expense in listing["expenses"])


def test_expense_mutation_validation_failures_return_422(admin_client):
    created = admin_client.post(
        "/api/v2/admin/finance/expenses",
        json={"category": "rent", "amount_cents": 250000, "note": "May rent"},
    )
    expense_id = created.json()["expense_id"]

    patch_response = admin_client.patch(
        f"/api/v2/admin/finance/expenses/{expense_id}",
        json={"amount_cents": -1},
    )
    delete_response = admin_client.request(
        "DELETE",
        f"/api/v2/admin/finance/expenses/{expense_id}",
        json={},
    )

    assert patch_response.status_code == 422
    assert delete_response.status_code == 422


def test_expense_mutations_wrong_persona_404(parent_on_admin_client):
    patch_response = parent_on_admin_client.patch(
        "/api/v2/admin/finance/expenses/exp-1",
        json={"note": "Blocked"},
    )
    delete_response = parent_on_admin_client.request(
        "DELETE",
        "/api/v2/admin/finance/expenses/exp-1",
        json={"reason": "blocked"},
    )

    assert patch_response.status_code == 404
    assert delete_response.status_code == 404
