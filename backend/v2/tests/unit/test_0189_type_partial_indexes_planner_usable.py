"""Migration 0189 — ``$type``-filtered partial indexes move to ``$gt: ""`` (#878).

A ``$type: "string"`` partial index enforces uniqueness but the planner never
uses it for an equality lookup. mongomock evaluates neither partial filters nor
query plans, so what is pinned here is the SHAPE, the preserved names, the
resumable swap, and that the target list keeps up with the migrations; planner
use was verified with ``explain()`` against a real MongoDB 7.
"""

from __future__ import annotations

import importlib
from typing import Any

import mongomock_motor

from backend.scripts.index_drift_audit import expected_indexes

_MODULE = "backend.v2.migrations.0189_type_partial_indexes_planner_usable"

#: ``$type`` indexes keyed on a bare id. #849 re-keys them per academy (and
#: fixes the filter in the same swap), so 0189 leaves them alone. An entry
#: leaves this list when #849 reaches it; nothing new may join it.
LEFT_TO_849 = {
    "academy_settings.academy_settings_id_unique",
    "expenses.expense_id_unique",
    "message_deliveries.message_deliveries_provider_message_id_unique",
    "messages.message_id_unique",
    "onboarding_applications.application_id_unique",
    "payouts.payout_id_unique",
    "waitlist.waitlist_id_unique",
    "waiver_signatures.waiver_signature_id_unique",
    "waiver_templates.waiver_template_id_unique",
}


def _module() -> Any:
    return importlib.import_module(_MODULE)


def _fresh_db():  # type: ignore[no-untyped-def]
    return mongomock_motor.AsyncMongoMockClient()["test"]


async def _seed_type_filtered_indexes(db) -> None:  # type: ignore[no-untyped-def]
    for collection, name, fields, unique, partial in _module().TARGETS:
        await db[collection].create_index(
            [(f, 1) for f in fields],
            unique=unique,
            partialFilterExpression=partial,
            name=name,
        )


async def _assert_swapped(db) -> None:  # type: ignore[no-untyped-def]
    module = _module()
    for collection, name, fields, unique, partial in module.TARGETS:
        info = await db[collection].index_information()
        assert name + "__swap" not in info
        assert info[name]["key"] == [(f, 1) for f in fields]
        assert bool(info[name].get("unique")) is unique
        assert info[name]["partialFilterExpression"] == module.planner_usable(partial)
        assert "$type" not in str(info[name]["partialFilterExpression"])


def test_only_string_type_clauses_change() -> None:
    assert _module().planner_usable(
        {"lock": {"$type": "string"}, "status": {"$in": ["active", "held"]}}
    ) == {"lock": {"$gt": ""}, "status": {"$in": ["active", "held"]}}


async def test_each_index_keeps_its_name_and_gains_the_planner_usable_filter() -> None:
    db = _fresh_db()
    await _seed_type_filtered_indexes(db)

    await _module().up(db)

    await _assert_swapped(db)


async def test_rerun_is_a_noop_and_a_fresh_database_gets_the_same_shape() -> None:
    db = _fresh_db()

    await _module().up(db)
    await _module().up(db)

    await _assert_swapped(db)


async def test_a_run_that_died_after_dropping_the_original_resumes() -> None:
    module = _module()
    db = _fresh_db()
    collection, name, fields, unique, partial = module.TARGETS[-1]
    # Twin built, original already dropped, final not yet rebuilt.
    await db[collection].create_index(
        [(f, 1) for f in fields],
        unique=unique,
        partialFilterExpression={k: {"$gte": ""} for k in partial},
        name=name + "__swap",
    )

    await module.up(db)

    await _assert_swapped(db)


async def test_the_legacy_payment_intent_field_is_indexed_where_it_is_read() -> None:
    module = _module()
    db = _fresh_db()

    await module.up(db)

    for collection in module.LEGACY_PI_COLLECTIONS:
        index = (await db[collection].index_information())[module.LEGACY_PI_INDEX]
        assert index["key"] == [("academy_id", 1), ("stripe_payment_intent", 1)]
        assert index["partialFilterExpression"] == {"stripe_payment_intent": {"$gt": ""}}
        assert not index.get("unique")


async def test_no_type_filtered_index_survives_the_migrations_except_849s() -> None:
    """The guard #878 asked for: a new ``$type`` partial index fails here."""
    survivors = {
        f"{collection}.{name}"
        for collection, specs in (await expected_indexes()).items()
        for name, spec in specs.items()
        if "$type" in str(spec.get("partial"))
    }

    assert survivors <= LEFT_TO_849, (
        "A `$type`-filtered partial index enforces uniqueness but serves no "
        'lookup (#878). Use {"<field>": {"$gt": ""}} instead: '
        f"{sorted(survivors - LEFT_TO_849)}"
    )
