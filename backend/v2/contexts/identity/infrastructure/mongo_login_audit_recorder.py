"""Append sign-ins to the academy audit trail, once per token (#468).

`login_attempts` (migration 0110) already carries a 24h TTL index on
`updated_at` and had no writer; it is the dedupe store here. Its `_id` is the
token-scoped key, so the insert itself is the "have we recorded this session
yet?" test — no read-then-write race, and the row ages out on its own.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from pymongo.errors import DuplicateKeyError

from backend.v2.shared.ids import new_ulid


class MongoLoginAuditRecorder:
    """Writes `audit_logs` rows for logins, deduped via `login_attempts`."""

    def __init__(self, db: Any) -> None:
        self._db = db

    async def record_login(
        self,
        *,
        user_id: str,
        academy_id: str,
        membership_id: str,
        roles: Sequence[str],
        provider: str | None,
        persona: str | None,
        dedupe_key: str,
    ) -> None:
        now = datetime.now(UTC)
        try:
            await self._db["login_attempts"].insert_one(
                {
                    "_id": dedupe_key,
                    "user_id": user_id,
                    "academy_id": academy_id,
                    "provider": provider,
                    "updated_at": now,
                }
            )
        except DuplicateKeyError:
            # This token already logged its sign-in; every later request on it
            # is the same session, not a new login.
            return

        await self._db["audit_logs"].insert_one(
            {
                "audit_id": f"audit_{new_ulid()}",
                "academy_id": academy_id,
                "actor_id": user_id,
                "action": "user_logged_in",
                "entity_type": "user",
                "entity_id": user_id,
                "created_at": now,
                "metadata": {
                    "provider": provider,
                    "persona": persona,
                    "roles": list(roles),
                    "membership_id": membership_id,
                },
            }
        )
