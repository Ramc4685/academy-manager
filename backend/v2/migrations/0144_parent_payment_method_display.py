"""Allow safe parent payment-method display fields.

Slice L adds non-sensitive display projections (brand/bank label + last4) to
``parent_billing_customers``. This is a new migration rather than an edit to
0142 so environments that already recorded 0142 still receive the validator
update at boot.
"""

from __future__ import annotations

import copy
import importlib
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0144_parent_payment_method_display"


def _validator() -> dict[str, Any]:
    migration_0142 = importlib.import_module("backend.v2.migrations.0142_ach_lifecycle")
    validator = copy.deepcopy(migration_0142.PARENT_BILLING_CUSTOMERS_VALIDATOR)
    properties = validator["$jsonSchema"]["properties"]
    properties["payment_method_label"] = {"bsonType": migration_0142.OPT_STRING}
    properties["payment_method_last4"] = {"bsonType": migration_0142.OPT_STRING}
    for role in ("primary", "fallback"):
        properties[f"{role}_payment_method_label"] = {"bsonType": migration_0142.OPT_STRING}
        properties[f"{role}_payment_method_last4"] = {"bsonType": migration_0142.OPT_STRING}
    method_properties = properties["autopay_payment_methods"]["items"]["properties"]
    method_properties["payment_method_label"] = {"bsonType": migration_0142.OPT_STRING}
    method_properties["payment_method_last4"] = {"bsonType": migration_0142.OPT_STRING}
    return validator


async def up(db: AsyncIOMotorDatabase) -> None:
    migration_0142 = importlib.import_module("backend.v2.migrations.0142_ach_lifecycle")
    await migration_0142._apply_validator(
        db,
        "parent_billing_customers",
        _validator(),
    )
