"""``POST /api/v2/webhooks/resend`` — the route contract (issue #556).

The Svix signature is the only authentication on this endpoint, so the status
codes matter as much as the behaviour: an unsigned request must be 401 with
nothing written, and a well-signed one must be 200 even when we do nothing with
it, or Resend retries and eventually disables the endpoint.
"""

from __future__ import annotations

import base64
import json
import time
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.contexts.communications.application.use_cases.ingest_email_provider_event import (
    IngestEmailProviderEvent,
)
from backend.v2.contexts.communications.domain.email_suppression import SuppressionReason
from backend.v2.contexts.communications.infrastructure.resend_signature import (
    ResendSignatureVerifier,
    sign_resend_payload,
)
from backend.v2.interfaces.email_webhook_routes import router as email_webhook_router
from backend.v2.shared.http import register_exception_handlers

SECRET = "whsec_" + base64.b64encode(b"route-test-key").decode()


class _Suppressions:
    def __init__(self) -> None:
        self.recorded: list[tuple[str, SuppressionReason]] = []

    async def record(
        self,
        *,
        email: str,
        reason: SuppressionReason,
        bounce_subtype: str | None = None,
        provider_event_id: str | None = None,
    ) -> Any:
        self.recorded.append((email, reason))
        return None

    async def get_active(self, email: str) -> Any:
        return None

    async def list_active(self, *, limit: int = 100) -> list[Any]:
        return []

    async def release(self, *, email: str, released_by: str) -> bool:
        return False


class _Events:
    def __init__(self) -> None:
        self.claims: list[str] = []

    async def claim(self, *, event_id: str, event_type: str, payload: dict[str, Any]) -> bool:
        if event_id in self.claims:
            return False
        self.claims.append(event_id)
        return True

    async def mark_processed(self, event_id: str, *, status: str = "processed") -> None:
        return None

    async def mark_failed(self, event_id: str, error: str) -> None:
        return None


def _app(*, enabled: bool = True) -> tuple[FastAPI, _Suppressions, _Events]:
    app = FastAPI()
    register_exception_handlers(app)
    suppressions, events = _Suppressions(), _Events()
    app.state.ingest_email_provider_event = (
        IngestEmailProviderEvent(
            suppressions=suppressions,
            events=events,
            verifier=ResendSignatureVerifier(secret=SECRET),
        )
        if enabled
        else None
    )
    app.include_router(email_webhook_router, prefix="/api/v2")
    return app, suppressions, events


BOUNCE = {
    "type": "email.bounced",
    "data": {"to": ["dead@example.com"], "bounce": {"type": "Permanent"}},
}


def _headers(payload: bytes, *, svix_id: str = "msg_route") -> dict[str, str]:
    timestamp = str(int(time.time()))
    return {
        "svix-id": svix_id,
        "svix-timestamp": timestamp,
        "svix-signature": sign_resend_payload(
            svix_id=svix_id, timestamp=timestamp, payload=payload, secret=SECRET
        ),
        "content-type": "application/json",
    }


def test_signed_bounce_returns_200_and_records_a_suppression() -> None:
    app, suppressions, _ = _app()
    payload = json.dumps(BOUNCE).encode()

    with TestClient(app) as client:
        response = client.post(
            "/api/v2/webhooks/resend", content=payload, headers=_headers(payload)
        )

    assert response.status_code == 200
    assert response.json()["status"] == "processed"
    assert suppressions.recorded == [("dead@example.com", SuppressionReason.HARD_BOUNCE)]


def test_unsigned_post_is_401_and_writes_nothing() -> None:
    app, suppressions, events = _app()
    payload = json.dumps(BOUNCE).encode()

    with TestClient(app) as client:
        response = client.post(
            "/api/v2/webhooks/resend",
            content=payload,
            headers={"content-type": "application/json"},
        )

    assert response.status_code == 401
    assert suppressions.recorded == []
    assert events.claims == []


def test_signature_over_a_different_body_is_401() -> None:
    """The signature covers the RAW bytes, so a swapped body must not verify."""
    app, suppressions, _ = _app()
    signed_payload = json.dumps(BOUNCE).encode()
    other_payload = json.dumps(
        {"type": "email.bounced", "data": {"to": ["someone-else@example.com"]}}
    ).encode()

    with TestClient(app) as client:
        response = client.post(
            "/api/v2/webhooks/resend",
            content=other_payload,
            headers=_headers(signed_payload),
        )

    assert response.status_code == 401
    assert suppressions.recorded == []


def test_duplicate_delivery_is_200_not_an_error() -> None:
    app, suppressions, _ = _app()
    payload = json.dumps(BOUNCE).encode()

    with TestClient(app) as client:
        first = client.post("/api/v2/webhooks/resend", content=payload, headers=_headers(payload))
        second = client.post("/api/v2/webhooks/resend", content=payload, headers=_headers(payload))

    assert (first.status_code, second.status_code) == (200, 200)
    assert second.json()["status"] == "duplicate"
    assert len(suppressions.recorded) == 1


def test_unknown_event_type_is_200_ignored() -> None:
    app, suppressions, _ = _app()
    payload = json.dumps({"type": "email.opened", "data": {"to": ["a@example.com"]}}).encode()

    with TestClient(app) as client:
        response = client.post(
            "/api/v2/webhooks/resend", content=payload, headers=_headers(payload)
        )

    assert response.status_code == 200
    assert response.json()["status"] == "ignored"
    assert suppressions.recorded == []


def test_route_404s_when_no_signing_secret_is_configured() -> None:
    """Fail-closed: an unconfigured deployment must not look like it works."""
    app, _, _ = _app(enabled=False)
    payload = json.dumps(BOUNCE).encode()

    with TestClient(app) as client:
        response = client.post(
            "/api/v2/webhooks/resend", content=payload, headers=_headers(payload)
        )

    assert response.status_code == 404
