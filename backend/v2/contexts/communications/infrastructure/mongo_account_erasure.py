"""Communications share of a self-service account deletion (mobile M5, D3).

Messages stay so the academy's threads still read (owner decision 5) but show
the author as "Deleted user"; delivery rows drop the copied address; the
person's email preferences go. Every query names its ``academy_id``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

DELETED_NAME = "Deleted user"


class MongoCommunicationsErasure:
    def __init__(self, db: Any) -> None:
        self._db = db

    async def erase(self, *, academy_id: str, user_ids: Sequence[str]) -> None:
        ids = list(user_ids)
        await self._db["messages"].update_many(
            {"academy_id": academy_id, "sender_id": {"$in": ids}},
            {"$set": {"author_display_name": DELETED_NAME}},
        )
        await self._db["message_deliveries"].update_many(
            {"academy_id": academy_id, "recipient_user_id": {"$in": ids}},
            {"$unset": {"recipient_email": ""}},
        )
        await self._db["email_preferences"].delete_many(
            {"academy_id": academy_id, "user_id": {"$in": ids}}
        )
