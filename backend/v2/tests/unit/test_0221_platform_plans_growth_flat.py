"""Migration 0221 seeds the Growth and Flat plans once and never overwrites a
row that already exists for the code."""

from __future__ import annotations

import importlib
from datetime import UTC, datetime

import mongomock_motor
import pytest

_M0221 = importlib.import_module("backend.v2.migrations.0221_platform_plans_growth_flat")


def test_version_matches_the_file_stem() -> None:
    assert _M0221.version == "0221_platform_plans_growth_flat"


@pytest.mark.asyncio
async def test_seeds_growth_and_flat_and_is_idempotent() -> None:
    db = mongomock_motor.AsyncMongoMockClient()["test"]
    await _M0221.up(db)
    await _M0221.up(db)

    rows = {doc["code"]: doc async for doc in db["platform_plans"].find({})}
    assert set(rows) == {"growth", "flat"}
    growth, flat = rows["growth"], rows["flat"]
    assert growth["display_name"] == "Growth"
    assert growth["monthly_price_cents"] == 9900
    assert growth["features"] == ["ai"]
    assert growth["stripe_price_id"] is None
    assert growth["limits"] == {
        "max_active_students": None,
        "max_locations": None,
        "max_staff_members": None,
    }
    assert flat["monthly_price_cents"] == 4900
    assert flat["features"] == []
    assert flat["status"] == growth["status"] == "active"


@pytest.mark.asyncio
async def test_an_existing_growth_row_is_left_alone() -> None:
    db = mongomock_motor.AsyncMongoMockClient()["test"]
    now = datetime.now(UTC)
    await db["platform_plans"].insert_one(
        {
            "plan_id": "plan_custom",
            "code": "growth",
            "display_name": "Growth (owner edited)",
            "monthly_price_cents": 14900,
            "stripe_price_id": "price_live_123",
            "features": ["ai"],
            "status": "active",
            "created_at": now,
            "updated_at": now,
        }
    )
    await _M0221.up(db)

    growth = await db["platform_plans"].find_one({"code": "growth"})
    assert growth is not None
    assert growth["plan_id"] == "plan_custom"
    assert growth["monthly_price_cents"] == 14900
    assert growth["stripe_price_id"] == "price_live_123"
    assert await db["platform_plans"].count_documents({}) == 2
