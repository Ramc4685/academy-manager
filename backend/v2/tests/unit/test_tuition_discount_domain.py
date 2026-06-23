from __future__ import annotations

import pytest

from backend.v2.contexts.billing.domain.tuition_discount import (
    TuitionDiscount,
    display_label,
    monthly_discount_cents,
)


def _policy(**kw) -> TuitionDiscount:
    base = dict(
        discount_id="d1",
        enrollment_id="e1",
        student_id="s1",
        category="scholarship",
        kind="waiver",
        effective_start="2026-06-01",
    )
    base.update(kw)
    return TuitionDiscount(**base)


@pytest.mark.parametrize(
    "kind,fields,price,expected",
    [
        ("waiver", {}, 10000, 10000),
        ("percent", {"percent_bps": 1000}, 10000, 1000),
        ("amount_off", {"amount_off_cents": 4000}, 10000, 4000),
        ("amount_off", {"amount_off_cents": 99999}, 10000, 10000),  # floor at price
        ("fixed_net", {"fixed_net_cents": 4000}, 10000, 6000),
        ("fixed_net", {"fixed_net_cents": 0}, 10000, 10000),  # waiver-equivalent
    ],
)
def test_monthly_discount_cents(kind, fields, price, expected) -> None:
    pol = _policy(kind=kind, **fields)
    assert monthly_discount_cents(pol, monthly_price_cents=price) == expected


def test_other_requires_label() -> None:
    with pytest.raises(ValueError):
        _policy(category="other", category_label=None)
    # with a label it is valid
    ok = _policy(category="other", category_label="Founding family rate")
    assert display_label(ok) == "Founding family rate"


def test_percent_requires_bps_in_range() -> None:
    with pytest.raises(ValueError):
        _policy(kind="percent", percent_bps=0)
    with pytest.raises(ValueError):
        _policy(kind="percent", percent_bps=10001)


def test_effective_end_must_not_precede_start() -> None:
    with pytest.raises(ValueError):
        _policy(effective_start="2026-06-01", effective_end="2026-05-01")


def test_display_label_for_known_categories() -> None:
    assert display_label(_policy(category="sibling")) == "Sibling discount"
    assert display_label(_policy(category="coach_child")) == "Coach child"
