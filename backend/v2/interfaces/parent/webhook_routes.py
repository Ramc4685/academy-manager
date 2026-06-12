"""Stripe webhook endpoint.

Lives under the parent BFF because parents own the upstream checkout
session. NOT auth-gated — signature verification is the auth.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Request

from backend.v2.interfaces.parent.deps import ParentUseCases, get_parent_use_cases

router = APIRouter(tags=["parent.webhook"])


@router.post(
    "/webhooks/stripe",
    summary="Stripe webhook receiver (signature-verified, idempotent on event id)",
)
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(alias="stripe-signature"),
    use_cases: ParentUseCases = Depends(get_parent_use_cases),
) -> dict[str, object]:
    payload = await request.body()
    return await use_cases.handle_webhook_event.accept(payload, stripe_signature)
