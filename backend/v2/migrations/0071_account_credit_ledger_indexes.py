from __future__ import annotations

from typing import Any

version = "0071_account_credit_ledger_indexes"


async def _drop_conflicting_index_for_key(
    collection: Any, keys: list[tuple[str, int]], desired_name: str
) -> None:
    """Drop any index that already covers ``keys`` under a different name.

    Mongo rejects creating an index whose key spec matches an existing index
    but whose name differs (error 85, IndexOptionsConflict). Later migrations
    (e.g. 0132) recreate these same keys with explicit names, so a full replay
    must reconcile to the canonical name rather than the auto-generated one.
    """
    if not hasattr(collection, "index_information"):
        return
    indexes = await collection.index_information()
    for name, info in indexes.items():
        if name != desired_name and info.get("key") == keys:
            await collection.drop_index(name)


async def up(db) -> None:
    parent_status_keys = [("academy_id", 1), ("parent_id", 1), ("status", 1)]
    await _drop_conflicting_index_for_key(
        db.account_credit_ledger, parent_status_keys, "academy_credit_parent_status"
    )
    await db.account_credit_ledger.create_index(
        parent_status_keys, name="academy_credit_parent_status"
    )

    expires_keys = [("academy_id", 1), ("expires_at", 1)]
    await _drop_conflicting_index_for_key(
        db.account_credit_ledger, expires_keys, "academy_credit_expires"
    )
    await db.account_credit_ledger.create_index(
        expires_keys, name="academy_credit_expires"
    )

    application_keys = [("academy_id", 1), ("credit_id", 1), ("invoice_id", 1)]
    await _drop_conflicting_index_for_key(
        db.credit_applications, application_keys, "academy_credit_application_unique"
    )
    await db.credit_applications.create_index(
        application_keys,
        unique=True,
        name="academy_credit_application_unique",
    )
