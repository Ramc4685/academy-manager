"""#608 — admin financial reports bucket months on the academy's clock.

A payment taken at 23:30 on the last evening of a month in Chicago lands at
05:30 UTC on the 1st. Bucketing that in UTC reported it as next month's money,
in a different month from the invoice it settled. These pin the corrected
behaviour in both the Mongo aggregation and the Python fallback paths.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from backend.v2.contexts.billing.application.admin_money import month_bounds
from backend.v2.contexts.billing.infrastructure.admin_reports_read_model import (
    AdminEffectiveRevenueQuery,
)
from backend.v2.contexts.billing.infrastructure.cash_received import cash_received_in_period
from backend.v2.shared.tenancy.context import tenant_scope

ACADEMY = "acad"
CHICAGO = "America/Chicago"
# 2026-01-31 23:30 America/Chicago.
BOUNDARY_AT = datetime(2026, 2, 1, 5, 30, tzinfo=UTC)
MIDMONTH_AT = datetime(2026, 2, 15, 12, tzinfo=UTC)


def _dateToString_stages(pipeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "$dateToString" and isinstance(value, dict):
                    found.append(value)
                _walk(value)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(pipeline)
    return found


def test_revenue_pipelines_bucket_in_the_academy_timezone() -> None:
    ledger = AdminEffectiveRevenueQuery._ledger_revenue_pipeline({}, CHICAGO)
    legacy = AdminEffectiveRevenueQuery._legacy_revenue_pipeline({}, CHICAGO)

    stages = _dateToString_stages(ledger) + _dateToString_stages(legacy)
    assert stages, "expected $dateToString month bucketing in both pipelines"
    assert all(stage.get("timezone") == CHICAGO for stage in stages)


@pytest.mark.asyncio
async def test_effective_revenue_buckets_a_month_end_evening_payment_locally() -> None:
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["test_db"]
    await db["academies"].insert_one({"academy_id": ACADEMY, "timezone": CHICAGO})
    await db["ledger_payments"].insert_many(
        [
            {
                "payment_id": "pay-boundary",
                "academy_id": ACADEMY,
                "status": "succeeded",
                "paid_at": BOUNDARY_AT,
                "paid_amount_cents": 4_000,
            },
            {
                "payment_id": "pay-midmonth",
                "academy_id": ACADEMY,
                "status": "succeeded",
                "paid_at": MIDMONTH_AT,
                "paid_amount_cents": 1_000,
            },
        ]
    )

    with tenant_scope(ACADEMY):
        months = await AdminEffectiveRevenueQuery(db).execute()

    assert months == {"2026-01": 4_000, "2026-02": 1_000}


@pytest.mark.asyncio
async def test_cash_received_counts_the_boundary_payment_in_the_local_month() -> None:
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["test_db"]
    await db["ledger_payments"].insert_one(
        {
            "payment_id": "pay-boundary",
            "academy_id": ACADEMY,
            "status": "succeeded",
            "paid_at": BOUNDARY_AT,
            "paid_amount_cents": 4_000,
        }
    )

    start, end = month_bounds("2026-01", timezone_name=CHICAGO)
    january = await cash_received_in_period(
        db, academy_id=ACADEMY, start=start, end=end, timezone_name=CHICAGO
    )
    assert january.net_cents == 4_000

    utc_start, utc_end = month_bounds("2026-01")
    utc_january = await cash_received_in_period(
        db, academy_id=ACADEMY, start=utc_start, end=utc_end
    )
    assert utc_january.net_cents == 0
