"""Admin Delivery problems route (L11 item 3): admin-only and read-only."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.contexts.communications.application.use_cases.delivery_problems import (
    DeliveryProblems,
    FailedSend,
)
from backend.v2.interfaces.admin.comms_routes import router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers


class _Get:
    async def execute(self) -> DeliveryProblems:
        return DeliveryProblems(
            suppressed_emails=["bounce@example.test"],
            failed=[
                FailedSend(
                    delivery_id="d1",
                    recipient_email="bounce@example.test",
                    failed_reason="email_delivery_failed",
                )
            ],
        )


def _client(roles: tuple[str, ...]) -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router, prefix="/api/v2/admin")
    app.state.delivery_problems = _Get()
    app.dependency_overrides[get_auth_claims] = lambda: AuthClaims(
        user_id="u1",
        email="u1@example.test",
        academy_id="acad",
        membership_id="m1",
        roles=roles,
    )
    return TestClient(app)


def test_admin_sees_the_academys_problems() -> None:
    res = _client(("admin",)).get("/api/v2/admin/comms/delivery-problems")
    assert res.status_code == 200
    assert res.json() == {
        "suppressed_emails": ["bounce@example.test"],
        "failed": [
            {
                "delivery_id": "d1",
                "recipient_email": "bounce@example.test",
                "failed_reason": "email_delivery_failed",
            }
        ],
    }


def test_a_parent_cannot_read_it() -> None:
    res = _client(("parent",)).get("/api/v2/admin/comms/delivery-problems")
    assert res.status_code == 404


def test_a_background_campaign_reports_queued_not_zero_delivered() -> None:
    from types import SimpleNamespace

    from backend.v2.contexts.communications.application.use_cases.send_campaign import (
        SendCampaignResult,
    )
    from backend.v2.interfaces.admin.deps import get_admin_use_cases

    class _Send:
        async def execute(self, command):
            return SendCampaignResult(
                campaign_id="c1", total_recipients=40, sent_count=0, failed_count=0, queued=True
            )

    client = _client(("admin",))
    client.app.dependency_overrides[get_admin_use_cases] = lambda: SimpleNamespace(  # type: ignore[attr-defined]
        send_campaign=_Send()
    )
    res = client.post(
        "/api/v2/admin/campaigns",
        json={"subject": "Hi", "body": "Hello", "audience": {"type": "academy", "role": "parent"}},
    )
    assert res.status_code == 201, res.text
    assert res.json()["queued"] is True
    assert res.json()["total_recipients"] == 40
