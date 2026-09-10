"""Issue #699: the enrollment status vocabulary migration.

Covers the pure canonical_status() mapping, the widened SEATLESS/
EnrollmentStatus dual-read, and the 0171 data-rewrite migration.
"""

from __future__ import annotations

import importlib
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.v2.contexts.enrollment.domain.models import (
    SEATLESS,
    EnrollmentStatus,
    canonical_status,
)

MIGRATION = importlib.import_module("backend.v2.migrations.0171_enrollment_status_vocabulary")


def test_canonical_status_maps_legacy_to_new_spelling() -> None:
    assert canonical_status("withdrawn") == "dropped"
    assert canonical_status("cancelled") == "deleted"


def test_canonical_status_is_identity_for_the_new_spelling_and_everything_else() -> None:
    assert canonical_status("dropped") == "dropped"
    assert canonical_status("deleted") == "deleted"
    assert canonical_status("active") == "active"
    assert canonical_status("held") == "held"
    assert canonical_status("reclaim_pending") == "reclaim_pending"
    # "paused" is deliberately NEVER mapped to "held" — see the design
    # contract's ESCALATE and domain/models.py's module docstring.
    assert canonical_status("paused") == "paused"


def test_seatless_carries_both_spellings_of_each_terminal_status() -> None:
    assert SEATLESS == {"paused", "cancelled", "deleted", "withdrawn", "dropped"}
    # Every SEATLESS member must canonicalize to something also representable
    # — i.e. no member is orphaned by the rename.
    for status in SEATLESS:
        assert canonical_status(status) in SEATLESS


def test_enrollment_status_literal_accepts_every_spelling() -> None:
    import typing

    values = typing.get_args(EnrollmentStatus)
    for expected in (
        "active",
        "paused",
        "held",
        "reclaim_pending",
        "cancelled",
        "deleted",
        "withdrawn",
        "dropped",
    ):
        assert expected in values


@pytest.mark.asyncio
async def test_0171_renames_enrollments_status_and_is_idempotent() -> None:
    db = MagicMock()
    enrollments = MagicMock()
    events = MagicMock()

    def _get(name: str) -> MagicMock:
        return {"enrollments": enrollments, "enrollment_events": events}[name]

    db.__getitem__ = MagicMock(side_effect=_get)

    # First call: one document per old value gets renamed.
    enrollments.update_many = AsyncMock(
        side_effect=[MagicMock(modified_count=3), MagicMock(modified_count=2)]
    )
    events.update_many = AsyncMock(
        side_effect=[MagicMock(modified_count=5), MagicMock(modified_count=4)]
    )

    await MIGRATION.up(db)

    enrollment_calls = enrollments.update_many.await_args_list
    assert enrollment_calls[0].args[0] == {"status": "withdrawn"}
    assert enrollment_calls[0].args[1] == {"$set": {"status": "dropped"}}
    assert enrollment_calls[1].args[0] == {"status": "cancelled"}
    assert enrollment_calls[1].args[1] == {"$set": {"status": "deleted"}}

    event_calls = events.update_many.await_args_list
    assert event_calls[0].args[0] == {"event_type": "withdrawn"}
    assert event_calls[0].args[1] == {"$set": {"event_type": "dropped"}}
    assert event_calls[1].args[0] == {"event_type": "cancelled"}
    assert event_calls[1].args[1] == {"$set": {"event_type": "deleted"}}

    # Second run: filters on the OLD value only, so a re-run against
    # already-rewritten data is a genuine no-op (idempotent).
    enrollments.update_many = AsyncMock(
        side_effect=[MagicMock(modified_count=0), MagicMock(modified_count=0)]
    )
    events.update_many = AsyncMock(
        side_effect=[MagicMock(modified_count=0), MagicMock(modified_count=0)]
    )
    await MIGRATION.up(db)
    for call in enrollments.update_many.await_args_list + events.update_many.await_args_list:
        assert call.args[0] in (
            {"status": "withdrawn"},
            {"status": "cancelled"},
            {"event_type": "withdrawn"},
            {"event_type": "cancelled"},
        )


def test_0171_never_touches_removed_event_type() -> None:
    """ "removed" is a distinct audit label (soft-cancel via the legacy
    DELETE /enrollments/{id} route) from "deleted" (a genuine hard-delete,
    #697's delete_if_status). Renaming it would collide two different
    historical facts into one value — see the migration's module docstring."""
    assert "removed" not in MIGRATION._EVENT_TYPE_RENAMES
    assert "removed" not in MIGRATION._EVENT_TYPE_RENAMES.values()


def test_0171_never_touches_unrelated_collections() -> None:
    """scheduled_enrollment_actions.status and
    student_billing_enrollments.status are different vocabularies (see the
    migration's module docstring) and must not appear in either rename map
    or be referenced by this migration's up()."""
    import inspect

    source = inspect.getsource(MIGRATION.up)
    assert "scheduled_enrollment_actions" not in source
    assert "student_billing_enrollments" not in source


def test_enrollments_status_and_event_type_are_unconstrained_strings() -> None:
    """Ground truth this migration relies on: neither field is enum-
    constrained by the schema validators, so (unlike #657/#658) no collMod
    is needed before the data rewrite. If either validator is ever narrowed
    to an enum, this migration's docstring assumption is no longer true and
    a 0172 must widen it BEFORE this migration's rename is applied again."""
    v0132 = importlib.import_module("backend.v2.migrations.0132_launch_indexes_and_validators")
    v0133 = importlib.import_module(
        "backend.v2.migrations.0133_broader_validators_and_outbox_retry_lock"
    )
    enrollments_schema = v0132.VALIDATORS["enrollments"]["$jsonSchema"]
    assert enrollments_schema["properties"]["status"] == {"bsonType": "string"}
    events_schema = v0133.VALIDATORS["enrollment_events"]["$jsonSchema"]
    assert "enum" not in events_schema["properties"]["event_type"]
