"""Composition for Came / Didn't come on a trial (People CRM L3a).

Wiring only: ``MarkTrialOutcome`` (``contexts/enrollment``) over the trial
request repository, the occurrence repository and the coach assignment
lookup. The assignment lookup is built WITHOUT the supervisor shortcut: the
coach route passes ``coach_id=None`` for a coach supervisor (academy admin or
owner), so a plain coach is checked against the session's own coach and
assistants only.

Built on first use and kept on ``app.state.trial_outcomes`` by the two route
modules (``interfaces/admin/trial_outcome_routes.py`` and
``interfaces/coach/trial_outcome_routes.py``), so ``main.py`` and the
line-capped ``composition/admin.py`` stay untouched.
"""

from __future__ import annotations

from typing import Any

from backend.v2.composition.coach import CoachAssignedSessionLookup
from backend.v2.contexts.enrollment.application.use_cases.trial_outcomes import MarkTrialOutcome
from backend.v2.contexts.enrollment.infrastructure.mongo_occurrence_repo import (
    MongoSessionOccurrenceRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_session_repo import (
    MongoSessionRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_trial_request_repo import (
    MongoTrialRequestRepository,
)


def compose_mark_trial_outcome(db: Any) -> MarkTrialOutcome:
    return MarkTrialOutcome(
        trials=MongoTrialRequestRepository(db),
        occurrences=MongoSessionOccurrenceRepository(db),
        assignments=CoachAssignedSessionLookup(MongoSessionRepository(db)),
    )


def mark_trial_outcome_from_state(state: Any) -> MarkTrialOutcome | None:
    """The app's ``MarkTrialOutcome``, composed once; ``None`` without a db."""
    service = getattr(state, "trial_outcomes", None)
    if service is not None:
        return service  # type: ignore[no-any-return]
    db = getattr(state, "db", None)
    if db is None:
        return None
    service = compose_mark_trial_outcome(db)
    state.trial_outcomes = service
    return service
