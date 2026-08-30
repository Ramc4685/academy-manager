"""Mongo-backed parent digest-send repository.

Idempotency works exactly like the coach digest (``mongo_digest_send_repo``):
``try_claim`` is an insert-first lock against the unique
``(academy_id, parent_id, digest_date)`` index (migration 0148). A duplicate-key
error means the family was already claimed for that day, so the claim is refused
(returns ``None``) and the hourly scheduler sends nothing on a re-run — unless
the existing row is a retryable ``failed`` one, which is re-claimed rather than
refused (see ``digest_claim`` and issue #435).

The shared :class:`DigestSend` domain model has a coach-oriented ``coach_id``
field; here it carries the *parent's* user id. The mapping is contained to this
repo — the doc field is ``parent_id`` so the collection schema reads cleanly and
the admin coach-digest log (a different collection) stays coach-only.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pymongo.errors import DuplicateKeyError

from backend.v2.contexts.communications.application.ports import DigestSendRepository
from backend.v2.contexts.communications.domain.models import DigestSend, DigestSendStatus
from backend.v2.contexts.communications.infrastructure.digest_claim import reclaim_failed_send
from backend.v2.shared.ids import new_ulid
from backend.v2.shared.tenancy import TenantScopedRepository


class MongoParentDigestSendRepository(TenantScopedRepository, DigestSendRepository):
    collection_name = "parent_digest_sends"

    async def try_claim(
        self, academy_id: str, coach_id: str, digest_date: str
    ) -> DigestSend | None:
        # ``coach_id`` is the recipient id (a parent's user id here).
        digest = DigestSend.queued(
            digest_id=new_ulid(),
            academy_id=academy_id,
            coach_id=coach_id,
            coach_email=None,
            digest_date=digest_date,
            created_at=datetime.now(UTC),
        )
        try:
            await self.collection.insert_one(self._to_doc(digest))
        except DuplicateKeyError:
            doc = await reclaim_failed_send(
                self.collection,
                academy_id=academy_id,
                recipient_field="parent_id",
                recipient_id=coach_id,
                digest_date=digest_date,
            )
            return self._from_doc(doc) if doc is not None else None
        return digest

    async def record_test_send(
        self, academy_id: str, coach_id: str, digest_date: str
    ) -> DigestSend:
        # No admin test-send surface for the parent digest yet; store against a
        # synthetic always-unique date so the daily claim is never blocked.
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
            "parent_id": d.coach_id,
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
        raw_date = str(doc.get("digest_date") or "")
        digest_date = raw_date.split("#", 1)[0]
        return DigestSend(
            digest_id=str(doc.get("digest_id") or ""),
            academy_id=str(doc.get("academy_id") or ""),
            coach_id=str(doc.get("parent_id") or ""),
            coach_email=None,
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
