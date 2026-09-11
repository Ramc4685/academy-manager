from __future__ import annotations

from pathlib import Path

_ADMIN = Path(__file__).parent.parent.parent / "composition" / "admin.py"
_ADD = (
    Path(__file__).parent.parent.parent
    / "contexts"
    / "enrollment"
    / "application"
    / "use_cases"
    / "admin_writes.py"
)


def test_admin_session_roster_query_lists_paused_and_held_enrollments() -> None:
    """A paused, held or reclaim_pending row must stay visible on the admin roster.

    Until 2026-09-03 the roster read was `status: "active"` while the
    add-to-roster guard blocked on `{"active", "paused"}` — a paused student
    was invisible on every admin surface yet still refused "Add to roster"
    ("already on this roster (paused)"). The roster panel's PAUSED chip and
    Resume button had never been reachable. The read and the guard must agree.

    #697 then introduced `held` and `reclaim_pending` without widening this
    read, which reopened the same dead end for the new statuses (#714): a held
    child vanished from the admin roster while the coach roster still listed
    them, and Return was unreachable because there was no row to act on. Both
    statuses are in `SEAT_HOLDING`, so a held row still occupies a seat and can
    make a class read as full with nobody visible to explain why.
    """
    source = _ADMIN.read_text()
    assert '"status": {"$in": ["active", "paused", "held", "reclaim_pending"]}' in source


def test_admin_session_seat_counts_stay_active_only() -> None:
    """Listing paused rows must not make them occupy a seat: pause releases
    the seat, so `enrolled_count` (capacity / open spots) counts active only."""
    source = _ADMIN.read_text()
    marker = "enrolled_count = await enrollments_r.collection.count_documents("
    assert marker in source
    window = source[source.index(marker) : source.index(marker) + 300]
    assert '"status": "active",' in window
    assert "paused" not in window


def test_roster_add_resumes_a_paused_row_instead_of_refusing_it() -> None:
    source = _ADD.read_text()
    assert 'existing.status == "paused" and self._resume is not None' in source
