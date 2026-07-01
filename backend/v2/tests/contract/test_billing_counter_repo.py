from __future__ import annotations

import asyncio

from backend.v2.contexts.billing.infrastructure.mongo_billing_counter_repo import (
    MongoBillingCounterRepository,
)


async def test_next_value_is_monotonic(db, acad) -> None:
    repo = MongoBillingCounterRepository(db)

    values = [await repo.next_value(scope="invoice_number") for _ in range(3)]

    assert values == [1, 2, 3]


async def test_next_value_scopes_are_independent(db, acad) -> None:
    repo = MongoBillingCounterRepository(db)

    invoice_1 = await repo.next_value(scope="invoice_number")
    receipt_1 = await repo.next_value(scope="receipt_number")
    invoice_2 = await repo.next_value(scope="invoice_number")

    assert invoice_1 == 1
    assert receipt_1 == 1
    assert invoice_2 == 2


async def test_tenant_isolation_counters_do_not_leak_across_academies(db, acad, other_acad) -> None:
    from backend.v2.shared.tenancy.context import _current as _tv

    repo = MongoBillingCounterRepository(db)

    token = _tv.set(acad)
    try:
        await repo.next_value(scope="invoice_number")
        await repo.next_value(scope="invoice_number")
    finally:
        _tv.reset(token)

    token = _tv.set(other_acad)
    try:
        other_value = await repo.next_value(scope="invoice_number")
    finally:
        _tv.reset(token)

    assert other_value == 1


async def test_next_value_is_race_safe_under_concurrency(db, acad) -> None:
    repo = MongoBillingCounterRepository(db)

    results = await asyncio.gather(*(repo.next_value(scope="invoice_number") for _ in range(20)))

    assert sorted(results) == list(range(1, 21))
    assert len(set(results)) == 20
