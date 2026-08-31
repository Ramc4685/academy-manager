"""Resend bounce/complaint webhook receiver (issue #556).

Mounted top-level rather than under ``/parent``: the Stripe webhook lives there
only because parents own the upstream checkout, but a bounce can belong to any
persona's mail, and the payload carries no tenant at all.

NOT auth-gated — the Svix signature IS the auth, and it is checked before
anything is written. The route is only mounted when a signing secret is
configured, so an unconfigured deployment 404s instead of accepting unverified
bounce reports.

Status codes are chosen for a provider that retries: a well-signed event is
always 200 (including a duplicate and an event type we do not understand), a
bad signature is 401, and only an unexpected server-side failure is a 5xx that
Resend should try again.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from backend.v2.contexts.communications.application.errors import InvalidProviderSignature
from backend.v2.contexts.communications.application.use_cases.ingest_email_provider_event import (
    IngestEmailProviderEvent,
    MalformedProviderEvent,
)

router = APIRouter(tags=["webhooks.email"])


@router.post(
    "/webhooks/resend",
    summary="Resend webhook receiver (Svix-signature-verified, idempotent on svix-id)",
)
async def resend_webhook(request: Request) -> dict[str, object]:
    use_case: IngestEmailProviderEvent | None = getattr(
        request.app.state, "ingest_email_provider_event", None
    )
    if use_case is None:
        # No signing secret configured: refuse to look like a working endpoint.
        raise HTTPException(status_code=404, detail="Resend webhook ingestion is not enabled")
    # RAW bytes: the signature covers the exact body Resend sent, so a
    # re-serialized dict would never verify.
    payload = await request.body()
    try:
        return await use_case.accept(payload=payload, headers=dict(request.headers))
    except InvalidProviderSignature:
        raise HTTPException(status_code=401, detail="Invalid webhook signature") from None
    except MalformedProviderEvent as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
