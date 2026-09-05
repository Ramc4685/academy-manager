"""#657: the enrollment_events validator must accept the string billing_result the
domain model and writers emit, or every admin remove/withdraw/pause 500s."""

from __future__ import annotations

import importlib
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.v2.contexts.enrollment.domain.events import EnrollmentLifecycleEvent

BASE = importlib.import_module(
    "backend.v2.migrations.0133_broader_validators_and_outbox_retry_lock"
)
FIX = importlib.import_module("backend.v2.migrations.0165_enrollment_events_billing_result_string")


def _billing_result_types() -> list[str]:
    return BASE.VALIDATORS["enrollment_events"]["$jsonSchema"]["properties"]["billing_result"][
        "bsonType"
    ]


def test_validator_allows_the_string_the_domain_model_declares() -> None:
    # Regression: 0133 said ['object','null'] while the model is `str | None`.
    assert "string" in _billing_result_types()
    assert "null" in _billing_result_types()
    assert EnrollmentLifecycleEvent.model_fields["billing_result"].annotation == (str | None)


@pytest.mark.asyncio
async def test_0165_reapplies_the_corrected_enrollment_events_validator() -> None:
    db = MagicMock()
    db.command = AsyncMock(return_value={"ok": 1})

    await FIX.up(db)

    db.command.assert_awaited_once()
    cmd = db.command.await_args.args[0]
    assert cmd["collMod"] == "enrollment_events"
    assert cmd["validationAction"] == "error"
    allowed = cmd["validator"]["$jsonSchema"]["properties"]["billing_result"]["bsonType"]
    assert "string" in allowed
