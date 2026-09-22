"""Every partial index the migrations build must serve the lookup it is keyed for (#894).

The drift audit compares index DEFINITIONS, and mongomock evaluates neither
partial filters nor query plans, so nothing else can tell whether MongoDB's
planner will actually pick an index. It did not for 34 of them (#878): a
``{"$type": "string"}`` partial filter enforces uniqueness but never serves an
equality lookup, and every Stripe-webhook and attendance read was a collection
scan. This test asks the real planner. It replays every migration into a
throwaway database on a real ``mongod`` (the CI backend job's service, which
runs the same major version as production; locally whatever listens on
27017), inserts one document per partial index that satisfies its filter, and
``explain()``s the equality lookup on the index's key fields. The winning plan
must name the index.

Skipped, not failed, when no ``mongod`` is reachable: the unit suite must stay
runnable without one. CI always has one.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from backend.v2.migrations import runner

#: Partial indexes that exist only to enforce uniqueness and are never a
#: lookup key, with the reason. Each entry must still exist (a stale entry
#: fails), and each is still checked for the WRONG answer only if its
#: collection is looked up by that field one day: remove it here first.
UNIQUENESS_ONLY: dict[str, str] = {
    "message_deliveries.message_deliveries_provider_message_id_unique": (
        "Provider-issued id; nothing reads message_deliveries by it (#878, #849)."
    ),
}

#: Lookups production code issues on hot paths, as (collection, filter, index
#: that must serve it). These are the literal filter shapes from #878; a
#: rewrite into a shape the planner cannot use (an ``$or`` across
#: partial-indexed fields, for example, which MongoDB 8.0 scans) fails here.
HOT_LOOKUPS: list[tuple[str, dict[str, Any], str]] = [
    (
        "ledger_payments",
        {"academy_id": "acad_0", "ledger_idempotency_key": "k"},
        "academy_ledger_payment_idempotency_unique",
    ),
    (
        "ledger_payments",
        {"academy_id": "acad_0", "stripe_payment_intent_id": "pi"},
        "academy_ledger_payment_intent_unique",
    ),
    (
        "payments",
        {"academy_id": "acad_0", "stripe_payment_intent_id": "pi"},
        "academy_stripe_pi_unique",
    ),
    (
        "payments",
        {"academy_id": "acad_0", "stripe_checkout_session_id": "cs"},
        "academy_checkout_session_unique",
    ),
    (
        "payment_attempts",
        {"academy_id": "acad_0", "idempotency_key": "k"},
        "academy_payment_attempt_idempotency_unique",
    ),
    (
        "onboarding_applications",
        {"academy_id": "acad_0", "payment_id": "pay"},
        "academy_payment_id",
    ),
    (
        "attendance",
        {"academy_id": "acad_0", "occurrence_id": "occ", "student_id": "stu"},
        "attendance_occurrence_unique",
    ),
    (
        "invoices",
        {"academy_id": "acad_0", "invoice_number": "INV-1"},
        "invoices_academy_invoice_number_unique",
    ),
    (
        "subscriptions",
        {"academy_id": "acad_0", "stripe_checkout_session_id": "cs"},
        "academy_subscription_checkout_session_unique",
    ),
    # The digest mark_sent / mark_failed / mark_skipped_empty updates (#880).
    # 0191 dropped the plain digest_id stopgap, so only this index can serve them.
    (
        "coach_digest_sends",
        {"academy_id": "acad_0", "digest_id": "dg"},
        "coach_digest_send_id_per_academy_uq",
    ),
    (
        "parent_digest_sends",
        {"academy_id": "acad_0", "digest_id": "dg"},
        "parent_digest_send_id_per_academy_uq",
    ),
]


def _mongo_url() -> str:
    return (
        os.environ.get("V2_MONGO_URL") or os.environ.get("MONGO_URL") or "mongodb://127.0.0.1:27017"
    )


@pytest.fixture
async def db() -> AsyncIterator[AsyncIOMotorDatabase[Any]]:
    client: AsyncIOMotorClient[Any] = AsyncIOMotorClient(
        _mongo_url(), serverSelectionTimeoutMS=1500
    )
    try:
        await client.admin.command("ping")
    except Exception as exc:  # any failure means "no mongod here"
        pytest.skip(f"no reachable mongod at {_mongo_url()}: {exc}")
    name = f"zz_planner_usability_{os.getpid()}_{uuid.uuid4().hex[:8]}"
    assert name not in await client.list_database_names()
    database = client[name]
    try:
        for module in runner._discover_migrations():
            await module.up(database)
        yield database
    finally:
        await client.drop_database(name)
        client.close()


async def _partial_indexes(
    database: AsyncIOMotorDatabase[Any],
) -> list[tuple[str, str, dict[str, Any], set[str]]]:
    """Every partial index, with the set of fields any index on its collection keys on."""
    out = []
    for collection in sorted(await database.list_collection_names()):
        info = await database[collection].index_information()
        keyed = {field for spec in info.values() for field, _direction in spec["key"]}
        for name, spec in info.items():
            if spec.get("partialFilterExpression"):
                out.append((collection, name, spec, keyed))
    return out


def _value_satisfying(clause: Any, unique: str) -> Any:
    """A value satisfying one partial-filter clause, row-unique where the clause allows.

    Row-unique matters when the filtered field is also a key of a sibling
    unique index (``academy_settings.academy_id``); a constant would collide.
    """
    if not isinstance(clause, dict):
        return clause  # plain equality: only this value satisfies it
    if "$in" in clause:
        return clause["$in"][0]
    if clause.get("$exists") or "$type" in clause:
        return unique
    for op in ("$gt", "$gte"):
        if op in clause:
            bound = clause[op]
            # Partial-filter comparisons are type-bracketed: the value must
            # be of the bound's type, not merely sort after it.
            if isinstance(bound, int | float):
                return bound + 1 + int(unique.rsplit("-", 1)[-1])
            return f"{bound}{unique}"
    if "$ne" in clause:
        return unique
    raise NotImplementedError(f"no value picker for partial filter clause {clause!r}")


def _winning_index_names(plan: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    if "indexName" in plan:
        names.add(plan["indexName"])
    for child in plan.get("inputStages", []) + (
        [plan["inputStage"]] if "inputStage" in plan else []
    ):
        names |= _winning_index_names(child)
    for key in ("queryPlan", "outerStage", "innerStage"):
        if key in plan:
            names |= _winning_index_names(plan[key])
    return names


async def _candidate_and_winning(
    database: AsyncIOMotorDatabase[Any], collection: str, query: dict[str, Any]
) -> tuple[set[str], set[str]]:
    """Index names in every plan the planner considered, and in the one it chose.

    A sibling index can legitimately win (a covering non-partial index, or an
    equally good one on a one-row-per-academy collection). What #878 showed is
    that a ``$type``-filtered index is never even a candidate.
    """
    explained = await database.command(
        "explain", {"find": collection, "filter": query}, verbosity="queryPlanner"
    )
    planner = explained["queryPlanner"]
    winning = _winning_index_names(planner["winningPlan"])
    candidates = set(winning)
    for rejected in planner.get("rejectedPlans", []):
        candidates |= _winning_index_names(rejected)
    return candidates, winning


async def _keys_examined_with_hint(
    database: AsyncIOMotorDatabase[Any], collection: str, query: dict[str, Any], index: str
) -> int:
    """Index keys read when the lookup is forced onto ``index``.

    Sibling-independent: a usable index answers an equality on its keys with
    one key; an index the planner cannot bound (the #878 ``$type`` shape) is
    walked end to end, so the count equals the rows in it.
    """
    explained = await database.command(
        "explain",
        {"find": collection, "filter": query, "hint": index},
        verbosity="executionStats",
    )
    return int(explained["executionStats"]["totalKeysExamined"])


ROWS_PER_INDEX = 3


async def test_every_partial_index_serves_the_equality_lookup_on_its_keys(
    db: AsyncIOMotorDatabase[Any],
) -> None:
    unserved: list[str] = []
    seen: set[str] = set()
    for n, (collection, name, spec, keyed) in enumerate(await _partial_indexes(db)):
        full = f"{collection}.{name}"
        seen.add(full)
        partial: dict[str, Any] = spec["partialFilterExpression"]
        keys = [field for field, _direction in spec["key"]]
        # A few rows per index, distinct on every field any index in the
        # collection keys on, so rows never collide on a sibling unique index
        # (a full unique index treats a missing field as null) and a walk of
        # the whole index is distinguishable from a point lookup.
        rows = []
        for j in range(ROWS_PER_INDEX):
            doc = {field: f"{field}-{n}-{j}" for field in keyed}
            for field, clause in partial.items():
                doc[field] = _value_satisfying(clause, f"{field}-{n}-{j}")
            rows.append(doc)
        # The collection validators reject synthetic rows; the planner does
        # not care, and an empty collection would give a meaningless plan.
        await db[collection].insert_many(rows, bypass_document_validation=True)
        query = {field: rows[1][field] for field in keys}
        for field in partial:
            query[field] = rows[1][field]
        if await _keys_examined_with_hint(db, collection, query, name) > 1:
            unserved.append(full)

    stale = sorted(set(UNIQUENESS_ONLY) - seen)
    assert not stale, f"UNIQUENESS_ONLY names indexes no migration builds: {stale}"
    assert set(UNIQUENESS_ONLY) <= set(unserved), (
        "UNIQUENESS_ONLY lists an index the planner now serves; drop it from the list: "
        f"{sorted(set(UNIQUENESS_ONLY) - set(unserved))}"
    )
    failing = sorted(set(unserved) - set(UNIQUENESS_ONLY))
    assert not failing, (
        "The planner cannot bound these partial indexes for an equality lookup on "
        "their own keys (#878): they enforce uniqueness and serve no read. A "
        '`{"$type": "string"}` filter is the usual cause; use `{"$gt": ""}`. '
        f"Unserved: {failing}"
    )


async def test_hot_path_lookups_are_index_served(db: AsyncIOMotorDatabase[Any]) -> None:
    misserved: list[str] = []
    for collection, query, index in HOT_LOOKUPS:
        await db[collection].insert_one(dict(query), bypass_document_validation=True)
        _candidates, winning = await _candidate_and_winning(db, collection, query)
        if index not in winning:
            misserved.append(f"{collection} {query} -> {sorted(winning) or 'COLLSCAN'}")

    assert not misserved, (
        "These hot-path lookups are not served by the index built for them (#878). "
        f"Expected the named index in the winning plan: {misserved}"
    )


async def test_the_check_bites_on_a_type_filtered_index(db: AsyncIOMotorDatabase[Any]) -> None:
    """The #878 shape must fail this file's check, or the check proves nothing."""
    coll = db["zz_type_filtered_probe"]
    await coll.create_index(
        [("academy_id", 1), ("thing_id", 1)],
        unique=True,
        partialFilterExpression={"thing_id": {"$type": "string"}},
        name="thing_id_type_filtered",
    )
    await coll.create_index(
        [("academy_id", 1), ("thing_id", 1)],
        partialFilterExpression={"thing_id": {"$gt": ""}},
        name="thing_id_planner_usable",
    )
    await coll.insert_many([{"academy_id": "a", "thing_id": f"t{i}"} for i in range(3)])

    query = {"academy_id": "a", "thing_id": "t1"}
    _candidates, winning = await _candidate_and_winning(db, coll.name, query)

    assert winning == {"thing_id_planner_usable"}
    assert await _keys_examined_with_hint(db, coll.name, query, "thing_id_type_filtered") == 3
    assert await _keys_examined_with_hint(db, coll.name, query, "thing_id_planner_usable") == 1
