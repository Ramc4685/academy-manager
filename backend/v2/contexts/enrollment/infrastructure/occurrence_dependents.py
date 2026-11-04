"""Which stored rows pin a single ``occurrence_id`` (issue #783).

``maintain_session_occurrences`` re-derives every ``occurrence_id`` from the
session's weekday/time signature, so changing ``days_of_week`` re-mints the
whole set and hard-deletes the rows that are no longer candidates. Deleting
an occurrence that something still references leaves a dangling foreign key
with no cleanup and no notification — a family's approved make-up, submitted
absence notice or assigned trial silently stops resolving.

The map lives here, once, rather than being re-spelled at each read: the
callers that need it are the occurrence cascade and any future reconcile,
and both need the SAME answer to "is anything still pointing at this?".

``makeup_requests`` and ``trial_requests`` deliberately list their own field
names — they do not call it ``occurrence_id``, which is exactly why a check
written against that one spelling missed them.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, Final

#: ``(collection, fields that may hold an occurrence_id)``.
OCCURRENCE_DEPENDENT_COLLECTIONS: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    ("attendance", ("occurrence_id",)),
    ("coach_attendance", ("occurrence_id",)),
    ("payout_period_lines", ("occurrence_id",)),
    ("occurrence_roster_entries", ("occurrence_id",)),
    ("absence_notices", ("occurrence_id",)),
    ("session_feedback", ("occurrence_id",)),
    (
        "makeup_requests",
        (
            "missed_occurrence_id",
            "requested_target_occurrence_id",
            "approved_target_occurrence_id",
        ),
    ),
    ("trial_requests", ("assigned_occurrence_id",)),
)


def occurrence_dependency_filters(
    *, academy_id: str, occurrence_id: str
) -> Iterator[tuple[str, dict[str, Any]]]:
    """Yield ``(collection, tenant-scoped filter)`` for every dependent row."""

    for collection, fields in OCCURRENCE_DEPENDENT_COLLECTIONS:
        if len(fields) == 1:
            yield collection, {"academy_id": academy_id, fields[0]: occurrence_id}
        else:
            yield (
                collection,
                {
                    "academy_id": academy_id,
                    "$or": [{field: occurrence_id} for field in fields],
                },
            )
