"""Payout period state guards on a real mongod (L7).

The driver hands datetimes back naive, so hydration must re-attach UTC before
``approve`` compares them with the clock; legacy drafts (no ``revenue_basis``)
must be recomputed first; and a write built from a stale load (reopen racing
mark-paid, approve racing recompute, two recomputes) must refuse with a
conflict and leave the stored period alone.
"""

from __future__ import annotations

import asyncio
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
    approve,
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
    await repo.replace(reopen(approved))

    paid = mark_paid(stale, at=JUNE_2, method="check", amount_minor=2_500, reference="r-1")
    with pytest.raises(PayoutPeriodConflictError):
        await repo.replace(paid)

    stored = await real_db["payout_periods"].find_one({"period_id": "pp-1"})
    assert stored["status"] == "draft"
    assert stored.get("paid_at") is None and stored.get("paid_reference") is None

    with pytest.raises(LookupError):
        await repo.replace(_period(period_id="pp-missing"))


def _recomputed(period: PayoutPeriod, *, amount_minor: int) -> PayoutPeriod:
    line = period.lines[0].model_copy(update={"amount_minor": amount_minor})
    return period.model_copy(update={"lines": [line], "total_minor": amount_minor})


async def _stored(real_db) -> dict:
    doc = await real_db["payout_periods"].find_one({"period_id": "pp-1"}, {"_id": 0})
    lines = (
        await real_db["payout_period_lines"].find({"period_id": "pp-1"}, {"_id": 0}).to_list(None)
    )
    return {"doc": doc, "lines": sorted(line["amount_minor"] for line in lines)}


async def test_an_approve_built_before_a_recompute_conflicts_and_changes_nothing(
    real_db, acad
) -> None:
    repo = MongoPayoutPeriodRepository(real_db)
    await repo.save(_period())
    stale = await repo.find_by_id("pp-1")
    assert stale is not None

    # Tab B recomputes first: new lines and a new total land.
    await repo.replace_with_lines(_recomputed(stale, amount_minor=4_000))
    before = await _stored(real_db)

    # Tab A approves what it loaded before the recompute.
    with pytest.raises(PayoutPeriodConflictError):
        await repo.replace(approve(stale, at=JUNE_2))

    after = await _stored(real_db)
    assert after == before
    assert after["doc"]["status"] == "draft"
    assert after["doc"]["total_minor"] == 4_000 and after["lines"] == [4_000]
    # The page still loads: header total and lines agree.
    reloaded = await repo.find_by_id("pp-1")
    assert reloaded is not None and reloaded.total_minor == 4_000


async def test_a_stale_mark_paid_after_reopen_recompute_and_reapprove_conflicts(
    real_db, acad
) -> None:
    """ABA: the status is back to ``approved``, but it is not the same approval."""
    repo = MongoPayoutPeriodRepository(real_db)
    await repo.save(_period())
    first = await _approve(real_db).execute(period_id="pp-1")

    stale = first  # tab A loaded the first approval and walks away
    reopened = await repo.replace(reopen(first))
    recomputed = await repo.replace_with_lines(_recomputed(reopened, amount_minor=1_000))
    await repo.replace(approve(recomputed, at=JUNE_2))
    before = await _stored(real_db)
    assert before["doc"]["status"] == "approved"

    paid = mark_paid(stale, at=JUNE_2, method="check", amount_minor=2_500, reference="r-1")
    with pytest.raises(PayoutPeriodConflictError):
        await repo.replace(paid)

    after = await _stored(real_db)
    assert after == before
    assert after["doc"].get("paid_at") is None


async def test_two_recomputes_from_one_load_conflict_instead_of_both_landing(real_db, acad) -> None:
    repo = MongoPayoutPeriodRepository(real_db)
    await repo.save(_period())
    loaded = await repo.find_by_id("pp-1")
    assert loaded is not None

    await repo.replace_with_lines(_recomputed(loaded, amount_minor=3_000))
    before = await _stored(real_db)
    with pytest.raises(PayoutPeriodConflictError):
        await repo.replace_with_lines(_recomputed(loaded, amount_minor=9_000))

    assert await _stored(real_db) == before
    assert before["lines"] == [3_000]


