"""Payout period state guards on a real mongod (L7).

The driver hands datetimes back naive, so hydration must re-attach UTC before
``approve`` compares them with the clock; legacy drafts (no ``revenue_basis``)
must be recomputed first; and a write built from a stale load (reopen racing
mark-paid) must refuse with a conflict and leave the stored period alone.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from backend.v2.contexts.finance.application.use_cases.approve_payout_period import (
    ApprovePayoutPeriod,
)
from backend.v2.contexts.finance.domain.payout_period import (
    PayoutPeriod,
    PayoutPeriodConflictError,
    PayoutPeriodStateError,
    PersistedPayoutLine,
    mark_paid,
    reopen,
)
from backend.v2.contexts.finance.infrastructure.mongo_payout_audit_log import (
    MongoPayoutAuditLogRepository,
)
from backend.v2.contexts.finance.infrastructure.mongo_payout_period_repo import (
    MongoPayoutPeriodRepository,
)

pytestmark = pytest.mark.asyncio

JUNE_2 = datetime(2026, 6, 2, tzinfo=UTC)


def _period(**overrides) -> PayoutPeriod:
    base = dict(
        period_id="pp-1",
        academy_id="test-academy",
        coach_id="coach-A",
        period_start=datetime(2026, 5, 1, tzinfo=UTC),
        period_end=datetime(2026, 6, 1, tzinfo=UTC),
        currency="USD",
        total_minor=2_500,
        lines=[
            PersistedPayoutLine(
                occurrence_id="occ-1",
                coach_id="coach-A",
                basis="scheduled",
                minutes=Decimal("60"),
                amount_minor=2_500,
                currency="USD",
                rate_id="cr-1",
            )
        ],
        generated_at=datetime(2026, 6, 1, 6, tzinfo=UTC),
        revenue_basis="invoiced",
    )
    base.update(overrides)
    return PayoutPeriod(**base)


def _approve(real_db) -> ApprovePayoutPeriod:
    return ApprovePayoutPeriod(
        repository=MongoPayoutPeriodRepository(real_db),
        audit=MongoPayoutAuditLogRepository(real_db),
        clock=lambda: JUNE_2,
    )


async def test_approve_reads_naive_stored_datetimes_as_utc(real_db, acad) -> None:
    repo = MongoPayoutPeriodRepository(real_db)
    await repo.save(_period())
    raw = await real_db["payout_periods"].find_one({"period_id": "pp-1"})
    assert raw["period_end"].tzinfo is None  # what the driver really returns

    loaded = await repo.find_by_id("pp-1")
    assert loaded is not None and loaded.period_end.tzinfo is not None

    approved = await _approve(real_db).execute(period_id="pp-1")
    assert approved.status == "approved"
    assert approved.approved_at == JUNE_2


async def test_a_legacy_draft_must_be_recomputed_before_approval(real_db, acad) -> None:
    await MongoPayoutPeriodRepository(real_db).save(_period())
    await real_db["payout_periods"].update_one(
        {"period_id": "pp-1"}, {"$unset": {"revenue_basis": ""}}
    )

    with pytest.raises(PayoutPeriodStateError, match="recompute first"):
        await _approve(real_db).execute(period_id="pp-1")
    stored = await real_db["payout_periods"].find_one({"period_id": "pp-1"})
    assert stored["status"] == "draft"


async def test_a_stale_mark_paid_loses_to_a_reopen_and_changes_nothing(real_db, acad) -> None:
    repo = MongoPayoutPeriodRepository(real_db)
    await repo.save(_period())
    approved = await _approve(real_db).execute(period_id="pp-1")

    # Both writers loaded the approved period; the reopen lands first.
    stale = approved
    await repo.replace(reopen(approved), expected_status="approved")

    paid = mark_paid(stale, at=JUNE_2, method="check", amount_minor=2_500, reference="r-1")
    with pytest.raises(PayoutPeriodConflictError):
        await repo.replace(paid, expected_status=stale.status)

    stored = await real_db["payout_periods"].find_one({"period_id": "pp-1"})
    assert stored["status"] == "draft"
    assert stored.get("paid_at") is None and stored.get("paid_reference") is None

    with pytest.raises(LookupError):
        await repo.replace(_period(period_id="pp-missing"), expected_status="draft")
