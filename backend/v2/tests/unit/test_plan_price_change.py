"""Pure rules for scheduled plan price changes (Settings overhaul PR 26)."""

from __future__ import annotations

import pytest

from backend.v2.contexts.billing.domain.errors import PriceChangeMonthNotAllowed
from backend.v2.contexts.billing.domain.plan_price_change import (
    PlanPriceChange,
    class_fee_for_period,
    earliest_effective_period,
    ensure_effective_period_allowed,
    next_period,
    pending_change_for_class,
    stored_class_fee_cents,
)


def _change(**kw) -> PlanPriceChange:
    base = dict(
        change_id="c1",
        plan_id="group",
        old_cents=10_000,
        new_cents=11_000,
        effective_period="2026-11",
        session_ids=("s1",),
    )
    base.update(kw)
    return PlanPriceChange(**base)  # type: ignore[arg-type]


def _fee(stored: int, period: str, changes, session_id: str = "s1") -> int:
    return class_fee_for_period(
        session_id=session_id, stored_fee_cents=stored, period=period, changes=changes
    )


def test_no_change_is_the_stored_fee() -> None:
    assert _fee(12_345, "2026-11", []) == 12_345


def test_scheduled_change_applies_from_its_month_only() -> None:
    changes = [_change()]
    assert _fee(10_000, "2026-10", changes) == 10_000
    assert _fee(10_000, "2026-11", changes) == 11_000
    assert _fee(10_000, "2027-03", changes) == 11_000


def test_class_outside_the_snapshot_is_not_affected() -> None:
    assert _fee(10_000, "2026-12", [_change()], session_id="s2") == 10_000


def test_cancelled_change_does_nothing() -> None:
    assert _fee(10_000, "2026-12", [_change(status="cancelled")]) == 10_000


def test_hand_edited_fee_wins() -> None:
    assert _fee(15_000, "2026-12", [_change()]) == 15_000


def test_flipped_class_reads_the_old_price_before_the_month() -> None:
    flipped = [_change(status="applied", flipped_session_ids=("s1",))]
    assert _fee(11_000, "2026-10", flipped) == 10_000
    assert _fee(11_000, "2026-11", flipped) == 11_000


def test_flip_in_progress_gives_the_same_answer() -> None:
    mid = [_change(flipped_session_ids=("s1",))]
    assert _fee(10_000, "2026-11", mid) == 11_000  # recorded, fee not moved yet
    assert _fee(11_000, "2026-11", mid) == 11_000  # moved
    assert _fee(11_000, "2026-10", mid) == 10_000


def test_two_changes_in_a_row_chain_back_to_the_first_price() -> None:
    changes = [
        _change(status="applied", flipped_session_ids=("s1",)),
        _change(
            change_id="c2",
            old_cents=11_000,
            new_cents=12_000,
            effective_period="2027-01",
            status="applied",
            flipped_session_ids=("s1",),
        ),
    ]
    assert _fee(12_000, "2026-10", changes) == 10_000
    assert _fee(12_000, "2026-12", changes) == 11_000
    assert _fee(12_000, "2027-01", changes) == 12_000


def test_earliest_is_never_the_current_month_and_skips_invoiced_months() -> None:
    assert earliest_effective_period(current_period="2026-09", latest_invoiced_period=None) == (
        "2026-10"
    )
    assert (
        earliest_effective_period(current_period="2026-09", latest_invoiced_period="2026-09")
        == "2026-10"
    )
    assert (
        earliest_effective_period(current_period="2026-09", latest_invoiced_period="2026-10")
        == "2026-11"
    )
    assert next_period("2026-12") == "2027-01"


@pytest.mark.parametrize("period", ["2026-09", "2026-13", "Nov", ""])
def test_bad_months_are_refused(period: str) -> None:
    with pytest.raises(PriceChangeMonthNotAllowed):
        ensure_effective_period_allowed(period, earliest="2026-10")


def test_pending_change_for_the_class_editor() -> None:
    change = _change()
    assert pending_change_for_class(session_id="s1", stored_fee_cents=10_000, changes=[change])
    assert (
        pending_change_for_class(session_id="s1", stored_fee_cents=15_000, changes=[change]) is None
    )


def test_stored_fee_matches_the_monthly_run_read() -> None:
    assert stored_class_fee_cents({"amount_cents": 1, "monthly_price_cents": 2}) == 1
    assert stored_class_fee_cents({"monthly_price_cents": 2}) == 2
    assert stored_class_fee_cents({"monthly_price": 120}) == 12_000
    assert stored_class_fee_cents({}) == 0
