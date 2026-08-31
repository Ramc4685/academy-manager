"""Ingest one Resend webhook event into the suppression list (issue #556).

Order of operations is the whole design:

1. **Verify the signature first.** Nothing is written before it passes, so a
   forged or replayed request leaves no row in ``email_provider_events`` and no
   suppression — "an invalid signature is rejected with no state change" is a
   property of this ordering, not of a later check.
2. **Claim the event id.** Insert-first against a unique index, exactly like
   the Stripe webhook: the duplicate-key error IS the idempotency guard.
   A duplicate returns 200; Resend retries on anything else and would
   eventually disable the endpoint.
3. **Classify, then apply.** Hard bounces and complaints write a suppression.
   Soft bounces and delivery delays are recorded and dropped — a full mailbox
   is not a dead address. An event type we do not recognise is stored
   ``ignored`` and 200'd, never 500'd, because Resend adds event types without
   asking us.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass

from backend.v2.contexts.communications.application.ports import (
    ProviderEventDedup,
    ProviderSignatureVerifier,
    SuppressionRepository,
)
from backend.v2.contexts.communications.domain.email_suppression import (
    KNOWN_EVENT_TYPES,
    classify_resend_event,
)

log = logging.getLogger(__name__)


class MalformedProviderEvent(ValueError):
    """The body verified but is not JSON we can read. Mapped to HTTP 400."""


@dataclass
class IngestEmailProviderEvent:
    suppressions: SuppressionRepository
    events: ProviderEventDedup
    verifier: ProviderSignatureVerifier

    async def accept(self, *, payload: bytes, headers: Mapping[str, str]) -> dict[str, object]:
        # 1. Signature. Raises InvalidProviderSignature -> 401, nothing written.
        self.verifier.verify(payload=payload, headers=headers)

        try:
            event = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MalformedProviderEvent(f"webhook body is not JSON: {exc}") from exc
        if not isinstance(event, dict):
            raise MalformedProviderEvent("webhook body is not a JSON object")

        event_type = str(event.get("type") or "")
        data = event.get("data")
        data_dict: dict[str, object] = data if isinstance(data, dict) else {}
        event_id = _event_id(headers, event_type, data_dict)

        # 2. Idempotency claim.
        if not await self.events.claim(event_id=event_id, event_type=event_type, payload=event):
            return {"status": "duplicate", "event_id": event_id}

        # 3. Apply.
        try:
            if event_type not in KNOWN_EVENT_TYPES:
                await self.events.mark_processed(event_id, status="ignored")
                return {"status": "ignored", "event_id": event_id, "event_type": event_type}

            classified = classify_resend_event(event_type, data_dict)
            if not classified.suppresses:
                # Soft bounce / delivery delay / no usable address: the event is
                # a fact worth keeping, but it must not cost anyone their mail.
                await self.events.mark_processed(event_id, status="processed")
                return {"status": "recorded", "event_id": event_id, "suppressed": False}

            assert classified.email is not None and classified.reason is not None
            await self.suppressions.record(
                email=classified.email,
                reason=classified.reason,
                bounce_subtype=classified.bounce_subtype,
                provider_event_id=event_id,
            )
            await self.events.mark_processed(event_id, status="processed")
            return {
                "status": "processed",
                "event_id": event_id,
                "suppressed": True,
                "reason": classified.reason.value,
            }
        except Exception as exc:
            # Leave a readable trail and let the route 500 so Resend retries.
            await self.events.mark_failed(event_id, f"{type(exc).__name__}: {exc}")
            log.exception("email_provider_event_failed: event_id=%s", event_id)
            raise


def _event_id(headers: Mapping[str, str], event_type: str, data: dict[str, object]) -> str:
    """The idempotency key: ``svix-id``, falling back to the message id + type.

    Svix always sends ``svix-id`` and it is what a retry repeats. The fallback
    exists only so a payload from a future transport still deduplicates on
    something stable rather than on nothing.
    """
    lookup = {str(k).lower(): v for k, v in headers.items()}
    svix_id = (lookup.get("svix-id") or "").strip()
    if svix_id:
        return svix_id
    email_id = data.get("email_id")
    return f"{email_id}:{event_type}" if isinstance(email_id, str) and email_id else event_type
