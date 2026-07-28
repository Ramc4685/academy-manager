"""Field conventions for ``session_occurrences`` documents.

Shared by the billing reporting read models and the coaching payout read
models, which both have to answer the same two questions about a raw
occurrence document: which session does it belong to, and is it done?
Keeping the answers in one place stops the two readers from drifting.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def optional_str(value: object | None) -> str | None:
    return None if value is None else str(value)


def occurrence_session_id(doc: dict[str, Any]) -> str:
    """Session the occurrence belongs to — enrollments reference the
    template session, so prefer ``template_session_id`` when present."""
    return str(doc.get("template_session_id") or doc.get("session_id") or "")


def effective_occurrence_status(doc: dict[str, Any]) -> str:
    """A scheduled occurrence whose end time has passed counts as completed.

    Nothing in the app flips ``session_occurrences.status`` to "completed",
    so payout eligibility derives completion from the clock instead.
    Cancelled occurrences stay cancelled.
    """
    status = str(doc.get("status", "scheduled"))
    if status != "scheduled":
        return status
    end_at = doc["end_at"]
    end_utc = end_at if end_at.tzinfo else end_at.replace(tzinfo=UTC)
    return "completed" if end_utc < datetime.now(UTC) else status
