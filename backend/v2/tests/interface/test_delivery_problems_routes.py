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


def test_campaign_preview_returns_the_resolved_audience_counts() -> None:
    from types import SimpleNamespace

    from backend.v2.contexts.communications.application.use_cases.send_campaign import (
        CampaignAudiencePreview,
    )
    from backend.v2.interfaces.admin.deps import get_admin_use_cases

    seen: list[object] = []

    class _Send:
        async def preview(self, audience):
            seen.append(audience)
            return CampaignAudiencePreview(recipient_count=7, family_count=6, contact_count=1)

    client = _client(("admin",))
    client.app.dependency_overrides[get_admin_use_cases] = lambda: SimpleNamespace(  # type: ignore[attr-defined]
        send_campaign=_Send()
    )
    res = client.post(
        "/api/v2/admin/campaigns/preview",
        json={"audience": {"type": "session", "session_id": "sess-1"}},
    )
    assert res.status_code == 200, res.text
    assert res.json()["recipient_count"] == 7
    assert (res.json()["family_count"], res.json()["contact_count"]) == (6, 1)
    assert getattr(seen[0], "session_id", None) == "sess-1"


def test_a_parent_cannot_preview_a_campaign() -> None:
    res = _client(("parent",)).post(
        "/api/v2/admin/campaigns/preview", json={"audience": {"type": "academy"}}
    )
    assert res.status_code == 404


def test_a_changed_audience_is_a_409_the_ui_can_tell_apart() -> None:
    from types import SimpleNamespace

    from backend.v2.contexts.communications.domain.errors import AudienceChangedError
    from backend.v2.interfaces.admin.deps import get_admin_use_cases

    commands: list[object] = []

    class _Send:
        async def execute(self, command):
            commands.append(command)
            raise AudienceChangedError("changed")

    client = _client(("admin",))
    client.app.dependency_overrides[get_admin_use_cases] = lambda: SimpleNamespace(  # type: ignore[attr-defined]
        send_campaign=_Send()
    )
    res = client.post(
        "/api/v2/admin/campaigns",
        json={
            "subject": "Hi",
            "body": "Hello",
            "audience": {"type": "academy", "role": "parent"},
            "expected_audience_fingerprint": "fp-old",
        },
    )
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "audience_changed"
    assert getattr(commands[0], "expected_audience_fingerprint", None) == "fp-old"


def _capture_preview_client():
    from types import SimpleNamespace

    from backend.v2.contexts.communications.application.use_cases.send_campaign import (
        CampaignAudiencePreview,
    )
    from backend.v2.contexts.communications.domain.errors import InvalidAudienceError
    from backend.v2.interfaces.admin.deps import get_admin_use_cases

    seen: list[object] = []

    class _Send:
        async def preview(self, audience):
            seen.append(audience)
            if "sess-foreign" in getattr(audience, "session_ids", ()):
                raise InvalidAudienceError("unknown session(s): sess-foreign")
            return CampaignAudiencePreview(recipient_count=1, family_count=1, contact_count=0)

    client = _client(("admin",))
    client.app.dependency_overrides[get_admin_use_cases] = lambda: SimpleNamespace(  # type: ignore[attr-defined]
        send_campaign=_Send()
    )
    return client, seen


def test_several_sessions_become_one_union_audience() -> None:
    client, seen = _capture_preview_client()
    res = client.post(
        "/api/v2/admin/campaigns/preview",
        json={"audience": {"type": "session", "session_ids": ["s1", "s2", "s1"]}},
    )
    assert res.status_code == 200, res.text
    assert getattr(seen[0], "session_ids", None) == ("s1", "s2")


def test_one_selected_session_keeps_the_single_session_audience() -> None:
    client, seen = _capture_preview_client()
    res = client.post(
        "/api/v2/admin/campaigns/preview",
        json={"audience": {"type": "session", "session_ids": ["s1"]}},
    )
    assert res.status_code == 200
    assert getattr(seen[0], "session_id", None) == "s1"


def test_empty_selection_and_foreign_sessions_are_refused() -> None:
    client, _ = _capture_preview_client()
    empty = client.post(
        "/api/v2/admin/campaigns/preview",
        json={"audience": {"type": "session", "session_ids": []}},
    )
    assert empty.status_code == 400
    foreign = client.post(
        "/api/v2/admin/campaigns/preview",
        json={"audience": {"type": "session", "session_ids": ["s1", "sess-foreign"]}},
    )
    assert foreign.status_code == 422
