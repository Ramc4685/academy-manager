from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.contexts.billing.domain.tuition_discount import TuitionDiscount
from backend.v2.contexts.billing.infrastructure.mongo_tuition_discount_repo import (
    MongoTuitionDiscountRepository,
)


def _CLOCK() -> datetime:
    return datetime(2026, 6, 23, 12, 0, tzinfo=UTC)


def _policy(**kw) -> TuitionDiscount:
    base = dict(
        discount_id="disc-1",
        enrollment_id="enroll-1",
        student_id="student-1",
        category="scholarship",
        kind="waiver",
        effective_start="2026-06-01",
    )
    base.update(kw)
    return TuitionDiscount(**base)


@pytest.mark.asyncio
async def test_set_active_then_supersede(db, acad) -> None:
    repo = MongoTuitionDiscountRepository(db, clock=_CLOCK)

    await repo.set_active(_policy(discount_id="disc-1"), set_by="admin-1")
    await repo.set_active(
        _policy(discount_id="disc-2", kind="percent", percent_bps=1000),
        set_by="admin-1",
    )

    active = await db["enrollment_discounts"].count_documents(
        {"academy_id": acad, "enrollment_id": "enroll-1", "status": "active"}
    )
    superseded = await db["enrollment_discounts"].count_documents(
        {"academy_id": acad, "enrollment_id": "enroll-1", "status": "superseded"}
    )
    assert active == 1
    assert superseded == 1

    current = await repo.get_active("enroll-1")
    assert current is not None
    assert current.discount_id == "disc-2"
    assert current.kind == "percent"
    assert current.set_by == "admin-1"


@pytest.mark.asyncio
async def test_get_active_none_when_absent(db, acad) -> None:
    repo = MongoTuitionDiscountRepository(db, clock=_CLOCK)
    assert await repo.get_active("nope") is None


@pytest.mark.asyncio
async def test_remove_marks_ended(db, acad) -> None:
    repo = MongoTuitionDiscountRepository(db, clock=_CLOCK)
    await repo.set_active(_policy(), set_by="admin-1")

    await repo.remove("enroll-1", ended_by="admin-2")

    assert await repo.get_active("enroll-1") is None
    ended = await db["enrollment_discounts"].find_one(
        {"academy_id": acad, "enrollment_id": "enroll-1", "status": "ended"}
    )
    assert ended is not None
    assert ended["ended_by"] == "admin-2"


@pytest.mark.asyncio
async def test_active_by_enrollments_batch(db, acad) -> None:
    repo = MongoTuitionDiscountRepository(db, clock=_CLOCK)
    await repo.set_active(_policy(discount_id="d-a", enrollment_id="e-a"), set_by="admin-1")
    await repo.set_active(
        _policy(
            discount_id="d-b",
            enrollment_id="e-b",
            category="sibling",
            kind="amount_off",
            amount_off_cents=4000,
        ),
        set_by="admin-1",
    )

    found = await repo.active_by_enrollments(["e-a", "e-b", "e-missing"])
    assert set(found.keys()) == {"e-a", "e-b"}
    assert found["e-b"].category == "sibling"


@pytest.mark.asyncio
async def test_tenant_isolation(db, acad, other_acad) -> None:
    repo = MongoTuitionDiscountRepository(db, clock=_CLOCK)
    # other_acad is the active tenant on entry → write a policy there
    await repo.set_active(_policy(discount_id="d-other"), set_by="admin-x")

    from backend.v2.shared.tenancy.context import _current as _tv

    token = _tv.set(acad)
    try:
        assert await repo.get_active("enroll-1") is None
    finally:
        _tv.reset(token)
