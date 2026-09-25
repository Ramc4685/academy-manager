"""Allow ``stripe_account_id`` on ``parent_billing_customers`` (direct charges).

A parent's Stripe customer and saved payment methods live on ONE Stripe
account. Direct charges put every non-house academy's customers on its own
connected account, so the record now names that account in
``stripe_account_id`` (an optional string). Absent means the PLATFORM account:
every existing row, and every house-academy row going forward, keeps its
current shape — no data is read or changed here.

No index is added: the record stays one per ``(academy_id, parent_id)``
(``academy_parent_billing_customer_unique``), and Stripe customer ids are
unique across accounts, so ``academy_stripe_customer_unique`` still holds.

The validator is rebuilt from 0144's (which extends 0142's) plus the new
property, applied with the same ``collMod`` helper, ``validationLevel:
moderate``. Idempotent: re-applying the same validator is a no-op.
"""

from __future__ import annotations

import importlib
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0204_parent_billing_customer_stripe_account"


def validator() -> dict[str, Any]:
    migration_0142 = importlib.import_module("backend.v2.migrations.0142_ach_lifecycle")
    migration_0144 = importlib.import_module(
        "backend.v2.migrations.0144_parent_payment_method_display"
    )
    schema: dict[str, Any] = migration_0144._validator()
    schema["$jsonSchema"]["properties"]["stripe_account_id"] = {
        "bsonType": migration_0142.OPT_STRING
    }
    return schema


async def up(db: AsyncIOMotorDatabase[Any]) -> None:
    migration_0142 = importlib.import_module("backend.v2.migrations.0142_ach_lifecycle")
    await migration_0142._apply_validator(db, "parent_billing_customers", validator())
