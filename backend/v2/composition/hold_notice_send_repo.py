"""Mongo-backed hold-notice-send claim (issue #697).

Structurally a copy of ``MongoDigestSendRepository`` with a different
recipient field — reuses ``digest_claim.claim_digest_send`` per the
departures design contract §4.4, which is mandatory, not a convenience: that
module's docstring is the repo's written record of the 2026-09-02 production
incident where a freshly written claim (append-only, no verify) would have
been unsafe. ``recipient_field="enrollment_id"``, ``digest_date=notice_key``.

Lives in ``composition/`` rather than ``contexts/enrollment/infrastructure/``
(a deviation from the contract's literal path) because it imports the
communications context's ``digest_claim``/``DigestSendStatus`` — a
cross-context import that ``tests/structural/test_layering.py::
test_no_cross_context_imports`` forbids inside ``contexts/**``. Every other
enrollment/communications bridge in this repo (``roster_notifications.py``,
``enrollment_welcome_email.py``) already lives here for the same reason.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from backend.v2.contexts.communications.domain.models import DigestSendStatus
from backend.v2.contexts.communications.infrastructure.digest_claim import claim_digest_send
from backend.v2.shared.ids import new_ulid
from backend.v2.shared.tenancy import TenantScopedRepository


class MongoHoldNoticeSendRepository(TenantScopedRepository):
    collection_name = "enrollment_hold_notice_sends"

    async def try_claim(
        self, *, academy_id: str, enrollment_id: str, notice_key: str
    ) -> dict[str, Any] | None:
        send_id = str(new_ulid())
        doc = {
            "send_id": send_id,
            "academy_id": academy_id,
            "enrollment_id": enrollment_id,
            "notice_key": notice_key,
            "status": str(DigestSendStatus.QUEUED),
            "provider_message_id": None,
            "failed_reason": None,
            "created_at": datetime.now(UTC),
            "attempt_count": 1,
            "retryable": True,
        }
        return await claim_digest_send(
            self.collection,
            doc=doc,
            academy_id=academy_id,
            recipient_field="enrollment_id",
            recipient_id=enrollment_id,
            digest_date=notice_key,
        )

    async def mark_sent(self, send_id: str) -> None:
        await self.collection.update_one(
            {"send_id": send_id},
            {"$set": {"status": str(DigestSendStatus.SENT), "failed_reason": None}},
        )

    async def mark_failed(self, send_id: str, reason: str, *, retryable: bool = True) -> None:
        await self.collection.update_one(
            {"send_id": send_id},
            {
                "$set": {
                    "status": str(DigestSendStatus.FAILED),
                    "failed_reason": reason,
                    "retryable": retryable,
                }
            },
        )
