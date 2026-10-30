"""Claim log for the parent evening win email: one row per
``(academy_id, parent_id, local date)``.

Same claim rules as the parent daily digest (``digest_claim``), in its own
collection so a family's morning digest and evening win never block each
other. Unique index: migration 0213.
"""

from __future__ import annotations

from backend.v2.contexts.communications.infrastructure.mongo_parent_digest_send_repo import (
    MongoParentDigestSendRepository,
)


class MongoParentWinSendRepository(MongoParentDigestSendRepository):
    collection_name = "parent_win_sends"
