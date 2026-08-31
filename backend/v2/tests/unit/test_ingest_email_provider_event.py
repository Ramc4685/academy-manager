"""IngestEmailProviderEvent: what each Resend event does to the suppression list.

The distinctions under test are the ones the issue turns on: a hard bounce and
a complaint suppress, a *soft* bounce or delivery delay must not, an unknown
event type must not 500 (Resend would retry it forever), and a bad signature
must leave no trace at all.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest

from backend.v2.contexts.communications.application.use_cases.ingest_email_provider_event import (
    IngestEmailProviderEvent,
    MalformedProviderEvent,
)
from backend.v2.contexts.communications.domain.email_suppression import (
    EmailSuppression,
    SuppressionReason,
)
from backend.v2.contexts.communications.domain.errors import InvalidProviderSignature


@dataclass
class FakeSuppressions:
    rows: dict[str, EmailSuppression] = field(default_factory=dict)

    async def record(
        self,
        *,
        email: str,
        reason: SuppressionReason,
        bounce_subtype: str | None = None,
        provider_event_id: str | None = None,
    ) -> EmailSuppression:
        now = datetime.now(UTC)
        row = EmailSuppression(
            email=email,
            reason=reason,
            first_seen_at=now,
            last_seen_at=now,
            bounce_subtype=bounce_subtype,
            provider_event_id=provider_event_id,
        )
        self.rows[email] = row
        return row

    async def get_active(self, email: str) -> EmailSuppression | None:
        return self.rows.get(email)

    async def list_active(self, *, limit: int = 100) -> list[EmailSuppression]:
        return list(self.rows.values())[:limit]

    async def release(self, *, email: str, released_by: str) -> bool:
        return self.rows.pop(email, None) is not None


@dataclass
class FakeEvents:
    claimed: dict[str, dict[str, Any]] = field(default_factory=dict)

    async def claim(self, *, event_id: str, event_type: str, payload: dict[str, Any]) -> bool:
        if event_id in self.claimed:
            return False
        self.claimed[event_id] = {"event_type": event_type, "status": "received"}
        return True

    async def mark_processed(self, event_id: str, *, status: str = "processed") -> None:
        self.claimed[event_id]["status"] = status

    async def mark_failed(self, event_id: str, error: str) -> None:
        self.claimed[event_id]["status"] = "failed"


class AlwaysValid:
    def verify(self, *, payload: bytes, headers: Any) -> None:
        return None


class AlwaysInvalid:
    def verify(self, *, payload: bytes, headers: Any) -> None:
        raise InvalidProviderSignature("bad signature")


def _use_case(
    verifier: Any = None,
) -> tuple[IngestEmailProviderEvent, FakeSuppressions, FakeEvents]:
    suppressions = FakeSuppressions()
    events = FakeEvents()
    return (
        IngestEmailProviderEvent(
            suppressions=suppressions,
            events=events,
            verifier=verifier or AlwaysValid(),
        ),
        suppressions,
        events,
    )


def _body(event_type: str, data: dict[str, Any]) -> bytes:
    return json.dumps({"type": event_type, "data": data}).encode()


@pytest.mark.asyncio
async def test_hard_bounce_writes_a_suppression() -> None:
    use_case, suppressions, events = _use_case()
    result = await use_case.accept(
        payload=_body(
            "email.bounced",
            {"to": ["Dead@Example.com"], "bounce": {"type": "Permanent", "subType": "NoEmail"}},
        ),
        headers={"svix-id": "msg_1"},
    )
    assert result["status"] == "processed"
    assert suppressions.rows["dead@example.com"].reason is SuppressionReason.HARD_BOUNCE
    assert suppressions.rows["dead@example.com"].bounce_subtype == "NoEmail"
    assert events.claimed["msg_1"]["status"] == "processed"


@pytest.mark.asyncio
async def test_complaint_writes_a_complaint_suppression() -> None:
    use_case, suppressions, _ = _use_case()
    await use_case.accept(
        payload=_body("email.complained", {"to": ["annoyed@example.com"]}),
        headers={"svix-id": "msg_2"},
    )
    assert suppressions.rows["annoyed@example.com"].reason is SuppressionReason.COMPLAINT


@pytest.mark.asyncio
async def test_transient_bounce_does_not_suppress() -> None:
    """A full mailbox is not a dead address."""
    use_case, suppressions, events = _use_case()
    result = await use_case.accept(
        payload=_body(
            "email.bounced",
            {"to": ["full@example.com"], "bounce": {"type": "Transient", "subType": "MailboxFull"}},
        ),
        headers={"svix-id": "msg_3"},
    )
    assert result == {"status": "recorded", "event_id": "msg_3", "suppressed": False}
    assert suppressions.rows == {}
    assert events.claimed["msg_3"]["status"] == "processed"


@pytest.mark.asyncio
async def test_delivery_delayed_does_not_suppress() -> None:
    use_case, suppressions, _ = _use_case()
    await use_case.accept(
        payload=_body("email.delivery_delayed", {"to": ["slow@example.com"]}),
        headers={"svix-id": "msg_4"},
    )
    assert suppressions.rows == {}


@pytest.mark.asyncio
async def test_unknown_event_type_is_ignored_not_raised() -> None:
    use_case, suppressions, events = _use_case()
    result = await use_case.accept(
        payload=_body("email.teleported", {"to": ["someone@example.com"]}),
        headers={"svix-id": "msg_5"},
    )
    assert result["status"] == "ignored"
    assert suppressions.rows == {}
    assert events.claimed["msg_5"]["status"] == "ignored"


@pytest.mark.asyncio
async def test_duplicate_event_id_is_a_no_op() -> None:
    use_case, suppressions, _ = _use_case()
    payload = _body("email.bounced", {"to": ["dead@example.com"], "bounce": {"type": "Permanent"}})
    first = await use_case.accept(payload=payload, headers={"svix-id": "msg_6"})
    second = await use_case.accept(payload=payload, headers={"svix-id": "msg_6"})
    assert first["status"] == "processed"
    assert second == {"status": "duplicate", "event_id": "msg_6"}
    assert len(suppressions.rows) == 1


@pytest.mark.asyncio
async def test_invalid_signature_writes_nothing() -> None:
    use_case, suppressions, events = _use_case(AlwaysInvalid())
    with pytest.raises(InvalidProviderSignature):
        await use_case.accept(
            payload=_body("email.bounced", {"to": ["dead@example.com"]}),
            headers={"svix-id": "msg_7"},
        )
    assert suppressions.rows == {}
    assert events.claimed == {}


@pytest.mark.asyncio
async def test_non_json_body_is_a_client_error_not_a_crash() -> None:
    use_case, _, events = _use_case()
    with pytest.raises(MalformedProviderEvent):
        await use_case.accept(payload=b"not json", headers={"svix-id": "msg_8"})
    assert events.claimed == {}
