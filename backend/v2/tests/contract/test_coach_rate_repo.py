"""Mongo coach-rate repository contract tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.contexts.coaching.application.use_cases.manage_coach_rates import (
    SetCoachPayRate,
    SetCoachPayRateCommand,
)
from backend.v2.contexts.coaching.infrastructure.mongo_coach_rate_repo import (
    MongoCoachRateRepository,
)


@pytest.mark.asyncio
async def test_set_rate_supersedes_mongo_rate_with_naive_effective_from(db, acad) -> None:
    await db["coach_rates"].insert_one(
        {
            "academy_id": acad,
            "rate_id": "cr-existing",
            "coach_id": "coach-1",
            "billing_unit": "per_session",
            "amount_minor": 2500,
            "percent_bps": None,
            "currency": "USD",
            "effective_from": datetime(2026, 1, 1),
            "effective_until": None,
            "status": "active",
        }
    )
    use_case = SetCoachPayRate(
        rates=MongoCoachRateRepository(db),
        clock=lambda: datetime(2026, 6, 1, tzinfo=UTC),
        id_factory=lambda: "cr-new",
    )

    rate = await use_case.execute(
        SetCoachPayRateCommand(
            coach_id="coach-1",
            billing_unit="percent_of_revenue",
            percent_bps=3000,
            currency="MYR",
        )
    )

    assert rate.rate_id == "cr-new"
    old = await db["coach_rates"].find_one({"academy_id": acad, "rate_id": "cr-existing"})
    assert old is not None
    assert old["status"] == "superseded"
    assert old["effective_until"].replace(tzinfo=UTC) == datetime(2026, 6, 1, tzinfo=UTC)
