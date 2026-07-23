"""Mongo-backed ``MagicLinkRepository`` on the ``parent_magic_links`` collection.

NOT tenant-scoped: ``get_by_hash`` resolves a token by its unique hash alone.
Tenant binding is enforced one layer up, by ``ConsumeMagicLink`` comparing the
stored ``academy_id`` to the request's resolved tenant (see the port docstring)
— a repo query that silently filtered by tenant could not tell "wrong tenant"
apart from "unknown token".

Naive datetimes read back from Mongo (mongomock, or a driver storing without
tzinfo) are coerced to aware UTC so downstream ``is_expired`` comparisons never
mix aware and naive datetimes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pymongo import ReturnDocument

from backend.v2.contexts.identity.domain.models import MagicLinkRecord


def _as_utc(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class MongoMagicLinkRepository:
    """Read/write access to single-use parent auto-login tokens."""

    collection_name = "parent_magic_links"

    def __init__(self, db: Any) -> None:
        self._db = db
        self._links = db[self.collection_name]

    async def insert(self, record: MagicLinkRecord) -> None:
        await self._links.insert_one(
            {
                "magic_link_id": record.magic_link_id,
                "token_hash": record.token_hash,
                "user_id": record.user_id,
                "academy_id": record.academy_id,
                "next_path": record.next_path,
                "created_at": record.created_at,
                "expires_at": record.expires_at,
                "purge_at": record.purge_at,
                "used_at": record.used_at,
            }
        )

    async def get_by_hash(self, token_hash: str) -> MagicLinkRecord | None:
        doc = await self._links.find_one({"token_hash": token_hash})
        return self._to_record(doc) if doc else None

    async def mark_used(self, token_hash: str, *, used_at: datetime) -> bool:
        """Atomically stamp ``used_at`` iff the token is still unused.

        The ``used_at: None`` filter is the single-use guard: the update matches
        only an unconsumed token, so exactly one of two concurrent consumers
        succeeds. Returns whether this call claimed it.
        """
        doc = await self._links.find_one_and_update(
            {"token_hash": token_hash, "used_at": None},
            {"$set": {"used_at": used_at}},
            return_document=ReturnDocument.AFTER,
        )
        return doc is not None

    @staticmethod
    def _to_record(doc: dict[str, Any]) -> MagicLinkRecord:
        now = datetime.now(UTC)
        return MagicLinkRecord(
            magic_link_id=str(doc.get("magic_link_id") or doc["_id"]),
            token_hash=str(doc["token_hash"]),
            user_id=str(doc["user_id"]),
            academy_id=str(doc["academy_id"]),
            next_path=str(doc.get("next_path") or "/parent/dashboard"),
            created_at=_as_utc(doc.get("created_at")) or now,
            expires_at=_as_utc(doc.get("expires_at")) or now,
            purge_at=_as_utc(doc.get("purge_at")) or now,
            used_at=_as_utc(doc.get("used_at")),
        )
