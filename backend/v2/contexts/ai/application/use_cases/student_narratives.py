"""B4: a coach asks for tonight's note on a student, then approves or rejects it.

``NarrativeFacts`` is implemented at the composition root over the same
student_progress and curriculum reads the evening wins provider uses, so this
context imports nothing from them (ADR-0005).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Literal, Protocol

from backend.v2.contexts.ai.application.ports import AiCallRepository
from backend.v2.contexts.ai.application.use_cases.draft_progress_narrative import (
    DraftProgressNarrative,
    ProgressNarrativeInput,
)
from backend.v2.contexts.ai.domain.narrative import COACH_REVIEW_OFF, AiNarrative, NoWinsToday
from backend.v2.shared.ids import new_ulid


class NarrativeFacts(Protocol):
    """Today's wins for one student as the model may see them; ``None`` when
    the student mastered nothing in ``[start, end)``."""

    async def facts_for(
        self, student_id: str, start: datetime, end: datetime
    ) -> ProgressNarrativeInput | None: ...


class CoachReviewSwitch(Protocol):
    """``ai.coach_review_narratives`` on the academy in scope; default True."""

    async def coach_review_required(self) -> bool: ...


class AiNarrativeRepository(Protocol):
    async def upsert_draft(self, row: AiNarrative) -> AiNarrative: ...
    async def get(self, narrative_id: str) -> AiNarrative | None: ...
    async def list_pending(self, for_date: str, created_by: str | None) -> list[AiNarrative]: ...
    async def decide(
        self,
        narrative_id: str,
        *,
        status: Literal["approved", "rejected"],
        text: str | None,
        approver: str | None,
        decided_at: datetime,
    ) -> AiNarrative | None: ...


class DraftStudentNarrative:
    def __init__(
        self,
        *,
        facts: NarrativeFacts,
        drafter: DraftProgressNarrative,
        review: CoachReviewSwitch,
        narratives: AiNarrativeRepository,
        calls: AiCallRepository,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._facts = facts
        self._drafter = drafter
        self._review = review
        self._narratives = narratives
        self._calls = calls
        self._clock = clock or (lambda: datetime.now(UTC))

    async def execute(
        self, *, student_id: str, for_date: date, start: datetime, end: datetime, coach_id: str
    ) -> AiNarrative:
        facts = await self._facts.facts_for(student_id, start, end)
        if facts is None:
            raise NoWinsToday("no skill mastered that day", student_id=student_id)
        draft, call = await self._drafter.execute(facts)
        review = await self._review.coach_review_required()
        now = self._clock()
        if not review:
            await self._calls.set_approver(call.call_id, COACH_REVIEW_OFF)
        return await self._narratives.upsert_draft(
            AiNarrative(
                narrative_id=new_ulid(),
                student_id=student_id,
                for_date=for_date.isoformat(),
                kind="evening_wins",
                text=draft.text,
                status="pending_review" if review else "approved",
                approver=None if review else COACH_REVIEW_OFF,
                prompt_version=call.prompt_version,
                call_id=call.call_id,
                created_by=coach_id,
                created_at=now,
                decided_at=None if review else now,
            )
        )


class ReviewNarratives:
    def __init__(
        self,
        *,
        narratives: AiNarrativeRepository,
        calls: AiCallRepository,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._narratives = narratives
        self._calls = calls
        self._clock = clock or (lambda: datetime.now(UTC))

    async def get(self, narrative_id: str) -> AiNarrative | None:
        return await self._narratives.get(narrative_id)

    async def pending(self, for_date: date, created_by: str | None) -> list[AiNarrative]:
        return await self._narratives.list_pending(for_date.isoformat(), created_by)

    async def decide(
        self,
        narrative_id: str,
        *,
        status: Literal["approved", "rejected"],
        text: str | None,
        approver: str,
    ) -> AiNarrative | None:
        """Approve (optionally with the coach's edited text) or reject a pending
        row. Approving also stamps the coach on the ``ai_calls`` row."""
        row = await self._narratives.decide(
            narrative_id,
            status=status,
            text=text,
            approver=approver if status == "approved" else None,
            decided_at=self._clock(),
        )
        if row is not None and status == "approved" and row.call_id:
            await self._calls.set_approver(row.call_id, approver)
        return row
