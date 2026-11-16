"""Raw readers of ``payout_period_lines`` count only each period's current set (L7).

A recompute that dies between its header compare-and-set and its cleanup
leaves the replaced line set behind. Reports and the replacement-coach
snapshot must ignore it, the same way the repository's hydrate does.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from backend.v2.composition.replacement_payout_snapshots import (
    draft_payout_periods_for_occurrence,
)
from backend.v2.contexts.billing.infrastructure.admin_reports_read_model import (
    make_session_economics_report,
)
from backend.v2.contexts.finance.domain.payout_period import PayoutPeriod, PersistedPayoutLine
from backend.v2.contexts.finance.infrastructure.mongo_payout_period_repo import (
    MongoPayoutPeriodRepository,
)

pytestmark = pytest.mark.asyncio

ACADEMY = "test-academy"


def _line(occurrence_id: str, amount_minor: int) -> PersistedPayoutLine:
    return PersistedPayoutLine(
        occurrence_id=occurrence_id,
        coach_id="coach-A",
        basis="scheduled",
        minutes=Decimal("60"),
        amount_minor=amount_minor,
        currency="USD",
        rate_id="cr-1",
    )


async def _recomputed_with_stale_lines(real_db, *, status: str = "draft") -> None:
    """pp-1 currently holds occ-2 at 4,000; a stale save-era set holds occ-1 at 2,500."""
    repo = MongoPayoutPeriodRepository(real_db)
    await repo.save(
        PayoutPeriod(
            period_id="pp-1",
            academy_id=ACADEMY,
            coach_id="coach-A",
            period_start=datetime(2026, 4, 1, tzinfo=UTC),
            period_end=datetime(2026, 5, 1, tzinfo=UTC),
            currency="USD",
            total_minor=2_500,
            lines=[_line("occ-1", 2_500)],
            generated_at=datetime(2026, 5, 1, tzinfo=UTC),
            revenue_basis="invoiced",
        )
    )
    loaded = await repo.find_by_id("pp-1")
    assert loaded is not None
    await repo.replace_with_lines(
        loaded.model_copy(update={"lines": [_line("occ-2", 4_000)], "total_minor": 4_000})
    )
    # The crash: the replaced (unstamped) set was never cleaned up.
    await real_db["payout_period_lines"].insert_one(
        {
            "academy_id": ACADEMY,
            "period_id": "pp-1",
            "occurrence_id": "occ-1",
            "amount_minor": 2_500,
        }
    )
    if status != "draft":
        await real_db["payout_periods"].update_one(
            {"period_id": "pp-1"}, {"$set": {"status": status}}
        )


async def test_session_economics_counts_only_the_current_line_set(real_db, acad) -> None:
    await _recomputed_with_stale_lines(real_db)
    await real_db["sessions"].insert_one(
        {
            "session_id": "sess-1",
            "academy_id": ACADEMY,
            "title": "Beginner",
            "amount_cents": 0,
            "status": "scheduled",
            "start_at": datetime(2026, 4, 1, 22, tzinfo=UTC),
        }
    )
    await real_db["session_occurrences"].insert_many(
        [
            {
                "occurrence_id": occ,
                "academy_id": ACADEMY,
                "session_id": "sess-1",
                "template_session_id": "sess-1",
                "status": "scheduled",
                "start_at": datetime(2026, 4, day, 22, tzinfo=UTC),
                "end_at": datetime(2026, 4, day, 23, tzinfo=UTC),
            }
            for occ, day in (("occ-1", 1), ("occ-2", 8))
        ]
    )

    report = await make_session_economics_report(real_db)("2026-04")

    assert report["summary"]["coach_payroll_cents"] == 4_000


async def test_replacement_snapshot_ignores_a_period_only_a_stale_set_holds(real_db, acad) -> None:
    await _recomputed_with_stale_lines(real_db, status="approved")

    # Only the stale set holds occ-1: the approved period must not freeze the swap.
    assert (
        await draft_payout_periods_for_occurrence(
            real_db, academy_id=ACADEMY, occurrence_id="occ-1"
        )
        == []
    )
    # The current set holds occ-2, so the approved period still refuses it.
    with pytest.raises(ValueError, match="approved or paid"):
        await draft_payout_periods_for_occurrence(
            real_db, academy_id=ACADEMY, occurrence_id="occ-2"
        )
