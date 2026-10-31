"""Invoice lookup by id or number is two equality reads, never an ``$or`` (#878)."""

from __future__ import annotations

from typing import Any

import mongomock_motor

from backend.v2.composition.invoice_naming import find_invoice_by_id_or_number


class _RecordingInvoices:
    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self.filters: list[dict[str, Any]] = []
        self._docs = docs

    async def find_one(
        self, query: dict[str, Any], projection: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        self.filters.append(query)
        return next((d for d in self._docs if all(d.get(k) == v for k, v in query.items())), None)


async def test_it_finds_by_id_then_by_number_within_the_academy() -> None:
    db = mongomock_motor.AsyncMongoMockClient()["test"]
    await db.invoices.insert_many(
        [
            {"academy_id": "acad-a", "invoice_id": "inv-1", "invoice_number": "INV-0001"},
            {"academy_id": "acad-b", "invoice_id": "inv-2", "invoice_number": "INV-0002"},
        ]
    )

    by_id = await find_invoice_by_id_or_number(db, "acad-a", "inv-1")
    by_number = await find_invoice_by_id_or_number(db, "acad-a", "INV-0001", {"_id": 1})

    assert by_id is not None and by_id["invoice_number"] == "INV-0001"
    assert by_number is not None and set(by_number) == {"_id"}
    assert await find_invoice_by_id_or_number(db, "acad-a", "INV-0002") is None


async def test_every_read_is_a_tenant_scoped_equality_the_partial_indexes_serve() -> None:
    invoices = _RecordingInvoices([])

    await find_invoice_by_id_or_number({"invoices": invoices}, "acad-a", "INV-0007")

    assert invoices.filters == [
        {"academy_id": "acad-a", "invoice_id": "INV-0007"},
        {"academy_id": "acad-a", "invoice_number": "INV-0007"},
    ]
