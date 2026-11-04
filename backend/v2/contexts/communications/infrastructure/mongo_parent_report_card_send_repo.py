"""Claim log for the parent monthly report card: one row per
``(academy_id, parent_id, report month)``; ``digest_date`` holds the month as
``YYYY-MM``.

Same claim rules as the parent daily digest (``digest_claim``), in its own
collection so the report card never blocks a digest or an evening win.
Unique index: migration 0214.
"""

from __future__ import annotations

from backend.v2.contexts.communications.infrastructure.mongo_parent_digest_send_repo import (
    MongoParentDigestSendRepository,
)


class MongoParentReportCardSendRepository(MongoParentDigestSendRepository):
    collection_name = "parent_report_card_sends"
