"""Issue #773: the ONE derived person lifecycle.

``students.status`` was free text. Its only writer was the admin edit form —
Drop, Stop-all, Pause, Hold and hold-expiry never touched it — so the field
froze at whatever an admin last typed and every child ever registered read
back as "active" on /admin/students, on the parent portal chip, and nowhere
at all for coaches. The fix is not a better writer: a person's state is a
*function* of their enrollments (plus holds, pending cancels and attendance),
so it is derived here, once, and every persona read calls this.

The eight states and their precedence are the owner-approved rules in
``docs/reviews/2026-09-12-ui-persona-lifecycle-audit.md`` §3. Two things about
the ordering are worth stating, because the §3 table lists rules rather than
an order and a reader could compose them differently:

* **A live ``active`` row wins over a held/paused one (spec R1).** §3 says
  "active: any SEAT_HOLDING enrollment" *and* "paused / on_hold: newest live
  row is paused / held". A child still attending Tuesday class is active even
  if Thursday's class went on hold this morning; reading only the newest row
  would tell that family their child is on hold.
* **``pending_cancel`` outranks everything live.** It is the only live state
  that carries a promised end date, and "ends Oct 31" is the fact the family
  and the coach need; "active" is true but useless next to it.

This module is status-set-free by construction: it composes ``TERMINAL``,
``SEAT_HOLDING`` and friends from ``models.py`` rather than respelling them
(``tests/structural/test_enrollment_status_predicates.py`` bans hand-rolled
status sets outside ``domain/``, and re-spelling them here is exactly the
duplication that gave "paused" three meanings in #642).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from typing import Final, Literal, get_args

from pydantic import BaseModel

from backend.v2.contexts.enrollment.domain.models import (
    RECLAIM_PENDING,
    SEAT_HOLDING,
    canonical_status,
)

#: The owner-approved person states. Deliberately NOT the enrollment
#: vocabulary: an enrollment is a contract for one class, a person is a
#: human, and the two only look alike when a family has exactly one class.
PersonLifecycle = Literal[
    "active",
    "at_risk",
    "paused",
    "on_hold",
    "pending_cancel",
    "left",
    "never_enrolled",
    "trial",
]

PERSON_LIFECYCLES: Final[frozenset[str]] = frozenset(get_args(PersonLifecycle))

#: The default /admin/students filter: everyone who is still somebody's
#: problem today. "left" and the lead states are reachable but not shown by
#: default, which is what "the Paused tile always counted nobody" was really
#: asking for.
OPERATIONAL_LIFECYCLES: Final[tuple[str, ...]] = ("active", "on_hold", "paused", "at_risk")

#: Statuses whose row is still attending, or still holding a seat it intends
#: to use. ``active`` is the only one that implies attendance today.
_ATTENDING: Final[frozenset[str]] = SEAT_HOLDING - {"held"}


class LifecycleEnrollment(BaseModel):
    """The only enrollment facts the derivation reads.

    A deliberately narrow projection rather than the ``Enrollment`` aggregate:
    the admin directory reads raw Mongo documents, the parent composition
    reads another shape and the coach roster a third, and forcing all three
    through the full aggregate would make this function unusable from at
    least two of them.
    """

    model_config = {"frozen": True}

    status: str
    #: #675: the instant a parent's end-of-period cancel takes effect.
    pending_cancellation_at: datetime | None = None
    #: #697: the promised return date of a hold.
    hold_return_on: date | None = None
    #: The scheduled end of a pause, when one was recorded.
    resume_on: date | None = None
    #: When a terminal row ended (withdrawal / cancellation date).
    ended_at: datetime | None = None
    #: Recency key — ``created_at`` or ``updated_at``. Rows without one sort
    #: oldest, so a document missing the field never wins "newest live row"
    #: over one that has it.
    ordinal: datetime | None = None


class PersonLifecycleState(BaseModel):
    """A derived state and the one date the UI shows next to it."""

    model_config = {"frozen": True}

    state: PersonLifecycle
    #: Resume date, hold return date, end date, left-on date or lead date —
    #: whichever the state means. None when the state has no date to show.
    as_of: date | None = None


def _as_date(value: datetime | date | None) -> date | None:
    if value is None:
        return None
    return value.date() if isinstance(value, datetime) else value


def _comparable(value: datetime) -> datetime:
    """Strip tzinfo so a naive legacy Mongo datetime compares with an aware one.

    Mixing the two raises ``TypeError`` at runtime — the #706 failure mode —
    and a lifecycle chip is not worth a 500.
    """
    return value.replace(tzinfo=None)


def derive_lifecycle(
    enrollments: Sequence[LifecycleEnrollment],
    *,
    last_seen_at: datetime | None = None,
    at_risk_cutoff: datetime | None = None,
    lead_since: date | None = None,
    is_trial: bool = False,
) -> PersonLifecycleState:
    """Derive one person's lifecycle from their enrollment rows.

    The branch order below IS the precedence (spec rules R1-R6):

    * **R1** an ``active`` row beats every other row status — pending_cancel
      when one carries an end date, at_risk when attendance has stopped,
      otherwise active;
    * **R2/R3** else a ``held`` row, or the transient ``reclaim_pending`` a
      reclaim leaves behind, reads as on_hold;
    * **R4** else ``paused``;
    * **R5** else every row is terminal — left;
    * **R6** else there are no rows at all — a lead state.

    ``at_risk_cutoff`` is the start of the window covering the last three
    scheduled occurrences for this person's classes; ``last_seen_at`` is their
    newest attendance mark. at_risk is claimed only when a cutoff exists — a
    class with fewer than three past occurrences cannot tell us anything, and
    guessing would flag every student in a brand-new session.
    """
    rows = list(enrollments)
    if not rows:
        # R6, minimal: this step derives from enrollments. Waitlist,
        # application and trial-request states are step 6 of the batch-3b
        # track and land on this same enum.
        if is_trial:
            return PersonLifecycleState(state="trial", as_of=lead_since)
        return PersonLifecycleState(state="never_enrolled", as_of=lead_since)

    by_status: dict[str, list[LifecycleEnrollment]] = {}
    for row in rows:
        by_status.setdefault(canonical_status(row.status), []).append(row)

    # R1: attending beats everything. A child still going to Tuesday class is
    # active even if Thursday's class went on hold this morning.
    attending = [row for status in _ATTENDING for row in by_status.get(status, ())]
    if attending:
        ends = [
            row.pending_cancellation_at
            for row in attending
            if row.pending_cancellation_at is not None
        ]
        if ends:
            # The SOONEST end date, not the newest row's: "ends Oct 31" is the
            # fact the family and the coach have to act on first.
            return PersonLifecycleState(state="pending_cancel", as_of=_as_date(min(ends)))
        stale = at_risk_cutoff is not None and (
            last_seen_at is None or _comparable(last_seen_at) < _comparable(at_risk_cutoff)
        )
        if stale:
            return PersonLifecycleState(state="at_risk", as_of=_as_date(last_seen_at))
        return PersonLifecycleState(state="active", as_of=None)

    # R2/R3: a kept seat that is not being used. ``reclaim_pending`` is the
    # in-flight state of a seat reclaim (#697) — neither kept nor released
    # until finalize() runs, and the last thing the family was told is the
    # hold. The spec's separate ``on_hold_reclaiming`` is a later step's
    # refinement of this same chip.
    held = by_status.get("held", []) + by_status.get(RECLAIM_PENDING, [])
    if held:
        returns = [row.hold_return_on for row in held if row.hold_return_on is not None]
        return PersonLifecycleState(state="on_hold", as_of=min(returns) if returns else None)

    # R4: a pause released the seat; the family has not left (#641).
    paused = by_status.get("paused", [])
    if paused:
        resumes = [row.resume_on for row in paused if row.resume_on is not None]
        return PersonLifecycleState(state="paused", as_of=min(resumes) if resumes else None)

    # R5: every row is terminal.
    ended = [row.ended_at for row in rows if row.ended_at is not None]
    return PersonLifecycleState(state="left", as_of=_as_date(max(ended)) if ended else None)
