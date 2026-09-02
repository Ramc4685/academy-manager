"""``missing_digest_claim_indexes`` names the claim indexes a database lacks.

Production ran with ``V2_RUN_MIGRATIONS_ON_BOOT=false`` and a registry stopped
at 0122, so the unique indexes from migrations 0125/0148 never existed and
nothing said so until every digest was re-sent hourly on 2026-09-02. The boot
check in ``main.py`` is only as good as this helper, so both directions are
pinned: a bare database reports both names, a migrated one reports nothing.
"""

from __future__ import annotations

import importlib

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.v2.composition.digests import (
    REQUIRED_DIGEST_CLAIM_INDEXES,
    missing_digest_claim_indexes,
)

_coach_indexes = importlib.import_module("backend.v2.migrations.0125_coach_digest_send_indexes")
_parent_indexes = importlib.import_module("backend.v2.migrations.0148_parent_digest_send_indexes")


@pytest.mark.asyncio
async def test_bare_database_reports_both_indexes_missing() -> None:
    db = AsyncMongoMockClient()["digest_index_check"]

    assert await missing_digest_claim_indexes(db) == [
        "coach_digest_sends_academy_coach_date_unique",
        "parent_digest_sends_academy_parent_date_unique",
    ]


@pytest.mark.asyncio
async def test_migrated_database_reports_nothing_missing() -> None:
    db = AsyncMongoMockClient()["digest_index_check"]
    await _coach_indexes.up(db)
    await _parent_indexes.up(db)

    assert await missing_digest_claim_indexes(db) == []


@pytest.mark.asyncio
async def test_each_collection_is_checked_independently() -> None:
    """Half-applied migrations (0125 but not 0148 — the parent digest shipped
    later) must still name the one that is absent."""
    db = AsyncMongoMockClient()["digest_index_check"]
    await _coach_indexes.up(db)

    assert await missing_digest_claim_indexes(db) == [
        "parent_digest_sends_academy_parent_date_unique"
    ]


def test_required_names_match_the_migrations() -> None:
    """The helper must look for the names the migrations actually create."""
    assert REQUIRED_DIGEST_CLAIM_INDEXES == {
        "coach_digest_sends": "coach_digest_sends_academy_coach_date_unique",
        "parent_digest_sends": "parent_digest_sends_academy_parent_date_unique",
    }
