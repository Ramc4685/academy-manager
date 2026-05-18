"""Mongo payment repository contract tests."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.v2.contexts.billing.domain.models import Payment
from backend.v2.contexts.billing.infrastructure.mongo_payment_repo import MongoPaymentRepository


@pytest.mark.asyncio
async def test_list_for_parent_maps_domain_payments(db, acad) -> None:
    repo = MongoPaymentRepository(db)
    now = datetime.now(timezone.utc)
    await repo.save(
        Payment(
            payment_id="pay-parent-1",
            academy_id=acad,
            parent_id="parent-1",
            session_id="session-1",
            amount_cents=2500,
            status="pending",
            created_at=now,
            updated_at=now,
        )
    )

    rows = await repo.list_for_parent("parent-1")

    assert [row.payment_id for row in rows] == ["pay-parent-1"]
    assert rows[0].amount_cents == 2500
