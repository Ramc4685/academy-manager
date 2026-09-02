"""TTL index for ``verification_email_cooldowns``.

Rows in this collection are throttle state for the public
``POST /register/parent/verification-email`` endpoint, keyed by a hash of the
recipient address. ``purge_at`` TTL (``expireAfterSeconds=0``) lets Mongo reap
each row once it has outlived the rolling 24h send window, so the collection
does not grow one document per address ever seen — including addresses an
attacker merely typed at us.

No unique index is needed: ``_id`` is the address hash, and the primary key is
exactly what makes the conditional-upsert claim atomic (see
``MongoVerificationEmailCooldown``).
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0163_verification_email_cooldowns"


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    await db["verification_email_cooldowns"].create_index(
        "purge_at",
        expireAfterSeconds=0,
        name="verification_email_cooldowns_purge_at_ttl",
    )
