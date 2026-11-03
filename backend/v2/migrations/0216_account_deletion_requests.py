"""Self-service account deletion requests (mobile M5, D1).

Global collection (one Firebase account spans academies). Unique ``user_id``
so a repeated request stores one row; ``(status, execute_after)`` serves the
executor's due-request scan (D3). New empty collection, so both builds are instant.
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0216_account_deletion_requests"


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    requests = db["account_deletion_requests"]
    await requests.create_index(
        "user_id", unique=True, name="account_deletion_requests_user_unique"
    )
    await requests.create_index(
        [("status", 1), ("execute_after", 1)], name="account_deletion_requests_due"
    )
