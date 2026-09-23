"""People CRM spec §6: the family stage is the most urgent child state.

``pending_cancel > active > at_risk > on_hold > paused > trial > never_enrolled > left``
"""

from __future__ import annotations

from itertools import combinations

import pytest

from backend.v2.contexts.crm.domain.family_stage import (
    FAMILY_STAGE_PRECEDENCE,
    FAMILY_STAGES,
    SCOPE_STAGES,
    roll_up_family_stage,
)
from backend.v2.contexts.enrollment.domain.lifecycle import PERSON_LIFECYCLES

SPEC_ORDER = (
    "pending_cancel",
    "active",
    "at_risk",
    "on_hold",
    "paused",
    "trial",
    "never_enrolled",
    "left",
)


def test_precedence_is_exactly_the_spec_order() -> None:
    assert FAMILY_STAGE_PRECEDENCE == SPEC_ORDER


def test_family_vocabulary_is_the_person_lifecycle_vocabulary() -> None:
    """The CRM may not import enrollment, so it spells the states once more;
    a ninth person state must fail here, not rank silently last."""
    assert FAMILY_STAGES == PERSON_LIFECYCLES


@pytest.mark.parametrize(("higher", "lower"), list(combinations(SPEC_ORDER, 2)))
def test_every_pair_the_more_urgent_state_wins(higher: str, lower: str) -> None:
    assert roll_up_family_stage([lower, higher]) == higher
    assert roll_up_family_stage([higher, lower]) == higher
    assert roll_up_family_stage([lower, lower, higher, lower]) == higher


@pytest.mark.parametrize("state", SPEC_ORDER)
def test_one_child_is_its_own_stage(state: str) -> None:
    assert roll_up_family_stage([state]) == state


def test_no_children_is_a_lead() -> None:
    assert roll_up_family_stage([]) == "never_enrolled"


def test_unknown_states_are_ignored_not_raised() -> None:
    assert roll_up_family_stage(["mystery"]) == "never_enrolled"
    assert roll_up_family_stage(["mystery", "left"]) == "left"


def test_split_family_is_active() -> None:
    """Spec §6 edge case: one child active and one left makes the family Active."""
    assert roll_up_family_stage(["left", "active"]) == "active"


def test_scope_tiles_follow_spec_3_2() -> None:
    assert SCOPE_STAGES == {
        "active": {"active"},
        "leaving": {"at_risk", "on_hold", "paused", "pending_cancel"},
        "left": {"left"},
    }
    on_a_tile = set().union(*SCOPE_STAGES.values())
    assert FAMILY_STAGES - on_a_tile == {"trial", "never_enrolled"}
