"""Issue #642: ``paused`` (and every other enrollment status) gets ONE meaning.

The incident family this pins: ``paused`` meant "keeps the seat" to one
reader, "released the seat" to another, "still bill them" to a third. Nothing
structural stopped a new reader from inventing a fourth meaning, because every
reader hand-rolled its own ``{"active", "paused", ...}`` literal set at the
point of use. Thirteen readers excluded paused, six included it, and no two of
them referenced a shared definition — so "which readers agree?" could only be
answered by grepping, and a reader added tomorrow agreed with nobody by
default.

Two invariants are enforced here.

**1. The vocabulary is closed and the predicate sets partition it.** Every
predicate frozenset in ``domain/models.py`` is checked against
``ENROLLMENT_STATUSES``: no predicate may name a status that does not exist
(the typo that silently matches nothing), and the seat and lifecycle
partitions must cover the vocabulary exactly. A status added to
``EnrollmentStatus`` without being classified fails here rather than falling
into whichever readers happen to use ``$nin``.

**2. No module inside ``contexts/enrollment/`` outside ``domain/`` may spell
its own status set.** An AST scan flags every set/list/tuple literal of two or
more string constants whose values are ALL enrollment statuses — the exact
shape of ``_BLOCKING_STATUSES``, ``_WITHDRAWABLE``, ``{"$in": ["active",
"paused"]}`` and friends. Mixed-vocabulary literals are untouched on purpose:
``{"scheduled", "active", "open"}`` is the *session* status vocabulary and
``("withdrawn", "dropped", "hold_expired", ...)`` is the *event type*
vocabulary; neither is an enrollment-status set, and flagging them would train
the next reader to suppress this test rather than use the domain.

Single literals (``status == "paused"``, ``{"$set": {"status": "held"}}``) are
deliberately NOT flagged: a write path naming the one status it transitions to
is the point, not a duplicated policy. What this bans is a *set*, because a
set is a policy — "these statuses are the ones that count for X" — and that
policy belongs in exactly one file.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import get_args

from backend.v2.contexts.enrollment.domain.models import (
    ACTIVE_OR_PAUSED,
    ATTENDANCE_VISIBLE,
    BILLABLE,
    DELETED_SPELLINGS,
    DROPPED_SPELLINGS,
    ENROLLMENT_STATUSES,
    LIVE,
    NON_TERMINAL,
    RECLAIM_PENDING,
    ROSTER_VISIBLE,
    SEAT_HOLDING,
    SEATLESS,
    STORED_ENROLLMENT_STATUSES,
    TERMINAL,
    TRANSIENT_DELETING_STATUS,
    EnrollmentStatus,
)

V2_ROOT = Path(__file__).resolve().parents[2]
ENROLLMENT_ROOT = V2_ROOT / "contexts" / "enrollment"
DOMAIN_ROOT = ENROLLMENT_ROOT / "domain"

#: Every predicate the domain publishes, by name, so a new one cannot be
#: added without being checked against the closed vocabulary below.
_PREDICATES = {
    "SEAT_HOLDING": SEAT_HOLDING,
    "SEATLESS": SEATLESS,
    "LIVE": LIVE,
    "NON_TERMINAL": NON_TERMINAL,
    "TERMINAL": TERMINAL,
    "BILLABLE": BILLABLE,
    "ROSTER_VISIBLE": ROSTER_VISIBLE,
    "ATTENDANCE_VISIBLE": ATTENDANCE_VISIBLE,
    "ACTIVE_OR_PAUSED": ACTIVE_OR_PAUSED,
    "DROPPED_SPELLINGS": DROPPED_SPELLINGS,
    "DELETED_SPELLINGS": DELETED_SPELLINGS,
}


def test_the_runtime_vocabulary_matches_the_literal() -> None:
    """``EnrollmentStatus`` is the type-checker's copy, ``ENROLLMENT_STATUSES``
    the runtime one. A Literal cannot be handed to a ``$in`` filter or to the
    Mongo validator enum, so both have to exist — and drift between them is
    the whole defect this issue is about, one level up."""
    assert set(get_args(EnrollmentStatus)) == ENROLLMENT_STATUSES


def test_every_predicate_only_names_statuses_that_exist() -> None:
    for name, members in _PREDICATES.items():
        unknown = members - ENROLLMENT_STATUSES
        assert not unknown, f"{name} names non-existent status(es): {sorted(unknown)}"


def test_seat_partition_covers_the_whole_vocabulary() -> None:
    """A row either holds a seat, has given it back, or is mid-reclaim."""
    assert SEAT_HOLDING.isdisjoint(SEATLESS)
    assert RECLAIM_PENDING not in SEAT_HOLDING
    assert RECLAIM_PENDING not in SEATLESS
    assert SEAT_HOLDING | SEATLESS | {RECLAIM_PENDING} == ENROLLMENT_STATUSES


def test_lifecycle_partition_covers_the_whole_vocabulary() -> None:
    """A row has either ended (TERMINAL) or not (NON_TERMINAL)."""
    assert NON_TERMINAL.isdisjoint(TERMINAL)
    assert NON_TERMINAL | TERMINAL == ENROLLMENT_STATUSES
    assert NON_TERMINAL == LIVE | {RECLAIM_PENDING}


def test_paused_has_exactly_one_meaning() -> None:
    """The #642 defect, stated as an assertion.

    ``paused`` released its seat, has not ended, is not billed, and is off
    the roster and the attendance sheet. Every reader that disagreed with one
    of these four facts was a bug.
    """
    assert "paused" in SEATLESS
    assert "paused" not in SEAT_HOLDING
    assert "paused" in LIVE
    assert "paused" not in TERMINAL
    assert "paused" not in BILLABLE
    assert "paused" not in ROSTER_VISIBLE
    assert "paused" not in ATTENDANCE_VISIBLE


def test_terminal_rows_carry_both_spellings_and_never_hold_a_seat() -> None:
    assert TERMINAL <= SEATLESS
    assert DROPPED_SPELLINGS <= TERMINAL
    assert DELETED_SPELLINGS <= TERMINAL
    assert DROPPED_SPELLINGS | DELETED_SPELLINGS == TERMINAL


def test_billable_and_visible_rows_are_live() -> None:
    assert BILLABLE <= LIVE
    assert ROSTER_VISIBLE <= LIVE
    assert ATTENDANCE_VISIBLE <= LIVE


def test_the_transient_delete_sentinel_is_storable_but_not_a_real_status() -> None:
    """``delete_if_status`` CAS-stamps ``__deleting__`` before removing the
    row, so the Mongo validator enum must accept it even though no reader may
    ever treat it as a status."""
    assert TRANSIENT_DELETING_STATUS not in ENROLLMENT_STATUSES
    assert STORED_ENROLLMENT_STATUSES == ENROLLMENT_STATUSES | {TRANSIENT_DELETING_STATUS}


def _scanned_files() -> list[Path]:
    return sorted(
        path
        for path in ENROLLMENT_ROOT.rglob("*.py")
        if DOMAIN_ROOT not in path.parents and "tests" not in path.relative_to(V2_ROOT).parts
    )


def _status_set_literals(tree: ast.AST) -> list[tuple[int, list[str]]]:
    """Collection literals that are entirely enrollment statuses, 2+ members."""
    found: list[tuple[int, list[str]]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Set | ast.List | ast.Tuple):
            continue
        elements = node.elts
        if len(elements) < 2:
            continue
        if not all(isinstance(e, ast.Constant) and isinstance(e.value, str) for e in elements):
            continue
        values = [e.value for e in elements]  # type: ignore[attr-defined]
        if all(value in ENROLLMENT_STATUSES for value in values):
            found.append((node.lineno, values))
    return found


def test_no_module_outside_the_domain_spells_its_own_status_set() -> None:
    offenders: list[str] = []
    for path in _scanned_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for lineno, values in _status_set_literals(tree):
            offenders.append(f"{path.relative_to(V2_ROOT)}:{lineno} {values}")

    assert not offenders, (
        "Enrollment status sets must come from contexts/enrollment/domain/models.py "
        "(SEAT_HOLDING, LIVE, TERMINAL, ...), not be re-spelled at the point of use "
        "— that is how 'paused' acquired three different meanings (#642).\n  "
        + "\n  ".join(offenders)
    )
