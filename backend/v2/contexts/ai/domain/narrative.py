"""B4 parent progress narrative: the stored draft and its errors."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from backend.v2.shared.http.errors import DomainError

NarrativeStatus = Literal["pending_review", "approved", "rejected"]
NarrativeKind = Literal["evening_wins", "report_card"]

#: ``approver`` on the narrative and its ``ai_calls`` row when the academy has
#: turned coach review off (``ai.coach_review_narratives`` false).
COACH_REVIEW_OFF = "coach_review_off"


class AiNarrative(BaseModel):
    """One model-drafted paragraph for one child and one day. ``academy_id``
    is stamped by the repository from the tenant scope."""

    model_config = {"frozen": True}

    narrative_id: str
    student_id: str
    #: YYYY-MM-DD in the academy's day.
    for_date: str
    kind: NarrativeKind
    text: str = Field(min_length=1, max_length=500)
    status: NarrativeStatus
    approver: str | None = None
    prompt_version: str
    #: The ``ai_calls`` row this draft came from; approval stamps its approver.
    call_id: str | None = None
    #: The coach who asked for the draft; the pending list is theirs.
    created_by: str
    created_at: datetime
    decided_at: datetime | None = None
    #: ``source_fingerprint`` of the wins the draft was built from; the evening
    #: email recomputes it and skips the paragraph when the wins changed.
    source_fingerprint: str | None = None


def source_fingerprint(
    skills: Iterable[tuple[str, str | None]], passed_in_level: int, total_in_level: int
) -> str:
    """sha256 over the sorted (skill name, coach words) pairs and the level's
    passed/total counts. An undone tap or an edited note changes it."""
    payload = [
        sorted((name, words or "") for name, words in skills),
        passed_in_level,
        total_in_level,
    ]
    return hashlib.sha256(json.dumps(payload).encode()).hexdigest()


class NoWinsToday(DomainError):
    """The student mastered nothing in the day asked for: nothing to narrate."""

    code = "Ai.NoWinsToday"
    status_code = 409
