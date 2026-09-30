"""Forward-looking fee reads after scheduled plan price changes, on a REAL mongod.

Follow-up to PR 26 (#1017). Real ``mongod`` with every migration applied
(``real_db``): the change lookup is a multikey ``$in`` on ``session_ids``
and the change documents pass the 0212 index and the billing validators, which
mongomock does not enforce. Skipped (not failed) when no mongod listens.

Pinned on the BLNO-shaped academy of ``test_plan_price_change_real_mongo``
(Chicago clock, "now" is 2026-09-29, so September is the current month):

* with no change on record, projected income, session economics and the
  percent-of-revenue payroll basis read exactly today's numbers for every
  month (the legacy ``monthly_price_cents``-only class is still left out of
  the two reports, as today);
* with a change scheduled for November, a projection for November or later
  uses the new fee, October and the current month the old one, and payroll
  for an already-closed month is unchanged;
* once the daily job has flipped the class at November (the change is
  "applied"), a later report for a month before November still reads the old
  fee it was billed at, the current month the stored (new) fee; two chained
  changes (November, then January) each apply from their own month;
* another academy's change on the same class ids moves nothing here;
* "start autopay" reads the fee of the month its first charge collects
  (October here), through the same month-aware read as checkout; an unpriced
  class reads $0 in both, and autopay refuses it instead of inventing $25.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from backend.v2.composition.parent import compose_parent
from backend.v2.contexts.billing.application.use_cases import parent_billing
from backend.v2.contexts.billing.domain.errors import AutopayClassUnpriced
from backend.v2.contexts.billing.infrastructure.admin_reports_read_model import (
    make_projected_income_report,
    make_session_economics_report,
)
from backend.v2.contexts.billing.infrastructure.mongo_plan_price_changes import (
    MongoProjectedClassFees,
)
from backend.v2.contexts.coaching.infrastructure.mongo_payout_read_models import (
    MongoPayableOccurrenceQuery,
)
from backend.v2.shared.config import get_settings
from backend.v2.shared.money import round_money_minor
from backend.v2.shared.tenancy.context import _current as _tenant
from backend.v2.tests.contract.test_plan_price_change_real_mongo import (
    NEW,
    OLD,
    OTHER,
    _clock,
    _Kit,
    _seed_academy,
)
from backend.v2.tests.unit.test_parent_composition import (
    _AutopaySetupStripe,
    _connected_account_doc,
)

#: Two payable juniors classes a month in each of these months.
_MONTHS = ("2026-08", "2026-09", "2026-10", "2026-11", "2026-12")


@pytest.fixture
def allow_app_origin(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("V2_CORS_ORIGINS", "https://app.example.com")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def _seed_occurrences(db: Any, acad: str) -> None:
    """Two payable juniors classes per month, coached by coach-1."""
    for period in _MONTHS:
        year, month = (int(p) for p in period.split("-"))
        for day in (8, 15):
            await db["session_occurrences"].insert_one(
                {
                    "academy_id": acad,
                    "occurrence_id": f"juniors_{period}_{day}",
                    "session_id": "juniors",
                    "start_at": datetime(year, month, day, 18, 0, tzinfo=UTC),
                    "end_at": datetime(year, month, day, 19, 0, tzinfo=UTC),
                    "status": "scheduled",
                    "scheduled_coach_id": "coach-1",
                    "is_payable": True,
                }
            )


def _reports(db: Any, *, clock: Any = _clock) -> tuple[Any, Any]:
    fees = MongoProjectedClassFees(db, clock=clock)
    return (
        make_projected_income_report(db, class_fees=fees),
        make_session_economics_report(db, class_fees=fees),
    )


async def _payroll_basis(
    db: Any, acad: str, *, month_aware: bool = True, clock: Any = _clock
) -> dict[str, Any]:
    query = MongoPayableOccurrenceQuery(
        db, class_fees=MongoProjectedClassFees(db, clock=clock) if month_aware else None
    )
    rows = await query.list_in_period(
        academy_id=acad,
        period_start=datetime(2026, 8, 1, tzinfo=UTC),
        period_end=datetime(2027, 1, 1, tzinfo=UTC),
    )
    return {row.occurrence_id: row.expected_revenue_minor for row in rows}


def _per_occurrence(fee: int) -> int:
    """Two active juniors enrollments (e5 is paused), two classes a month."""
    return round_money_minor(Decimal(fee) * Decimal(2) / Decimal(2))


async def _economics(report: Any, period: str) -> dict[str, int]:
    result = await report(period)
    return {row["session_id"]: row["monthly_fee_cents"] for row in result["sessions"]}


# ------------------------------------------------ no change: today's numbers


@pytest.mark.asyncio
async def test_without_a_change_every_projection_reads_todays_numbers(real_db, acad) -> None:
    await _seed_academy(real_db, acad)
    await _seed_occurrences(real_db, acad)
    projected, economics = _reports(real_db)

    for period in _MONTHS:
        result = await projected(period)
        # juniors 2 x OLD + squad 1 x OLD; adults stores only the legacy
        # ``monthly_price_cents``, which this report has never read.
        assert result["total_cents"] == 3 * OLD
        assert result["manual_cents"] == 3 * OLD
        assert {row["session_id"]: row["expected_cents"] for row in result["by_session"]} == {
            "juniors": 2 * OLD,
            "squad": OLD,
        }
        assert await _economics(economics, period) == {"juniors": OLD}

    month_aware = await _payroll_basis(real_db, acad)
    assert month_aware == await _payroll_basis(real_db, acad, month_aware=False)
    assert set(month_aware.values()) == {_per_occurrence(OLD)}
    assert await real_db["plan_price_changes"].count_documents({}) == 0


# ------------------------------------------------ a change scheduled for M


@pytest.mark.asyncio
async def test_a_scheduled_change_moves_projections_from_its_month_only(real_db, acad) -> None:
    await _seed_academy(real_db, acad)
    await _seed_occurrences(real_db, acad)
    kit = _Kit(real_db)
    before = await _payroll_basis(real_db, acad)

    await kit.schedule.execute(kit.cmd(acad, "2026-11"))
    projected, economics = _reports(real_db)

    # A closed month, the current month and the month before the change.
    for period in ("2026-08", "2026-09", "2026-10"):
        assert (await projected(period))["total_cents"] == 3 * OLD
        assert await _economics(economics, period) == {"juniors": OLD}
    # The change's month and later: juniors (linked) moves, squad (custom) not.
    for period in ("2026-11", "2026-12"):
        result = await projected(period)
        assert result["total_cents"] == 2 * NEW + OLD
        rows = {row["session_id"]: row for row in result["by_session"]}
        assert rows["juniors"]["monthly_fee_cents"] == NEW
        assert rows["juniors"]["expected_cents"] == 2 * NEW
        assert rows["squad"]["expected_cents"] == OLD
        assert await _economics(economics, period) == {"juniors": NEW}

    basis = await _payroll_basis(real_db, acad)
    for occurrence_id, value in basis.items():
        period = occurrence_id.split("_")[1]
        assert value == _per_occurrence(NEW if period >= "2026-11" else OLD), occurrence_id
        if period < "2026-11":
            # Closed, current and next month: exactly what they read before.
            assert value == before[occurrence_id], occurrence_id


@pytest.mark.asyncio
async def test_another_academys_change_on_the_same_class_ids_moves_nothing(real_db, acad) -> None:
    await _seed_academy(real_db, acad)
    await _seed_occurrences(real_db, acad)
    token = _tenant.set(OTHER)
    try:
        await _seed_academy(real_db, OTHER)
        kit = _Kit(real_db)
        await kit.schedule.execute(kit.cmd(OTHER, "2026-11"))
    finally:
        _tenant.reset(token)
    assert await real_db["plan_price_changes"].count_documents({"academy_id": OTHER}) == 1

    projected, economics = _reports(real_db)
    assert (await projected("2026-12"))["total_cents"] == 3 * OLD
    assert await _economics(economics, "2026-12") == {"juniors": OLD}
    assert set((await _payroll_basis(real_db, acad)).values()) == {_per_occurrence(OLD)}


def _clock_on(year: int, month: int, day: int) -> Any:
    return lambda: datetime(year, month, day, 17, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_after_the_flip_past_months_keep_the_fee_they_were_billed_at(real_db, acad) -> None:
    await _seed_academy(real_db, acad)
    await _seed_occurrences(real_db, acad)
    kit = _Kit(real_db)
    before = await _payroll_basis(real_db, acad)

    await kit.schedule.execute(kit.cmd(acad, "2026-11"))
    assert (await kit.apply_due.execute(academy_id=acad, period="2026-11")).applied == 1
    change = await real_db["plan_price_changes"].find_one({"academy_id": acad})
    assert change["status"] == "applied"
    assert "juniors" in change["flipped_session_ids"]
    juniors = await real_db["sessions"].find_one({"academy_id": acad, "session_id": "juniors"})
    assert juniors["amount_cents"] == NEW

    # Reports run in mid-December: December is the current month. The flip
    # also wrote ``amount_cents`` on the legacy adults class (fields kept in
    # step), so from here the report counts adults (one active enrollment).
    december = _clock_on(2026, 12, 15)
    projected, economics = _reports(real_db, clock=december)
    for period in ("2026-08", "2026-09", "2026-10"):
        # Billed at the old fee; the flipped stored fee must not rewrite them.
        result = await projected(period)
        assert result["total_cents"] == 4 * OLD, period
        fees = {row["session_id"]: row["monthly_fee_cents"] for row in result["by_session"]}
        assert fees == {"juniors": OLD, "adults": OLD, "squad": OLD}, period
        assert await _economics(economics, period) == {"juniors": OLD}, period
    for period in ("2026-11", "2026-12", "2027-01"):
        assert (await projected(period))["total_cents"] == 3 * NEW + OLD, period
        # Session economics lists classes with occurrences (seeded to Dec).
        if period in _MONTHS:
            assert await _economics(economics, period) == {"juniors": NEW}, period

    basis = await _payroll_basis(real_db, acad, clock=december)
    for occurrence_id, value in basis.items():
        period = occurrence_id.split("_")[1]
        assert value == _per_occurrence(NEW if period >= "2026-11" else OLD), occurrence_id
        if period < "2026-11":
            # Payroll for months closed before the change: unchanged by the flip.
            assert value == before[occurrence_id], occurrence_id


@pytest.mark.asyncio
async def test_two_chained_changes_each_apply_from_their_own_month(real_db, acad) -> None:
    await _seed_academy(real_db, acad)
    await _seed_occurrences(real_db, acad)
    kit = _Kit(real_db)
    newer = NEW + 1_000

    await kit.schedule.execute(kit.cmd(acad, "2026-11"))
    assert (await kit.apply_due.execute(academy_id=acad, period="2026-11")).applied == 1
    await kit.schedule.execute(kit.cmd(acad, "2027-01", price=newer))
    statuses = sorted(
        [
            [doc["status"], doc["effective_period"]]
            async for doc in real_db["plan_price_changes"].find({"academy_id": acad})
        ]
    )
    assert statuses == [["applied", "2026-11"], ["scheduled", "2027-01"]]

    december = _clock_on(2026, 12, 15)
    projected, economics = _reports(real_db, clock=december)
    expected = {
        "2026-10": OLD,  # past, before both: the fee it was billed at
        "2026-11": NEW,  # past, first change
        "2026-12": NEW,  # current month: the stored fee
        "2027-01": newer,  # future: the second (scheduled) change
        "2027-02": newer,
    }
    for period, fee in expected.items():
        # juniors (2) + adults (1, flipped too) at the plan fee; squad custom.
        assert (await projected(period))["total_cents"] == 3 * fee + OLD, period
        if period in _MONTHS:
            assert await _economics(economics, period) == {"juniors": fee}, period

    basis = await _payroll_basis(real_db, acad, clock=december)
    for occurrence_id, value in basis.items():
        period = occurrence_id.split("_")[1]
        assert value == _per_occurrence(NEW if period >= "2026-11" else OLD), occurrence_id


# ------------------------------------------------------------ start autopay


async def _start_autopay(
    db: Any, acad: str, enrollment_id: str, monkeypatch: pytest.MonkeyPatch
) -> int:
    """Start autopay; return the fee it read for the Stripe setup."""
    seen: list[int] = []
    real_execute = parent_billing.StartSubscriptionCheckout.execute

    async def _spy(self: Any, cmd: Any) -> Any:
        seen.append(cmd.amount_cents)
        return await real_execute(self, cmd)

    monkeypatch.setattr(parent_billing.StartSubscriptionCheckout, "execute", _spy)
    parent = compose_parent(
        db,
        outbox=object(),  # type: ignore[arg-type]
        idempotency_store=object(),  # type: ignore[arg-type]
        stripe=_AutopaySetupStripe(),  # type: ignore[arg-type]
        academy_id=acad,
        clock=_clock,
    )
    try:
        await parent.start_autopay_for_enrollment(  # type: ignore[operator]
            parent_id="parent-1",
            enrollment_id=enrollment_id,
            success_url="https://app.example.com/parent/autopay?status=success",
            cancel_url="https://app.example.com/parent/autopay?status=cancelled",
        )
    finally:
        monkeypatch.setattr(parent_billing.StartSubscriptionCheckout, "execute", real_execute)
    return seen[0]


async def _seed_connected_account(db: Any, acad: str) -> None:
    await db["academy_connected_accounts"].insert_one(
        {**_connected_account_doc(), "academy_id": acad}
    )


@pytest.mark.asyncio
async def test_start_autopay_reads_todays_fee_without_a_change(
    real_db, acad, allow_app_origin, monkeypatch
) -> None:
    await _seed_academy(real_db, acad)
    await _seed_connected_account(real_db, acad)

    assert await _start_autopay(real_db, acad, "e1", monkeypatch) == OLD
    # Legacy class (``monthly_price_cents`` only): read as before.
    assert await _start_autopay(real_db, acad, "e3", monkeypatch) == OLD
    assert await _start_autopay(real_db, acad, "e4", monkeypatch) == OLD


@pytest.mark.asyncio
async def test_start_autopay_reads_the_fee_of_its_first_charge_month(
    real_db, acad, allow_app_origin, monkeypatch
) -> None:
    await _seed_academy(real_db, acad)
    await _seed_connected_account(real_db, acad)
    kit = _Kit(real_db)

    await kit.schedule.execute(kit.cmd(acad, "2026-11"))
    # The first autopay charge is October's invoice: still the old fee.
    assert await _start_autopay(real_db, acad, "e1", monkeypatch) == OLD
    snapshot = await kit.quote_snapshot("juniors", datetime(2026, 9, 29, 12, tzinfo=UTC))
    assert snapshot.next_monthly_price_cents == OLD


@pytest.mark.asyncio
async def test_start_autopay_matches_checkout_when_the_change_starts_next_month(
    real_db, acad, allow_app_origin, monkeypatch
) -> None:
    await _seed_academy(real_db, acad)
    await _seed_connected_account(real_db, acad)
    kit = _Kit(real_db)

    await kit.schedule.execute(kit.cmd(acad, "2026-10"))
    assert await _start_autopay(real_db, acad, "e1", monkeypatch) == NEW
    assert await _start_autopay(real_db, acad, "e3", monkeypatch) == NEW
    # Checkout's "starting next month" price for the same class is the same.
    snapshot = await kit.quote_snapshot("juniors", datetime(2026, 9, 29, 12, tzinfo=UTC))
    assert snapshot.next_monthly_price_cents == NEW
    # Custom-price class: unaffected.
    assert await _start_autopay(real_db, acad, "e4", monkeypatch) == OLD


@pytest.mark.asyncio
async def test_an_unpriced_class_reads_zero_in_checkout_and_autopay_refuses_it(
    real_db, acad, allow_app_origin, monkeypatch
) -> None:
    await _seed_academy(real_db, acad)
    await _seed_connected_account(real_db, acad)
    await real_db["sessions"].update_one(
        {"academy_id": acad, "session_id": "squad"}, {"$unset": {"amount_cents": ""}}
    )
    kit = _Kit(real_db)

    # Checkout prices an unpriced class at $0 (and skips payment on it).
    assert await kit.quote("squad", datetime(2026, 10, 1, 12, tzinfo=UTC)) == 0
    snapshot = await kit.quote_snapshot("squad", datetime(2026, 9, 29, 12, tzinfo=UTC))
    assert snapshot.next_monthly_price_cents == 0

    # Autopay reads the same $0 and refuses (the route's 409), never $25.
    with pytest.raises(AutopayClassUnpriced, match="no monthly fee") as refused:
        await _start_autopay(real_db, acad, "e4", monkeypatch)
    # Its own code (not the generic 409), so the parent portal can say why.
    assert (refused.value.code, refused.value.status_code) == ("Billing.AutopayClassUnpriced", 409)
    enrollment = await real_db["enrollments"].find_one({"academy_id": acad, "enrollment_id": "e4"})
    assert "payment_mode" not in enrollment
