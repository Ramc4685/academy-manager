"""Normalize datetimes read back from Mongo."""

from __future__ import annotations

from datetime import UTC, datetime


def ensure_utc(value: datetime) -> datetime:
    """Stamp UTC onto a naive datetime read back from Mongo.

    The Motor client is constructed without ``tz_aware=True``, so stored
    datetimes (which BSON always holds as UTC) come back *naive*. Serialized
    naive, they render as an offset-less ISO string that JS `new Date()` parses
    as browser-LOCAL wall clock — while rows synthesized in Python in the same
    response are aware and serialize with a trailing ``Z``. Two shapes in one
    array mean opposite things to the client, so normalize on read.

    Naive values also blow up any ``<=``/``-`` against ``datetime.now(UTC)``
    in a use case (issue #706, the parent absence-notice 500). The fix lives
    at the repository read boundary, never in individual use cases (#251
    precedent). Repositories whose ``_to_domain`` normalises with this helper:

    * ``enrollment/infrastructure/mongo_session_repo.py``
    * ``enrollment/infrastructure/mongo_occurrence_repo.py``
      (``start_at``, ``end_at``, ``cancelled_at``,
      ``next_upcoming_start_for_session``)
    * ``enrollment/infrastructure/mongo_makeup_request_repo.py``
      (``expires_at``, ``created_at``, ``decided_at``)
    * ``enrollment/infrastructure/mongo_trial_request_repo.py``
      (``created_at``, ``decided_at``)
    * ``enrollment/infrastructure/mongo_absence_notice_repo.py`` (``submitted_at``)
    * ``enrollment/infrastructure/mongo_enrollment_writer.py``
      (``cancelled_at``, ``pending_cancellation_*``, ``hold_*_at``;
      ``mongo_hold_repo.py`` delegates to it)

    Any new repository that reads a BSON datetime into a domain model must
    do the same.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
