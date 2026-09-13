"""Mongo-backed win-back-notice-send claim (issue #778).

Structurally a copy of ``MongoHoldNoticeSendRepository`` (composition/
hold_notice_send_repo.py), with ``recipient_field="student_id"`` (win-back
outreach is per departed student, not per enrollment — a dropped
enrollment_id is a one-time event, while the student is who eventually
re-enrolls or doesn't) and ``digest_date=milestone_key`` (``"30"``/``"60"``/
``"90"``). Reuses ``digest_claim.claim_digest_send`` for the same reason
``hold_notice_send_repo.py`` does: it is the one place the 2026-09-02
duplicate-send incident's fix lives, and every idempotent-send claim in this
codebase is required to go through it rather than re-implement the
verify-after-insert dance.

Lives in ``composition/`` rather than ``contexts/enrollment/infrastructure/``
for the identical cross-context-import reason ``hold_notice_send_repo.py``
gives — this module imports the communications context's ``digest_claim``/
``DigestSendStatus``, which ``tests/structural/test_layering.py::
test_no_cross_context_imports`` forbids inside ``contexts/**``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from backend.v2.contexts.communications.domain.models import DigestSendStatus
from backend.v2.contexts.communications.infrastructure.digest_claim import claim_digest_send
from backend.v2.shared.ids import new_ulid
from backend.v2.shared.tenancy import TenantScopedRepository


class MongoWinBackSendRepository(TenantScopedRepository):
    collection_name = "win_back_notice_sends"

    async def try_claim(
        self, *, academy_id: str, student_id: str, milestone_key: str
    ) -> dict[str, Any] | None:
        send_id = str(new_ulid())
        doc = {
            "send_id": send_id,
            "academy_id": academy_id,
            "student_id": student_id,
            "milestone_key": milestone_key,
            # See `MongoHoldNoticeSendRepository`'s identical comment:
            # `claim_digest_send`'s post-insert verify filters on
            # `digest_date`, not `milestone_key` — load-bearing, not
            # decorative.
            "digest_date": milestone_key,
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
            recipient_field="student_id",
            recipient_id=student_id,
            digest_date=milestone_key,
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
