"""Per-address send budget for the public verification-email endpoint.

Why Mongo and not an in-process dict: the API runs on several Fly machines and
restarts on every deploy, so an in-memory counter is both per-machine (an
attacker just retries until they land on a fresh one) and erased on deploy.
Every other durable throttle in this codebase already lives in Mongo with a TTL
index — ``login_attempts`` (migration 0110), ``idempotency_keys`` (0001),
``parent_magic_links`` (0149) — so this follows the same shape rather than
introducing Redis for one counter.

The budget is claimed with a single conditional upsert, which makes the check
atomic across machines:

* the filter matches only a document whose cooldown has already elapsed *and*
  whose 24h send count is under the cap;
* if no document exists, the upsert inserts one — first send allowed;
* if a document exists but fails the filter, the upsert cannot match and tries
  to insert a second row on the same ``_id``, which the primary key rejects
  with ``DuplicateKeyError``. That error *is* the "denied" answer, not a bug.

``sends`` keeps only the most recent ``_MAX_PER_DAY`` timestamps (``$slice``),
so ``sends.0`` is the oldest send that still counts against the daily cap: if
that one is older than 24h, fewer than the cap happened in the window.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import DuplicateKeyError

COLLECTION = "verification_email_cooldowns"

#: Minimum gap between two verification emails to the same address. Long enough
#: that a flood is not worth an attacker's time, short enough that a parent who
#: genuinely missed the first mail can retry within one support conversation.
COOLDOWN = timedelta(minutes=5)

#: Hard ceiling per address per rolling 24h. Without it the cooldown alone still
#: permits ~288 messages a day at one victim, which is a mail bomb by any
#: reasonable definition.
MAX_PER_DAY = 5

#: How long a row outlives its last send before the TTL index reaps it. Must
#: exceed the 24h window or the daily cap would reset early.
RETENTION = timedelta(days=2)


def _key(email: str) -> str:
    """Stable id for an address, hashed rather than stored in the clear.

    The row is a throttling artifact, not a user record: it has no owner, no
    retention policy of its own beyond the TTL, and — critically — anyone can
    create one for an address they do not own just by hitting the endpoint. A
    hash keeps the collection from becoming an unauthenticated log of "someone
    typed this email address here".
    """
    return hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()


class MongoVerificationEmailCooldown:
    """Atomic per-address send budget backed by ``verification_email_cooldowns``."""

    def __init__(
        self,
        db: AsyncIOMotorDatabase[Any],
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._collection = db[COLLECTION]
        self._now = now or (lambda: datetime.now(UTC))

    async def claim_send(self, email: str) -> bool:
        """Reserve one send for ``email``. ``False`` means "throttled, do not send".

        Claiming *before* the send (rather than recording after) is deliberate:
        a send that fails halfway still consumed the recipient's attention
        budget, and a retry loop on a failing provider must not be able to
        bypass the cap.
        """
        now = self._now()
        day_floor = now - timedelta(hours=24)
        try:
            await self._collection.update_one(
                {
                    "_id": _key(email),
                    "cooldown_until": {"$lte": now},
                    "$or": [
                        # Fewer than MAX_PER_DAY sends recorded at all...
                        {f"sends.{MAX_PER_DAY - 1}": {"$exists": False}},
                        # ...or the oldest of the last MAX_PER_DAY has aged out
                        # of the window, so the window holds fewer than the cap.
                        {"sends.0": {"$lt": day_floor}},
                    ],
                },
                {
                    "$set": {
                        "cooldown_until": now + COOLDOWN,
                        "purge_at": now + RETENTION,
                    },
                    "$push": {"sends": {"$each": [now], "$slice": -MAX_PER_DAY}},
                },
                upsert=True,
            )
        except DuplicateKeyError:
            # A row exists that the filter rejected: still cooling down, or the
            # daily cap is spent. See the module docstring.
            return False
        return True
