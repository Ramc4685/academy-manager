"""Issue #820: the scheduled-action validator and unique index must admit an
``admin_drop_at_period_end`` row, or scheduling an admin drop at period end
500s in prod on "Document failed validation" — exactly like #657 and #675."""

from __future__ import annotations

import importlib
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.v2.contexts.enrollment.application.use_cases.scheduled_actions import (
    ScheduledActionType,
    ScheduledEnrollmentAction,
)

BASE = importlib.import_module(
    "backend.v2.migrations.0133_broader_validators_and_outbox_retry_lock"
)
FIX = importlib.import_module("backend.v2.migrations.0182_admin_drop_at_period_end")


def _schema() -> dict:
    return BASE.VALIDATORS["scheduled_enrollment_actions"]["$jsonSchema"]


def test_validator_admits_every_action_type_the_model_can_write() -> None:
    """The validator and the Literal are one vocabulary. A type the model can
    produce but Mongo rejects is a 500 that only shows up in production."""
    schema = _schema()
    assert set(ScheduledActionType.__args__) <= set(schema["properties"]["action_type"]["enum"])
    for field in ("outcome", "actor_id", "reason", "reason_code"):
        assert field in schema["properties"], field
        assert "null" in schema["properties"][field]["bsonType"], field
        assert field not in schema["required"], field
    # The decision fields are optional on the model too, so the two
    # pre-#820 types keep writing exactly the documents they always did.
    for field in ("outcome", "actor_id", "reason", "reason_code"):
        assert ScheduledEnrollmentAction.model_fields[field].default is None


@pytest.mark.asyncio
async def test_0182_reapplies_validator_and_adds_the_admin_drop_index() -> None:
    db = MagicMock()
    db.command = AsyncMock(return_value={"ok": 1})
    collection = MagicMock()
    collection.create_index = AsyncMock()
    db.__getitem__ = MagicMock(return_value=collection)

    await FIX.up(db)

    cmd = db.command.await_args.args[0]
    assert cmd["collMod"] == "scheduled_enrollment_actions"
    assert (
        "admin_drop_at_period_end"
        in (cmd["validator"]["$jsonSchema"]["properties"]["action_type"]["enum"])
    )
    [call] = collection.create_index.await_args_list
    assert call.kwargs["name"] == "unique_pending_admin_drop_at_period_end"
    assert call.kwargs["unique"] is True
    # Scoped to the new type: widening it to every period-end type would make
    # a parent self-cancel and an admin drop collide on one enrollment.
    assert call.kwargs["partialFilterExpression"] == {
        "status": "pending",
        "action_type": "admin_drop_at_period_end",
    }
