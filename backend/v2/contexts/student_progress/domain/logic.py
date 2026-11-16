"""Student progress domain logic — pure functions, no I/O."""

from __future__ import annotations

import math
from datetime import datetime, timedelta


def calculate_skill_pass(
    attempts: int,
    successes: int,
    threshold_pct: float,
) -> bool:
    """Return True if successes/attempts meets the pass threshold.

    Args:
        attempts: Total number of attempts recorded.
        successes: Number of successful attempts.
        threshold_pct: Pass threshold as a percentage (0-100).

    Returns:
        True if the skill is considered passed, False otherwise.
    """
    if attempts <= 0:
        return False
    return (successes / attempts) * 100.0 >= threshold_pct


def check_level_completion(
    required_skill_ids: list[str],
    passed_skill_ids: set[str],
) -> bool:
    """Return True if all required skills have been passed.

    Args:
        required_skill_ids: IDs of skills that are marked is_required=True.
        passed_skill_ids: IDs of skills whose status is PASSED.

    Returns:
        True if all required skills appear in the passed set.
    """
    if not required_skill_ids:
        return True
    return all(skill_id in passed_skill_ids for skill_id in required_skill_ids)


def format_cert_number(prefix: str | None, seq: int) -> str:
    """``BLNO-C-0042``: the academy's invoice prefix, ``C`` and the sequence.

    No prefix gives ``C-0042`` rather than borrowing another academy's.
    """
    return f"{prefix}-C-{seq:04d}" if prefix else f"C-{seq:04d}"


#: Pace estimates only look at recent passes, so a long break doesn't drag the
#: rate down forever and old bulk placements don't count.
PACE_WINDOW = timedelta(weeks=8)
PACE_MIN_PASSES = 3
#: Past half a year the estimate stops being useful to a parent.
PACE_MAX_WEEKS = 26


def estimate_weeks_to_next_level(
    pass_dates: list[datetime],
    skills_remaining: int,
    now: datetime,
) -> int | None:
    """Weeks until the remaining skills are done at the recent pass rate.

    Returns ``None`` instead of guessing when there is too little signal:
    fewer than ``PACE_MIN_PASSES`` passes in the window, or all of them on a
    single day (a placement backfill, not a pace).
    """
    if skills_remaining <= 0:
        return None
    recent = [d for d in pass_dates if now - PACE_WINDOW <= d <= now]
    if len(recent) < PACE_MIN_PASSES or len({d.date() for d in recent}) < 2:
        return None
    span_weeks = max((now - min(recent)) / timedelta(weeks=1), 1.0)
    weeks = math.ceil(skills_remaining / (len(recent) / span_weeks))
    return weeks if weeks <= PACE_MAX_WEEKS else None