async def test_a_period_stored_before_versions_existed_reads_as_version_zero(real_db, acad) -> None:
    repo = MongoPayoutPeriodRepository(real_db)
    await repo.save(_period())
    await real_db["payout_periods"].update_one({"period_id": "pp-1"}, {"$unset": {"version": ""}})

    loaded = await repo.find_by_id("pp-1")
    assert loaded is not None and loaded.version == 0
    approved = await repo.replace(approve(loaded, at=JUNE_2))
    assert approved.status == "approved" and approved.version == 1


async def test_a_read_between_the_line_and_header_writes_sees_one_consistent_set(
    real_db, acad
) -> None:
    repo = MongoPayoutPeriodRepository(real_db)
    await repo.save(_period())
    loaded = await repo.find_by_id("pp-1")
    assert loaded is not None
    seen: list[tuple[int, list[int]]] = []
    real_set = repo._guarded_set

    async def observing_set(period, fields):
        # New lines are already inserted here; the header still points at the old set.
        before = await repo.find_by_id("pp-1")
        previous = await real_set(period, fields)
        after = await repo.find_by_id("pp-1")  # old lines not yet cleaned up
        for p in (before, after):
            assert p is not None
            seen.append((p.total_minor, [line.amount_minor for line in p.lines]))
        return previous

    repo._guarded_set = observing_set  # type: ignore[method-assign]
    await repo.replace_with_lines(_recomputed(loaded, amount_minor=4_000))

    assert seen == [(2_500, [2_500]), (4_000, [4_000])]
    assert (await _stored(real_db))["lines"] == [4_000]


async def test_an_interleaved_override_and_recompute_leave_one_whole_line_set(
    real_db, acad
) -> None:
    repo = MongoPayoutPeriodRepository(real_db)
    await repo.save(_period())
    loaded = await repo.find_by_id("pp-1")
    assert loaded is not None

    results = await asyncio.gather(
        repo.replace_with_lines(_recomputed(loaded, amount_minor=3_000)),
        repo.replace_with_lines(_recomputed(loaded, amount_minor=9_000)),
        return_exceptions=True,
    )

    assert sum(isinstance(r, PayoutPeriodConflictError) for r in results) == 1
    stored = await _stored(real_db)
    assert stored["lines"] in ([3_000], [9_000])
    assert stored["doc"]["total_minor"] == stored["lines"][0]
    reloaded = await repo.find_by_id("pp-1")
    assert (
        reloaded is not None and [line.amount_minor for line in reloaded.lines] == stored["lines"]
    )


async def test_a_late_cleanup_never_deletes_a_newer_writers_lines(real_db, acad) -> None:
    repo_a, repo_c = MongoPayoutPeriodRepository(real_db), MongoPayoutPeriodRepository(real_db)
    await repo_a.save(_period())
    loaded_a = await repo_a.find_by_id("pp-1")
    assert loaded_a is not None
    real_set = repo_a._guarded_set

    async def cas_then_stall(period, fields):
        previous = await real_set(period, fields)
        # A has won its compare-and-set but not cleaned up yet; C loads A's
        # write and completes a whole recompute of its own.
        loaded_c = await repo_c.find_by_id("pp-1")
        assert loaded_c is not None and loaded_c.total_minor == 3_000
        await repo_c.replace_with_lines(_recomputed(loaded_c, amount_minor=7_000))
        return previous

    repo_a._guarded_set = cas_then_stall  # type: ignore[method-assign]
    await repo_a.replace_with_lines(_recomputed(loaded_a, amount_minor=3_000))  # cleanup runs last

    stored = await _stored(real_db)
    assert stored["lines"] == [7_000]
    reloaded = await repo_c.find_by_id("pp-1")
    assert reloaded is not None and reloaded.total_minor == 7_000
    assert [line.amount_minor for line in reloaded.lines] == [7_000]
