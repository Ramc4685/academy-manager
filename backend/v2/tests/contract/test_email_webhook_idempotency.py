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


# ---------------------------------------------------------------------------
# A FAILED attempt must be retryable (remediation for #556 review)
#
# `accept` deliberately re-raises so the route 500s and Resend retries. That
# only works if the dedup lets the retry back in. The first cut returned False
# for any DuplicateKeyError, so the retry was answered "duplicate" and the
# bounce was dropped forever — the 500 provoked a retry that could never
# succeed. `MongoStripeEventDedup.claim` already reclaims failed rows; this
# pins the same behaviour here.
# ---------------------------------------------------------------------------


class _ExplodingOnceSuppressions(MongoSuppressionRepository):
    """Real repository whose first `record` raises, as a transient blip would."""

    def __init__(self, db) -> None:
        super().__init__(db)
        self.calls = 0

    async def record(self, **kwargs):  # type: ignore[override]
        self.calls += 1
        if self.calls == 1:
            raise ConnectionError("transient mongo blip")
        return await super().record(**kwargs)


@pytest.mark.asyncio
async def test_failed_event_is_reapplied_when_the_provider_retries(db) -> None:
    await db["email_suppressions"].create_index("email", unique=True)
    await db["email_provider_events"].create_index("event_id", unique=True)
    suppressions = _ExplodingOnceSuppressions(db)
    use_case = IngestEmailProviderEvent(
        suppressions=suppressions,
        events=MongoEmailProviderEventDedup(db),
        verifier=ResendSignatureVerifier(secret=SECRET),
    )
    payload, headers = _signed(BOUNCE, svix_id="msg_retry")

    # First delivery blows up mid-apply -> route would 500 -> Resend retries.
    with pytest.raises(ConnectionError):
        await use_case.accept(payload=payload, headers=headers)
    assert await db["email_suppressions"].count_documents({}) == 0
    row = await db["email_provider_events"].find_one({"event_id": "msg_retry"})
    assert row["status"] == "failed"

    # The retry must be let back in, not answered "duplicate".
    result = await use_case.accept(payload=payload, headers=headers)

    assert result["status"] == "processed"
    stored = await MongoSuppressionRepository(db).get_active("dead@example.com")
    assert stored is not None
    assert stored.reason is SuppressionReason.HARD_BOUNCE
    # still exactly one event row, now succeeded, with the attempt counted
    assert await db["email_provider_events"].count_documents({}) == 1
    row = await db["email_provider_events"].find_one({"event_id": "msg_retry"})
    assert row["status"] == "processed"
    assert row["attempts"] == 2


@pytest.mark.asyncio
async def test_a_successfully_processed_event_is_still_never_reapplied(db) -> None:
    """The reclaim must not weaken the idempotency guarantee it sits inside."""
    use_case = await _wire(db)
    payload, headers = _signed(BOUNCE, svix_id="msg_done")

    assert (await use_case.accept(payload=payload, headers=headers))["status"] == "processed"
    for _ in range(3):
        assert (await use_case.accept(payload=payload, headers=headers))["status"] == "duplicate"
    assert await db["email_provider_events"].count_documents({}) == 1
