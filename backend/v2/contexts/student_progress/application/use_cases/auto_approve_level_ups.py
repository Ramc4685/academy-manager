"""Use case: evening sweep that lands queued level-ups without an owner click.

A level whose ``requires_admin_approval`` is off moves the student up on its
own once the coach ticks the last skill. The move waits for this sweep rather
than happening on the tap, which gives the coach (or the owner, from the
queue) the rest of the day to undo a mistaken tap. Levels that do require
approval are left in the owner's queue exactly as before.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from pydantic import BaseModel

from backend.v2.contexts.student_progress.application.ports import (
    LevelUpRecommendationRepository,
    SkillLookup,
)
from backend.v2.contexts.student_progress.application.use_cases.review_level_up import (
    ReviewLevelUpCommand,
    ReviewLevelUpRecommendation,
)
from backend.v2.contexts.student_progress.domain.errors import (
    EnrollmentEnded,
    RecommendationAlreadyReviewed,
)

log = logging.getLogger(__name__)

AUTO_REVIEWER = "system:auto_level_up"

#: rec_id -> certificate display fields (student_name, level_name,
#: program_name, level_sequence). Resolved by the caller, as the admin
#: approve route does, because the names live outside this context.
CertificateDisplayResolver = Callable[[str], Awaitable[dict[str, object]]]


class AutoApproveLevelUpsResult(BaseModel):
    model_config = {"frozen": True}
    approved: int = 0
    needs_owner: int = 0
    skipped: int = 0


class AutoApproveLevelUps:
    def __init__(
        self,
        *,
        recommendations: LevelUpRecommendationRepository,
        skill_lookup: SkillLookup,
        review_level_up: ReviewLevelUpRecommendation,
    ) -> None:
        self._recs = recommendations
        self._skill_lookup = skill_lookup
        self._review = review_level_up

    async def execute(self, display_for: CertificateDisplayResolver) -> AutoApproveLevelUpsResult:
        approved = needs_owner = skipped = 0
        for rec in await self._recs.list_pending():
            # A claimed row belongs to the reviewer holding it.
            if rec.status != "RECOMMENDED":
                continue
            level = await self._skill_lookup.get_level(rec.from_level_id)
            if level is None or getattr(level, "requires_admin_approval", False):
                needs_owner += 1
                continue
            display = await display_for(rec.rec_id)
            try:
                await self._review.execute(
                    ReviewLevelUpCommand(
                        rec_id=rec.rec_id,
                        action="approve",
                        reviewed_by=AUTO_REVIEWER,
                        student_name=str(display.get("student_name") or ""),
                        level_name=str(display.get("level_name") or ""),
                        program_name=str(display.get("program_name") or ""),
                        level_sequence=int(display.get("level_sequence") or 1),  # type: ignore[call-overload]
                    )
                )
                approved += 1
            except (EnrollmentEnded, RecommendationAlreadyReviewed) as exc:
                # Withdrawn student, or the owner/coach acted first: leave it.
                log.info("auto_level_up_skipped", extra={"rec_id": rec.rec_id, "reason": exc.code})
                skipped += 1
        return AutoApproveLevelUpsResult(
            approved=approved, needs_owner=needs_owner, skipped=skipped
        )
