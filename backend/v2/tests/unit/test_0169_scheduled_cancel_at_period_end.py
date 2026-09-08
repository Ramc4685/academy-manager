"""Issue #675: the scheduled-action validator and unique index must admit a
``cancel_at_period_end`` row (no pause_request_id) or the parent's
end-of-period self-cancel 500s in prod, exactly like #657."""

from __future__ import annotations

import importlib
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.v2.contexts.enrollment.application.use_cases.scheduled_actions import (
    ScheduledEnrollmentAction,
)

BASE = importlib.import_module(
    "backend.v2.migrations.0133_broader_validators_and_outbox_retry_lock"
)
FIX = importlib.import_module("backend.v2.migrations.0169_scheduled_cancel_at_period_end")


def _schema() -> dict:
    return BASE.VALIDATORS["scheduled_enrollment_actions"]["$jsonSchema"]


def test_validator_matches_the_widened_model() -> None:
    schema = _schema()
    assert "pause_request_id" not in schema["required"]
    assert "null" in schema["properties"]["pause_request_id"]["bsonType"]
    assert set(schema["properties"]["action_type"]["enum"]) == {
        "resume_from_pause",
        "cancel_at_period_end",
    }
    assert ScheduledEnrollmentAction.model_fields["pause_request_id"].annotation == (str | None)


@pytest.mark.asyncio
async def test_0169_reapplies_validator_and_rebuilds_partial_unique_indexes() -> None:
    db = MagicMock()
    db.command = AsyncMock(return_value={"ok": 1})
    collection = MagicMock()
    collection.drop_index = AsyncMock()
    collection.create_index = AsyncMock()
    db.__getitem__ = MagicMock(return_value=collection)

    await FIX.up(db)

    cmd = db.command.await_args.args[0]
    assert cmd["collMod"] == "scheduled_enrollment_actions"
    assert "pause_request_id" not in cmd["validator"]["$jsonSchema"]["required"]
    collection.drop_index.assert_awaited_once_with("unique_pause_action")
    by_name = {c.kwargs["name"]: c.kwargs for c in collection.create_index.await_args_list}
    assert by_name["unique_pause_action"]["unique"] is True
    assert by_name["unique_pause_action"]["partialFilterExpression"] == {
        "pause_request_id": {"$type": "string"}
    }
    assert by_name["unique_pending_cancel_at_period_end"]["unique"] is True
    assert by_name["unique_pending_cancel_at_period_end"]["partialFilterExpression"] == {
        "status": "pending",
        "action_type": "cancel_at_period_end",
    }


@pytest.mark.asyncio
async def test_0169_tolerates_a_missing_0113_index() -> None:
    from pymongo.errors import OperationFailure

    db = MagicMock()
    db.command = AsyncMock(return_value={"ok": 1})
    collection = MagicMock()
    collection.drop_index = AsyncMock(side_effect=OperationFailure("index not found", code=27))
    collection.create_index = AsyncMock()
    db.__getitem__ = MagicMock(return_value=collection)

    await FIX.up(db)

    assert collection.create_index.await_count == 2
