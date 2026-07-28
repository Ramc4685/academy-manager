"""UIM11 — every rollup read carries an explicit academy_id filter.

The rollup is the one surface that spans academies, so the guarantee that
each underlying query is still single-tenant is worth asserting directly.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from backend.v2.contexts.billing.infrastructure.mongo_owner_rollup_reader import (
    MongoAcademyFinancialSnapshotReader,
)


class _FakeCursor:
    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self._docs = docs

    def __aiter__(self):
        async def _gen():
            for doc in self._docs:
                yield doc

        return _gen()


class _FakeCollection:
    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self._docs = docs
        self.filters: list[dict[str, Any]] = []

    def find(
        self, filter_: dict[str, Any], projection: dict[str, Any] | None = None
    ) -> _FakeCursor:
        self.filters.append(filter_)
        return _FakeCursor(self._docs)


class _FakeDb:
    def __init__(self, collections: dict[str, _FakeCollection]) -> None:
        self._collections = collections

    def __getitem__(self, name: str) -> _FakeCollection:
        return self._collections[name]


def _payment(month: str, amount: int, refunded: int = 0) -> dict[str, Any]:
    return {
        "amount_cents": amount,
        "refunded_cents": refunded,
        "created_at": datetime.strptime(f"{month}-15", "%Y-%m-%d").replace(tzinfo=UTC),
    }


@pytest.mark.asyncio
async def test_snapshot_nets_refunds_and_buckets_revenue_by_month() -> None:
    payments = _FakeCollection([_payment("2026-06", 5_000), _payment("2026-07", 3_000, 1_000)])
    invoices = _FakeCollection(
        [
            {"status": "open", "balance_due_cents": 2_500},
            {"status": "partially_paid", "balance_due_cents": 500},
            {"status": "open", "balance_due_cents": 0},
        ]
    )
    reader = MongoAcademyFinancialSnapshotReader(
        _FakeDb({"payments": payments, "invoices": invoices})
    )

    snapshot = await reader.read(academy_id="academy-a")

    assert snapshot.revenue_by_month == {"2026-06": 5_000, "2026-07": 2_000}
    assert snapshot.collected_cents == 7_000
    assert snapshot.outstanding_cents == 3_000
    assert snapshot.outstanding_invoice_count == 2


@pytest.mark.asyncio
async def test_every_query_filters_on_the_given_academy_id() -> None:
    payments = _FakeCollection([])
    invoices = _FakeCollection([])
    reader = MongoAcademyFinancialSnapshotReader(
        _FakeDb({"payments": payments, "invoices": invoices})
    )

    await reader.read(academy_id="academy-b")

    assert [f["academy_id"] for f in payments.filters] == ["academy-b"]
    assert [f["academy_id"] for f in invoices.filters] == ["academy-b"]


@pytest.mark.asyncio
async def test_months_filter_drops_out_of_range_payments() -> None:
    payments = _FakeCollection([_payment("2026-06", 5_000), _payment("2026-07", 3_000)])
    reader = MongoAcademyFinancialSnapshotReader(
        _FakeDb({"payments": payments, "invoices": _FakeCollection([])})
    )

    snapshot = await reader.read(academy_id="academy-a", months=("2026-07",))

    assert snapshot.revenue_by_month == {"2026-07": 3_000}
