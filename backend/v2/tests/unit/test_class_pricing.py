"""Class-to-plan link rules (Settings overhaul PR 11b).

A link is a label, never an amount. These pin the rule that a link can never
disagree with what the class is charged.
"""

from __future__ import annotations

import pytest

from backend.v2.contexts.billing.domain.class_pricing import (
    DEFAULT_PLAN_TYPE,
    PlanPrice,
    effective_plan_link,
    ensure_link_allowed,
    initial_plan_link,
    matching_plan_ids,
)
from backend.v2.contexts.billing.domain.errors import PlanPriceMismatch

GROUP = PlanPrice(plan_id="group", price_cents=12_000)
PRIVATE = PlanPrice(plan_id="private", price_cents=24_000)
GROUP_TWIN = PlanPrice(plan_id="group-twin", price_cents=12_000)
ARCHIVED = PlanPrice(plan_id="old", price_cents=18_000, is_active=False)


def test_every_plan_is_monthly_by_default() -> None:
    assert DEFAULT_PLAN_TYPE == "monthly"


def test_exactly_one_matching_plan_links() -> None:
    assert initial_plan_link(12_000, [GROUP, PRIVATE]) == "group"


def test_no_matching_plan_stays_custom() -> None:
    assert initial_plan_link(18_000, [GROUP, PRIVATE]) is None


def test_two_matching_plans_stay_custom() -> None:
    assert matching_plan_ids(12_000, [GROUP, GROUP_TWIN]) == ["group", "group-twin"]
    assert initial_plan_link(12_000, [GROUP, GROUP_TWIN, PRIVATE]) is None


def test_archived_plans_never_match() -> None:
    assert matching_plan_ids(18_000, [ARCHIVED]) == []
    assert initial_plan_link(18_000, [ARCHIVED]) is None


def test_link_to_a_plan_at_another_price_is_refused() -> None:
    with pytest.raises(PlanPriceMismatch):
        ensure_link_allowed(18_000, GROUP)


def test_link_to_an_archived_plan_is_refused() -> None:
    with pytest.raises(PlanPriceMismatch):
        ensure_link_allowed(18_000, ARCHIVED)


def test_link_at_the_class_fee_is_allowed() -> None:
    ensure_link_allowed(12_000, GROUP)


def test_stored_link_shows_only_while_the_price_still_matches() -> None:
    assert effective_plan_link("group", 12_000, [GROUP]) == "group"
    # The class fee (or the plan price) changed since the link was made: the
    # page must not show a plan price the family is not charged.
    assert effective_plan_link("group", 13_000, [GROUP]) is None
    assert effective_plan_link("gone", 12_000, [GROUP]) is None
    assert effective_plan_link(None, 12_000, [GROUP]) is None
    assert effective_plan_link("old", 18_000, [ARCHIVED]) is None
