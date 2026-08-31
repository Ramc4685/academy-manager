"""The Resend webhook, wired the way composition wires it (issue #556).

Everything below runs against the real Mongo-backed suppression store, event
log and signature verifier — the only fake is the transport. Mirrors
``tests/contract/test_billing_idempotency.py``: a provider that retries must
never apply the same event twice, and must never be handed a 4xx for a
duplicate.
"""

from __future__ import annotations

import base64
import json
import time

import pytest

from backend.v2.contexts.communications.application.use_cases.ingest_email_provider_event import (
    IngestEmailProviderEvent,
)
from backend.v2.contexts.communications.domain.email_suppression import SuppressionReason
from backend.v2.contexts.communications.domain.errors import InvalidProviderSignature
from backend.v2.contexts.communications.infrastructure.mongo_provider_event_repo import (
    MongoEmailProviderEventDedup,
)
from backend.v2.contexts.communications.infrastructure.mongo_suppression_repo import (
    MongoSuppressionRepository,
)
from backend.v2.contexts.communications.infrastructure.resend_signature import (
    ResendSignatureVerifier,
    sign_resend_payload,
)

SECRET = "whsec_" + base64.b64encode(b"contract-test-key").decode()


async def _wire(db):
    # Indexes from migration 0158 — the duplicate-key errors ARE the guards.
    await db["email_suppressions"].create_index("email", unique=True)
    await db["email_provider_events"].create_index("event_id", unique=True)
    return IngestEmailProviderEvent(
        suppressions=MongoSuppressionRepository(db),
        events=MongoEmailProviderEventDedup(db),
        verifier=ResendSignatureVerifier(secret=SECRET),
    )


def _signed(event: dict, *, svix_id: str) -> tuple[bytes, dict[str, str]]:
    payload = json.dumps(event).encode()
    timestamp = str(int(time.time()))
    return payload, {
        "svix-id": svix_id,
        "svix-timestamp": timestamp,
        "svix-signature": sign_resend_payload(
            svix_id=svix_id, timestamp=timestamp, payload=payload, secret=SECRET
        ),
    }


BOUNCE = {
    "type": "email.bounced",
    "data": {"to": ["dead@example.com"], "bounce": {"type": "Permanent", "subType": "NoEmail"}},
}


@pytest.mark.asyncio
async def test_signed_bounce_writes_a_suppression(db) -> None:
    use_case = await _wire(db)
    payload, headers = _signed(BOUNCE, svix_id="msg_a")

    result = await use_case.accept(payload=payload, headers=headers)

    assert result["status"] == "processed"
    stored = await MongoSuppressionRepository(db).get_active("dead@example.com")
    assert stored is not None
    assert stored.reason is SuppressionReason.HARD_BOUNCE
    assert stored.bounce_subtype == "NoEmail"


@pytest.mark.asyncio
async def test_same_svix_id_delivered_twice_yields_one_row_each(db) -> None:
    use_case = await _wire(db)
    payload, headers = _signed(BOUNCE, svix_id="msg_b")

    first = await use_case.accept(payload=payload, headers=headers)
    second = await use_case.accept(payload=payload, headers=headers)

    assert first["status"] == "processed"
    assert second["status"] == "duplicate"
    assert await db["email_suppressions"].count_documents({}) == 1
    assert await db["email_provider_events"].count_documents({}) == 1


@pytest.mark.asyncio
async def test_invalid_signature_leaves_no_state_behind(db) -> None:
    use_case = await _wire(db)
    payload, headers = _signed(BOUNCE, svix_id="msg_c")
    headers["svix-signature"] = "v1," + base64.b64encode(b"x" * 32).decode()

    with pytest.raises(InvalidProviderSignature):
        await use_case.accept(payload=payload, headers=headers)

    assert await db["email_suppressions"].count_documents({}) == 0
    assert await db["email_provider_events"].count_documents({}) == 0


@pytest.mark.asyncio
async def test_soft_bounce_is_logged_but_never_suppressed(db) -> None:
    use_case = await _wire(db)
    payload, headers = _signed(
        {
            "type": "email.bounced",
            "data": {
                "to": ["full@example.com"],
                "bounce": {"type": "Transient", "subType": "MailboxFull"},
            },
        },
        svix_id="msg_d",
    )

    result = await use_case.accept(payload=payload, headers=headers)

    assert result["suppressed"] is False
    assert await db["email_suppressions"].count_documents({}) == 0
    event = await db["email_provider_events"].find_one({"event_id": "msg_d"})
    assert event["status"] == "processed"
