"""Per-academy Stripe Connect accounts (Slice I).

New tenant-scoped collection ``academy_connected_accounts``: one document per
academy holding its Stripe Connect merchant identity + onboarding
status/capabilities.

- Unique index on ``academy_id`` (one connected account per academy).
- Lookup index on ``stripe_account_id`` (Connect webhook account resolution).
- A Mongo JSON-schema validator (moderate/error) following the launch-validator
  pattern used elsewhere in this package.

Idempotent: index/validator creation is safe to re-run.
"""

from __future__ import annotations

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import CollectionInvalid, OperationFailure

version = "0139_connected_accounts"

OPT_BOOL = ["bool", "null"]
OPT_DATE = ["date", "null"]
OPT_STRING = ["string", "null"]

COLLECTION = "academy_connected_accounts"

VALIDATOR: dict[str, Any] = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["academy_id", "stripe_account_id"],
        "properties": {
            "academy_id": {"bsonType": "string"},
            "stripe_account_id": {"bsonType": "string"},
            "status": {"bsonType": OPT_STRING},
            "capabilities": {"bsonType": ["object", "null"]},
            "charges_enabled": {"bsonType": OPT_BOOL},
            "payouts_enabled": {"bsonType": OPT_BOOL},
            "created_at": {"bsonType": OPT_DATE},
            "updated_at": {"bsonType": OPT_DATE},
        },
    }
}


async def _apply_validator(
    db: AsyncIOMotorDatabase, collection_name: str, validator: dict[str, Any]
) -> None:
    try:
        await db.command(
            {
                "collMod": collection_name,
                "validator": validator,
                "validationLevel": "moderate",
                "validationAction": "error",
            }
        )
    except NotImplementedError:
        return
    except OperationFailure as exc:
        if exc.code != 26:
            raise
        try:
            await db.create_collection(
                collection_name,
                validator=validator,
                validationLevel="moderate",
                validationAction="error",
            )
        except CollectionInvalid:
            await db.command(
                {
                    "collMod": collection_name,
                    "validator": validator,
                    "validationLevel": "moderate",
                    "validationAction": "error",
                }
            )


async def up(db: AsyncIOMotorDatabase) -> None:
    collection = db[COLLECTION]
    await collection.create_index(
        "academy_id",
        unique=True,
        name="academy_connected_accounts_academy_unique",
    )
    await collection.create_index(
        "stripe_account_id",
        name="academy_connected_accounts_stripe_account",
    )

    await _apply_validator(db, COLLECTION, VALIDATOR)
