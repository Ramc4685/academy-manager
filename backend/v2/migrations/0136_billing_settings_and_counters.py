"""BillingSettings + atomic billing counters (Slice S0 shared primitives).

Two new tenant-scoped collections:
- ``billing_settings``: one document per academy (cash/ACH discount config).
- ``billing_counters``: one document per (academy_id, scope) — atomic
  monotonic counters, e.g. invoice numbering.

Idempotent: index/validator creation is safe to re-run.
"""

from __future__ import annotations

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import CollectionInvalid, OperationFailure

version = "0136_billing_settings_and_counters"

OPT_BOOL = ["bool", "null"]
OPT_DATE = ["date", "null"]
OPT_STRING = ["string", "null"]


def _schema(required: list[str], properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "$jsonSchema": {
            "bsonType": "object",
            "required": required,
            "properties": properties,
        }
    }


VALIDATORS: dict[str, dict[str, Any]] = {
    "billing_settings": _schema(
        ["academy_id"],
        {
            "academy_id": {"bsonType": "string"},
            "ach_discount_enabled": {"bsonType": OPT_BOOL},
            "ach_discount_percent": {"bsonType": ["int", "long", "double", "decimal", "null"]},
            "ach_discount_label": {"bsonType": OPT_STRING},
            "max_ach_discount_percent": {"bsonType": ["int", "long", "double", "decimal", "null"]},
            "disclosure_text": {"bsonType": OPT_STRING},
            "disclosure_version": {"bsonType": OPT_STRING},
            "effective_at": {"bsonType": OPT_DATE},
            "invoice_number_prefix": {"bsonType": OPT_STRING},
        },
    ),
    "billing_counters": _schema(
        ["academy_id", "scope", "seq"],
        {
            "academy_id": {"bsonType": "string"},
            "scope": {"bsonType": "string"},
            "seq": {"bsonType": ["int", "long"]},
        },
    ),
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
    settings = db["billing_settings"]
    await settings.create_index(
        "academy_id",
        unique=True,
        name="billing_settings_academy_unique",
    )

    counters = db["billing_counters"]
    await counters.create_index(
        [("academy_id", 1), ("scope", 1)],
        unique=True,
        name="billing_counters_academy_scope_unique",
    )

    for collection_name, validator in VALIDATORS.items():
        await _apply_validator(db, collection_name, validator)
