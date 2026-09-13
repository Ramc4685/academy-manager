"""Issue #773: ONE derived person lifecycle, read by parent, coach and admin.

Before this, ``students.status`` was free text whose only writer was the admin
edit form: Drop, Stop-all, Pause, Hold and hold-expiry never touched it, so
every child ever registered read back as "active" on every surface. These
tests pin the derivation rules from
``docs/reviews/2026-09-12-ui-persona-lifecycle-audit.md`` §3 so the next
reader cannot invent a ninth state or reorder the precedence by accident.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import get_args

import pytest

from backend.v2.contexts.enrollment.domain.lifecycle import (
    PERSON_LIFECYCLES,
    LifecycleEnrollment,
    PersonLifecycle,
    derive_lifecycle,
)
from backend.v2.contexts.enrollment.domain.models import ENROLLMENT_STATUSES


def _at(day: int) -> datetime:
    return datetime(2026, 9, day, 12, 0, tzinfo=UTC)


def test_lifecycle_vocabulary_matches_the_owner_approved_eight_states() -> None:
    assert PERSON_LIFECYCLES == frozenset(get_args(PersonLifecycle))
    assert PERSON_LIFECYCLES == {
        "active",
        "at_risk",
        "paused",
        "on_hold",
        "pending_cancel",
        "left",
        "never_enrolled",
        "trial",
    }


def test_no_enrollment_rows_derives_never_enrolled() -> None:
    assert derive_lifecycle([]).state == "never_enrolled"


def test_no_enrollment_rows_with_a_trial_request_derives_trial() -> None:
    result = derive_lifecycle([], lead_since=date(2026, 9, 1), is_trial=True)
    assert result.state == "trial"
    assert result.as_of == date(2026, 9, 1)


def test_a_single_active_row_derives_active() -> None:
    rows = [LifecycleEnrollment(status="active", ordinal=_at(1))]
    assert derive_lifecycle(rows).state == "active"


def test_paused_enrollment_derives_paused_not_active() -> None:
    """The bug in one line: this student's ``students.status`` still reads
    "active" because nothing but the admin form ever writes it."""
    rows = [LifecycleEnrollment(status="paused", ordinal=_at(1), resume_on=date(2026, 10, 1))]
    result = derive_lifecycle(rows)
    assert result.state == "paused"
    assert result.as_of == date(2026, 10, 1)


def test_held_enrollment_derives_on_hold_with_the_return_date() -> None:
    rows = [LifecycleEnrollment(status="held", ordinal=_at(1), hold_return_on=date(2026, 10, 15))]
    result = derive_lifecycle(rows)
    assert result.state == "on_hold"
    assert result.as_of == date(2026, 10, 15)


def test_reclaim_pending_is_on_hold_not_an_unknown_state() -> None:
    """#697's in-flight reclaim state must map somewhere: the seat is neither
    kept nor released, and the family's last told story was the hold."""
    rows = [LifecycleEnrollment(status="reclaim_pending", ordinal=_at(1))]
    assert derive_lifecycle(rows).state == "on_hold"


def test_a_live_active_row_outranks_an_older_held_row() -> None:
    """§3 reads 'active: any SEAT_HOLDING enrollment' and 'on_hold: newest
    live row is held'. A child still attending one class is active even if a
    second class went on hold more recently."""
    rows = [
        LifecycleEnrollment(status="active", ordinal=_at(1)),
        LifecycleEnrollment(status="held", ordinal=_at(5), hold_return_on=date(2026, 10, 15)),
    ]
    assert derive_lifecycle(rows).state == "active"


def test_pending_cancellation_at_derives_pending_cancel_over_active() -> None:
    rows = [LifecycleEnrollment(status="active", ordinal=_at(1), pending_cancellation_at=_at(30))]
    result = derive_lifecycle(rows)
    assert result.state == "pending_cancel"
    assert result.as_of == date(2026, 9, 30)


def test_all_terminal_rows_derive_left_with_the_newest_end_date() -> None:
    rows = [
        LifecycleEnrollment(status="withdrawn", ordinal=_at(1), ended_at=_at(2)),
        LifecycleEnrollment(status="deleted", ordinal=_at(3), ended_at=_at(4)),
    ]
    result = derive_lifecycle(rows)
    assert result.state == "left"
    assert result.as_of == date(2026, 9, 4)


def test_legacy_and_canonical_terminal_spellings_both_derive_left() -> None:
    """#699 dual-read era: a row written yesterday and one written today must
    read the same."""
    for status in ("withdrawn", "dropped", "cancelled", "deleted"):
        rows = [LifecycleEnrollment(status=status, ordinal=_at(1))]
        assert derive_lifecycle(rows).state == "left", status


def test_active_with_stale_attendance_derives_at_risk() -> None:
    rows = [LifecycleEnrollment(status="active", ordinal=_at(1))]
    result = derive_lifecycle(rows, last_seen_at=_at(1), at_risk_cutoff=_at(5))
    assert result.state == "at_risk"
    assert result.as_of == date(2026, 9, 1)


def test_active_with_no_attendance_at_all_derives_at_risk() -> None:
    rows = [LifecycleEnrollment(status="active", ordinal=_at(1))]
    assert derive_lifecycle(rows, last_seen_at=None, at_risk_cutoff=_at(5)).state == "at_risk"


def test_active_that_attended_inside_the_window_stays_active() -> None:
    rows = [LifecycleEnrollment(status="active", ordinal=_at(1))]
    result = derive_lifecycle(rows, last_seen_at=_at(6), at_risk_cutoff=_at(5))
    assert result.state == "active"


def test_without_a_cutoff_at_risk_is_never_claimed() -> None:
    """A class with fewer than three past occurrences cannot tell us anything;
    guessing "at risk" there would cry wolf on every brand-new session."""
    rows = [LifecycleEnrollment(status="active", ordinal=_at(1))]
    assert derive_lifecycle(rows, last_seen_at=None, at_risk_cutoff=None).state == "active"


def test_paused_beats_at_risk_because_nobody_expected_them_to_attend() -> None:
    rows = [LifecycleEnrollment(status="paused", ordinal=_at(1))]
    assert derive_lifecycle(rows, last_seen_at=None, at_risk_cutoff=_at(5)).state == "paused"


def test_terminal_rows_do_not_suppress_a_live_one() -> None:
    rows = [
        LifecycleEnrollment(status="dropped", ordinal=_at(1), ended_at=_at(1)),
        LifecycleEnrollment(status="active", ordinal=_at(5)),
    ]
    assert derive_lifecycle(rows).state == "active"


@pytest.mark.parametrize("status", sorted(ENROLLMENT_STATUSES))
def test_every_enrollment_status_derives_a_known_lifecycle(status: str) -> None:
    """A status added to the vocabulary without being classified here would
    otherwise silently inherit whichever branch fell through last."""
    result = derive_lifecycle([LifecycleEnrollment(status=status, ordinal=_at(1))])
    assert result.state in PERSON_LIFECYCLES
