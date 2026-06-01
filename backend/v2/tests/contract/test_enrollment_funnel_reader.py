"""Contract tests for MongoApplicationFunnelReader.

Uses mongomock-motor (via the ``db`` fixture from contract/conftest.py)
to exercise the aggregation pipeline without a real Mongo instance.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.contexts.finance.infrastructure.mongo_application_funnel_reader import (
    MongoApplicationFunnelReader,
)


def _doc(
    app_id: str,
    academy_id: str,
    status: str,
    created_at: datetime | None = None,
) -> dict[str, object]:
    return {
        "application_id": app_id,
        "academy_id": academy_id,
        "status": status,
        "created_at": created_at or datetime(2026, 5, 15, 12, 0, tzinfo=UTC),
    }


@pytest.mark.asyncio
async def test_funnel_counts_groups_by_status(db):
    """Three docs with distinct statuses → each appears with count 1; one
    status with two docs → count 2."""
    col = db["onboarding_applications"]
    await col.insert_many(
        [
            _doc("a1", "acad-1", "DRAFT"),
            _doc("a2", "acad-1", "PENDING_APPROVAL"),
            _doc("a3", "acad-1", "APPROVED"),
            _doc("a4", "acad-1", "DRAFT"),  # second DRAFT
        ]
    )
    reader = MongoApplicationFunnelReader(db)
    counts = await reader.get_funnel_counts("acad-1", None)

    assert counts["DRAFT"] == 2
    assert counts["PENDING_APPROVAL"] == 1
    assert counts["APPROVED"] == 1
    assert len(counts) == 3


@pytest.mark.asyncio
async def test_funnel_filters_by_academy_id(db):
    """Documents belonging to a different academy must not be counted."""
    col = db["onboarding_applications"]
    await col.insert_many(
        [
            _doc("b1", "acad-A", "APPROVED"),
            _doc("b2", "acad-A", "APPROVED"),
            _doc("b3", "acad-B", "APPROVED"),  # different academy
        ]
    )
    reader = MongoApplicationFunnelReader(db)

    counts_a = await reader.get_funnel_counts("acad-A", None)
    counts_b = await reader.get_funnel_counts("acad-B", None)

    assert counts_a == {"APPROVED": 2}
    assert counts_b == {"APPROVED": 1}


@pytest.mark.asyncio
async def test_funnel_filters_by_period(db):
    """Only documents whose created_at falls in the YYYY-MM window are counted."""
    col = db["onboarding_applications"]
    await col.insert_many(
        [
            # Inside 2026-05
            _doc("c1", "acad-X", "DRAFT", datetime(2026, 5, 1, 0, 0, tzinfo=UTC)),
            _doc("c2", "acad-X", "DRAFT", datetime(2026, 5, 31, 23, 59, tzinfo=UTC)),
            # Outside — April and June
            _doc("c3", "acad-X", "DRAFT", datetime(2026, 4, 30, 23, 59, tzinfo=UTC)),
            _doc("c4", "acad-X", "DRAFT", datetime(2026, 6, 1, 0, 0, tzinfo=UTC)),
        ]
    )
    reader = MongoApplicationFunnelReader(db)
    counts = await reader.get_funnel_counts("acad-X", "2026-05")

    assert counts == {"DRAFT": 2}


@pytest.mark.asyncio
async def test_funnel_empty_returns_empty_dict(db):
    """When no documents match, an empty dict is returned — not an error."""
    reader = MongoApplicationFunnelReader(db)
    counts = await reader.get_funnel_counts("nonexistent-academy", None)
    assert counts == {}
