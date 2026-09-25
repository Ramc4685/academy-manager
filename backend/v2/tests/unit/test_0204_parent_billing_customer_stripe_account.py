"""Migration 0204 allows ``stripe_account_id`` on ``parent_billing_customers``
as an optional string, keeps every earlier property, and is idempotent."""

from __future__ import annotations

import importlib

_M0204 = importlib.import_module(
    "backend.v2.migrations.0204_parent_billing_customer_stripe_account"
)
_M0144 = importlib.import_module("backend.v2.migrations.0144_parent_payment_method_display")


def test_version_matches_the_file_stem() -> None:
    assert _M0204.version == "0204_parent_billing_customer_stripe_account"


def test_validator_adds_only_the_optional_account() -> None:
    new = _M0204.validator()["$jsonSchema"]
    old = _M0144._validator()["$jsonSchema"]
    assert new["properties"]["stripe_account_id"] == {"bsonType": ["string", "null"]}
    assert {k: v for k, v in new["properties"].items() if k != "stripe_account_id"} == (
        old["properties"]
    )
    # Optional: existing (platform) rows have no field and stay valid.
    assert "stripe_account_id" not in new["required"]
    assert new["required"] == old["required"]


class _Db:
    def __init__(self) -> None:
        self.commands: list[dict] = []

    async def command(self, cmd: dict) -> dict:
        self.commands.append(cmd)
        return {"ok": 1}


async def test_up_is_idempotent() -> None:
    db = _Db()
    await _M0204.up(db)
    await _M0204.up(db)
    assert len(db.commands) == 2
    assert db.commands[0] == db.commands[1]
    assert db.commands[0]["collMod"] == "parent_billing_customers"
    assert db.commands[0]["validationLevel"] == "moderate"
