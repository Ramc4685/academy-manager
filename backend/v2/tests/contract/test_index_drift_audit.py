"""`backend/scripts/index_drift_audit.py` — live indexes vs. the migrations (#836)."""

from __future__ import annotations

import copy

import mongomock_motor
import pytest

from backend.scripts.index_drift_audit import (
    KNOWN_LEGACY_UNIQUE,
    diff_indexes,
    dump_indexes,
    expected_indexes,
)


@pytest.fixture(scope="module")
async def expected():  # type: ignore[no-untyped-def]
    return await expected_indexes()


def _unique(*fields: str) -> dict[str, object]:
    return {"key": [[f, 1] for f in fields], "unique": True, "sparse": False, "partial": None}


async def test_a_database_built_from_the_migrations_has_no_drift(expected) -> None:  # type: ignore[no-untyped-def]
    report = diff_indexes(copy.deepcopy(expected), expected, {})

    assert report.ok
    assert report.missing == report.changed == report.unexpected_unique == []


async def test_the_835_index_is_reported_as_an_unexpected_unique(expected) -> None:  # type: ignore[no-untyped-def]
    """The exact production shape that blocked re-adding a dropped student."""
    live = copy.deepcopy(expected)
    live["enrollments"]["session_id_1_student_id_1"] = _unique("session_id", "student_id")

    report = diff_indexes(live, expected, {})

    assert not report.ok
    assert report.unexpected_unique == ["enrollments.session_id_1_student_id_1"]


async def test_an_allowlisted_legacy_unique_does_not_fail_but_is_still_listed(expected) -> None:  # type: ignore[no-untyped-def]
    live = copy.deepcopy(expected)
    live.setdefault("invites", {})["token_1"] = _unique("token")

    report = diff_indexes(live, expected, {"invites.token_1": "empty pre-v2 collection"})

    assert report.ok
    assert report.allowlisted_unique == ["invites.token_1"]
    assert report.stale_allowlist == []


async def test_an_allowlist_entry_whose_index_is_gone_is_called_out(expected) -> None:  # type: ignore[no-untyped-def]
    report = diff_indexes(copy.deepcopy(expected), expected, {"invites.token_1": "gone now"})

    assert report.ok
    assert report.stale_allowlist == ["invites.token_1"]


async def test_a_missing_migration_index_fails(expected) -> None:  # type: ignore[no-untyped-def]
    live = copy.deepcopy(expected)
    del live["students"]["student_id_unique_per_academy"]

    report = diff_indexes(live, expected, {})

    assert report.missing == ["students.student_id_unique_per_academy"]
    assert not report.ok


async def test_the_same_definition_under_another_name_is_not_missing(expected) -> None:  # type: ignore[no-untyped-def]
    live = copy.deepcopy(expected)
    live["students"]["renamed_by_hand"] = live["students"].pop("student_id_unique_per_academy")

    assert diff_indexes(live, expected, {}).ok


async def test_a_changed_partial_filter_fails(expected) -> None:  # type: ignore[no-untyped-def]
    """What prod looks like between deploying 0185 and applying it."""
    live = copy.deepcopy(expected)
    lock = live["enrollments"]["uq_registration_active_student_lock"]
    lock["partial"] = {**lock["partial"], "status": {"$in": ["active", "paused"]}}

    report = diff_indexes(live, expected, {})

    assert report.changed == ["enrollments.uq_registration_active_student_lock"]


async def test_a_collection_mongo_has_not_created_yet_is_reported_not_failed(expected) -> None:  # type: ignore[no-untyped-def]
    live = copy.deepcopy(expected)
    del live["students"]

    report = diff_indexes(live, expected, {})

    assert report.ok
    assert "students" in report.absent_collections


async def test_an_unexpected_plain_index_is_listed_but_never_fails(expected) -> None:  # type: ignore[no-untyped-def]
    live = copy.deepcopy(expected)
    live["enrollments"]["stripe_subscription_id_1"] = {
        "key": [["stripe_subscription_id", 1]],
        "unique": False,
        "sparse": False,
        "partial": None,
    }

    report = diff_indexes(live, expected, {})

    assert report.ok
    assert report.unexpected_plain == ["enrollments.stripe_subscription_id_1"]


async def test_dump_skips_the_id_index_and_keeps_the_partial_filter() -> None:
    db = mongomock_motor.AsyncMongoMockClient()["dump"]
    await db.things.create_index(
        [("academy_id", 1), ("code", 1)],
        unique=True,
        name="things_code",
        partialFilterExpression={"code": {"$type": "string"}},
    )

    dumped = await dump_indexes(db)

    assert dumped == {
        "things": {
            "things_code": {
                "key": [["academy_id", 1], ["code", 1]],
                "unique": True,
                "sparse": False,
                "partial": {"code": {"$type": "string"}},
            }
        }
    }


def test_every_allowlist_entry_carries_a_reason() -> None:
    assert all(len(reason) > 20 for reason in KNOWN_LEGACY_UNIQUE.values())
