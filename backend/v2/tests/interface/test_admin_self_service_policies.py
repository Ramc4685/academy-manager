"""Admin self-service policy BFF contract tests."""

from __future__ import annotations

from unittest.mock import AsyncMock

from backend.v2.contexts.enrollment.domain.self_service import ParentSelfServicePolicy


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


def test_put_self_service_policy_roundtrips(admin_client):
    admin_client.use_cases.update_self_service_policy = AsyncMock()
    admin_client.use_cases.update_self_service_policy.execute.return_value = (
        ParentSelfServicePolicy(
            academy_id="acad",
            absence_notice_min_hours=4,
            makeup_expiry_days=45,
            makeup_requires_notice=False,
            cancellation_minimum_notice_days=14,
            cancellation_fee_cents=2500,
            cancellation_effective_timing="immediate",
        )
    )

    response = admin_client.put(
        "/api/v2/admin/self-service/policy",
        json={
            "absence_notice_min_hours": 4,
            "makeup_expiry_days": 45,
            "makeup_requires_notice": False,
            "cancellation_minimum_notice_days": 14,
            "cancellation_fee_cents": 2500,
            "cancellation_effective_timing": "immediate",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "absence_notice_min_hours": 4,
        "makeup_expiry_days": 45,
        "makeup_requires_notice": False,
        "cancellation_minimum_notice_days": 14,
        "cancellation_fee_cents": 2500,
        "cancellation_effective_timing": "immediate",
    }
    admin_client.use_cases.update_self_service_policy.execute.assert_awaited_once()


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
