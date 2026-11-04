"""The family stage: one roll-up of the children's lifecycle states.

People CRM spec §6 ("Per family"): the stage is the highest-ranked child
state, in exactly this order::

    pending_cancel > active > at_risk > on_hold > paused > trial > never_enrolled > left

Each child's state is ``derive_lifecycle()`` (the enrollment context's one
derivation, the same one ``/admin/students`` shows). This module does not
re-derive a child; it only ranks. The vocabulary is the enrollment context's
``PersonLifecycle`` spelled once more here because contexts may not import
each other (``tests/structural/test_layering.py``); ``test_crm_family_stage``
pins the two sets equal, so a ninth person state fails the build instead of
silently ranking last.

A family with no children (a parent membership with nothing enrolled yet)
is ``never_enrolled``: shown as "Lead" (spec §6).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Final, Literal, get_args

FamilyStage = Literal[
    "pending_cancel",
    "active",
    "at_risk",
    "on_hold",
    "paused",
    "trial",
    "never_enrolled",
    "left",
]

#: Most urgent first. ``pending_cancel`` leads because it carries a promised
#: end date the owner must act on; a split family (one child active, one
#: left) is active; ``left`` only when nothing else is true.
FAMILY_STAGE_PRECEDENCE: Final[tuple[FamilyStage, ...]] = get_args(FamilyStage)

FAMILY_STAGES: Final[frozenset[str]] = frozenset(FAMILY_STAGE_PRECEDENCE)

_RANK: Final[dict[str, int]] = {stage: i for i, stage in enumerate(FAMILY_STAGE_PRECEDENCE)}

#: The Families scope tiles (spec §3.2). Lead-only stages (``trial``,
#: ``never_enrolled``) are on no tile; they live in Pipeline.
FamilyScope = Literal["active", "leaving", "left"]
SCOPE_STAGES: Final[Mapping[str, frozenset[str]]] = {
    "active": frozenset({"active"}),
    "leaving": frozenset({"at_risk", "on_hold", "paused", "pending_cancel"}),
    "left": frozenset({"left"}),
}
FAMILY_SCOPES: Final[frozenset[str]] = frozenset(get_args(FamilyScope))


def stage_rank(stage: str) -> int:
    """Position in :data:`FAMILY_STAGE_PRECEDENCE`; unknown states rank last."""
    return _RANK.get(stage, len(_RANK))


def roll_up_family_stage(child_states: Iterable[str]) -> FamilyStage:
    """The family's stage: its most urgent child state.

    Unknown strings are ignored rather than raised on (a chip is not worth a
    500); the vocabulary test keeps them from existing.
    """
    known = [state for state in child_states if state in _RANK]
    if not known:
        return "never_enrolled"
    return FAMILY_STAGE_PRECEDENCE[min(_RANK[state] for state in known)]
