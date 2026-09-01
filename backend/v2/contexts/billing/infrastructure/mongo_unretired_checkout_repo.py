"""Mongo record of Checkout Sessions that could NOT be retired.

Retiring a superseded Checkout Session is what stops one enrollment having two
payable sessions. Stripe refusing the expiry because the session is already
complete or expired is benign — that is the "parent paid on the old tab" race.
A transient failure (connection dropped, timeout, 5xx, rate limit) is not: the
session is still open, still payable, and nothing in the system remembers it.

Before #549 both looked identical to the caller, so the transient case was
logged at INFO and forgotten. This collection is the reconciliation handle:
every un-retired session id lands here with the error that stopped it, and a
later successful retirement of the same id clears the row.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.v2.shared.tenancy import TenantScopedRepository


class MongoUnretiredCheckoutSessionRepository(TenantScopedRepository):
    collection_name = "unretired_checkout_sessions"

    async def record(
        self,
        *,
        checkout_session_id: str,
        payment_id: str | None,
        reason: str,
        error: str,
        occurred_at: datetime,
    ) -> None:
        """Upsert one un-retired session, keyed by its Stripe id.

        Repeated failures for the same id update the row rather than pile up,
        so `attempts` doubles as "how long has this been stuck".
        """
        update: dict[str, Any] = {
            "$setOnInsert": {
                "checkout_session_id": checkout_session_id,
                "first_seen_at": occurred_at,
            },
            "$set": {
                "payment_id": payment_id,
                "reason": reason,
                "last_error": error,
                "last_attempt_at": occurred_at,
            },
            "$inc": {"attempts": 1},
        }
        await self._update_one(
            {"checkout_session_id": checkout_session_id},
            update,
            upsert=True,
        )

    async def clear(self, checkout_session_id: str) -> None:
        """Drop the row once the session really has been retired.

        Called on every successful expiry, so a session that failed transiently
        and was retired on the next attempt does not stay on the worklist.
        """
        await self._delete_one({"checkout_session_id": checkout_session_id})
