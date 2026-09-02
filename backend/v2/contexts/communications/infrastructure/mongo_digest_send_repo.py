"""Mongo-backed coach digest-send repository.

``try_claim`` is a lookup-then-insert lock (``digest_claim.claim_digest_send``):
it looks for today's ``(academy_id, coach_id, digest_date)`` row first and only
inserts a QUEUED row when none exists, so the daily digest stays idempotent
across scheduler retries even when the unique index from migration 0125 has
not been built (the 2026-09-02 hourly-resend incident). Concurrent claims are
settled by ``claim_digest_send`` itself — a duplicate-key error when the index
is present, a post-insert verify when it is not — so no caller may assume the
index makes the claim safe.

A row already in ``failed`` is the one case where refusing is wrong: before #435
a transient Resend outage cost that coach the whole day's digest, because the
claim stayed held by a row nothing would ever retry. An existing row now goes
through a conditional re-claim (``digest_claim.reclaim_retryable_send``) that can
only ever match a failed or abandoned row with attempts left.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from backend.v2.contexts.communications.application.ports import DigestSendRepository
from backend.v2.contexts.communications.domain.models import DigestSend, DigestSendStatus
from backend.v2.contexts.communications.infrastructure.digest_claim import claim_digest_send
from backend.v2.shared.ids import new_ulid
from backend.v2.shared.tenancy import TenantScopedRepository


class MongoDigestSendRepository(TenantScopedRepository, DigestSendRepository):
    collection_name = "coach_digest_sends"

    async def try_claim(
        self, academy_id: str, coach_id: str, digest_date: str
    ) -> DigestSend | None:
        digest = DigestSend.queued(
            digest_id=new_ulid(),
            academy_id=academy_id,
            coach_id=coach_id,
            coach_email=None,
            digest_date=digest_date,
            created_at=datetime.now(UTC),
        )
        doc = await claim_digest_send(
            self.collection,
            doc=self._to_doc(digest),
            academy_id=academy_id,
            recipient_field="coach_id",
            recipient_id=coach_id,
            digest_date=digest_date,
        )
        return self._from_doc(doc) if doc is not None else None

    async def record_test_send(
        self, academy_id: str, coach_id: str, digest_date: str
    ) -> DigestSend:
        """Record an admin-triggered test send.

        A test send must NOT consume the daily claim, so the unique
        ``(academy_id, coach_id, digest_date)`` index must not block it. We store
        the row against a synthetic, always-unique ``digest_date`` (the real date
        plus a ``#test:<ulid>`` suffix) while keeping ``kind="test"``; the
        display date is recovered in ``list_recent`` by splitting on ``#``. This
        sidesteps the unique index without a partial-index migration (and works
        identically under mongomock).
        """
        digest = DigestSend.queued(
            digest_id=new_ulid(),
            academy_id=academy_id,
            coach_id=coach_id,
            coach_email=None,
            digest_date=f"{digest_date}#test:{new_ulid()}",
            created_at=datetime.now(UTC),
            kind="test",
        )
        await self.collection.insert_one(self._to_doc(digest))
        return digest

    async def mark_sent(self, digest_id: str, provider_message_id: str | None) -> None:
        await self.collection.update_one(
            {"digest_id": digest_id},
            {
                "$set": {
                    "status": str(DigestSendStatus.SENT),
                    "provider_message_id": provider_message_id,
                    "sent_at": datetime.now(UTC).isoformat(),
                    "failed_reason": None,
                }
            },
        )

    async def mark_failed(self, digest_id: str, reason: str, *, retryable: bool = True) -> None:
        await self.collection.update_one(
            {"digest_id": digest_id},
            {
                "$set": {
                    "status": str(DigestSendStatus.FAILED),
                    "failed_reason": reason,
                    "provider_message_id": None,
                    "retryable": retryable,
                }
            },
        )

    async def mark_skipped_empty(self, digest_id: str) -> None:
        await self.collection.update_one(
            {"digest_id": digest_id},
            {"$set": {"status": str(DigestSendStatus.SKIPPED_EMPTY)}},
        )

    async def list_recent(self, academy_id: str, limit: int) -> list[DigestSend]:
        cursor = (
            self.collection.find({"academy_id": academy_id})
            .sort("created_at", -1)
            .limit(max(0, limit))
        )
        return [self._from_doc(doc) async for doc in cursor]

    @staticmethod
    def _to_doc(d: DigestSend) -> dict[str, Any]:
        return {
            "digest_id": d.digest_id,
            "academy_id": d.academy_id,
            "coach_id": d.coach_id,
            "coach_email": d.coach_email,
            "digest_date": d.digest_date,
            "status": str(d.status),
            "provider_message_id": d.provider_message_id,
            "sent_at": d.sent_at,
            "failed_reason": d.failed_reason,
            "created_at": d.created_at,
            "kind": d.kind,
            "attempt_count": d.attempt_count,
            "retryable": d.retryable,
        }

    @staticmethod
    def _from_doc(doc: dict[str, Any]) -> DigestSend:
        # Test sends store a synthetic "<date>#test:<ulid>" digest_date; surface
        # only the human date for the delivery log.
        raw_date = str(doc.get("digest_date") or "")
        digest_date = raw_date.split("#", 1)[0]
        return DigestSend(
            digest_id=str(doc.get("digest_id") or ""),
            academy_id=str(doc.get("academy_id") or ""),
            coach_id=str(doc.get("coach_id") or ""),
            coach_email=doc.get("coach_email"),
            digest_date=digest_date,
            status=DigestSendStatus(str(doc.get("status") or DigestSendStatus.QUEUED)),
            provider_message_id=doc.get("provider_message_id"),
            sent_at=doc.get("sent_at"),
            failed_reason=doc.get("failed_reason"),
            created_at=doc.get("created_at"),
            kind=str(doc.get("kind") or "daily"),
            # Rows written before migration 0154 have no attempt_count.
            attempt_count=int(doc.get("attempt_count") or 1),
            retryable=bool(doc.get("retryable", True)),
        )
