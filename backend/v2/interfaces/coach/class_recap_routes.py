"""Coach class recap routes, per dated occurrence.

GET  /coach/occurrences/{occurrence_id}/class-recap      read (lead, assistant, owner, admin)
PUT  /coach/occurrences/{occurrence_id}/class-recap      direct entry (lead coach or owner)
POST /coach/occurrences/{occurrence_id}/class-reports    after-class report (lead coach or owner)
POST /coach/occurrences/{occurrence_id}/class-reports/{report_id}/resolve   owner closes a handoff
POST /coach/occurrences/{occurrence_id}/class-demonstrations   a child met a skill's criterion (lead coach or owner)

Writes carry ``class_starts_at`` as read, so a write meant for one dated
class cannot land on a rescheduled one. The use cases own every rule (who may
write, present-only per-child practice, real curriculum, merge-only reports,
revision checks); these routes map claims to a ``RecapActor`` and shape the
response. Raw reports come back only to their author and the owner.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from backend.v2.composition.class_recap import ClassRecapComposition
from backend.v2.contexts.coaching.application.use_cases.class_recap import (
    MAX_PARTICIPANTS,
    MAX_TAUGHT_SKILLS,
    REPORT_MAX_CHARS,
    ChildPractice,
    ClassRecapState,
    ClassReport,
    DemonstrationOutcome,
    RecapActor,
    RecordClassDemonstrationCommand,
    SaveClassRecapCommand,
    SubmitClassReportCommand,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import is_assistant_only, is_coach_supervisor, require_coach_surface

router = APIRouter(tags=["coach.class-recap"])


class RecapSkillView(BaseModel):
    skill_id: str
    name: str
    level_name: str = ""


class RecapRosterView(BaseModel):
    student_id: str
    name: str
    attendance: str


class ChildPracticeView(BaseModel):
    student_id: str
    skill_ids: list[str] = Field(min_length=1, max_length=MAX_TAUGHT_SKILLS)


class PassClaimView(BaseModel):
    student_id: str
    skill_id: str


class ClassReportView(BaseModel):
    report_id: str
    is_mine: bool
    text: str
    submitted_at: datetime
    outcome: str
    ai_used: bool
    questions: list[str]
    pass_claims: list[PassClaimView]
    applied_revision: int | None
    resolved_at: datetime | None


class ClassRecapView(BaseModel):
    occurrence_id: str
    class_starts_at: datetime
    can_edit: bool
    can_resolve: bool
    ai_enabled: bool
    revision: int
    source: str | None
    updated_at: datetime | None
    taught_skills: list[RecapSkillView]
    practice: list[ChildPracticeView]
    roster: list[RecapRosterView]
    skill_options: list[RecapSkillView]
    reports: list[ClassReportView]


class SaveClassRecapBody(BaseModel):
    class_starts_at: datetime
    mutation_id: str = Field(min_length=1, max_length=64)
    expected_revision: int = Field(ge=0)
    taught_skill_ids: list[str] = Field(default_factory=list, max_length=MAX_TAUGHT_SKILLS)
    practice: list[ChildPracticeView] = Field(default_factory=list, max_length=MAX_PARTICIPANTS)


class SubmitClassReportBody(BaseModel):
    class_starts_at: datetime
    report_id: str = Field(min_length=1, max_length=64)
    text: str = Field(min_length=1, max_length=REPORT_MAX_CHARS)
    use_ai: bool = False


class RecordDemonstrationBody(BaseModel):
    class_starts_at: datetime
    mutation_id: str = Field(min_length=1, max_length=64)
    skill_id: str = Field(min_length=1, max_length=64)
    student_ids: list[str] = Field(min_length=1, max_length=MAX_PARTICIPANTS)


class DemonstrationOutcomeView(BaseModel):
    student_id: str
    outcome: str
    off_level: bool
    level_up_queued: bool
    tries: int


class DemonstrationResultsView(BaseModel):
    results: list[DemonstrationOutcomeView]


def _recap(request: Request) -> ClassRecapComposition:
    return request.app.state.class_recap  # type: ignore[no-any-return]


def _actor(claims: AuthClaims) -> RecapActor:
    return RecapActor(
        user_id=claims.user_id,
        is_owner="owner" in claims.roles,
        is_supervisor=is_coach_supervisor(claims),
        is_assistant_only=is_assistant_only(claims),
    )


def _report_view(report: ClassReport, user_id: str) -> ClassReportView:
    return ClassReportView(
        report_id=report.report_id,
        is_mine=report.author_id == user_id,
        text=report.text,
        submitted_at=report.submitted_at,
        outcome=report.outcome,
        ai_used=report.ai_used,
        questions=list(report.questions),
        pass_claims=[PassClaimView(**c.model_dump()) for c in report.pass_claims],
        applied_revision=report.applied_revision,
        resolved_at=report.resolved_at,
    )


def _view(state: ClassRecapState, *, ai_enabled: bool, actor: RecapActor) -> ClassRecapView:
    recap = state.recap
    taught = list(recap.taught_skill_ids) if recap is not None else []
    levels = {o.skill_id: o.level_name for o in state.skill_options}
    return ClassRecapView(
        occurrence_id=state.occurrence_id,
        class_starts_at=state.class_starts_at,
        can_edit=state.can_edit,
        can_resolve=actor.is_owner,
        ai_enabled=ai_enabled,
        revision=recap.revision if recap is not None else 0,
        source=recap.source if recap is not None else None,
        updated_at=recap.updated_at if recap is not None else None,
        taught_skills=[
            RecapSkillView(
                skill_id=sid,
                name=state.skill_names.get(sid, "Retired skill"),
                level_name=levels.get(sid, ""),
            )
            for sid in taught
        ],
        practice=[
            ChildPracticeView(student_id=row.student_id, skill_ids=list(row.skill_ids))
            for row in (recap.practice if recap is not None else ())
        ],
        roster=[RecapRosterView(**r.model_dump()) for r in state.roster],
        skill_options=[RecapSkillView(**o.model_dump()) for o in state.skill_options],
        reports=[_report_view(r, actor.user_id) for r in state.reports],
    )


@router.get("/occurrences/{occurrence_id}/class-recap", response_model=ClassRecapView)
async def get_class_recap(
    occurrence_id: str,
    claims: AuthClaims = Depends(require_coach_surface()),
    recap: ClassRecapComposition = Depends(_recap),
) -> ClassRecapView:
    actor = _actor(claims)
    state = await recap.get.execute(occurrence_id, actor)
    return _view(state, ai_enabled=recap.ai_enabled, actor=actor)


@router.put("/occurrences/{occurrence_id}/class-recap", response_model=ClassRecapView)
async def save_class_recap(
    occurrence_id: str,
    body: SaveClassRecapBody,
    claims: AuthClaims = Depends(require_coach_surface()),
    recap: ClassRecapComposition = Depends(_recap),
) -> ClassRecapView:
    actor = _actor(claims)
    await recap.save.execute(
        SaveClassRecapCommand(
            occurrence_id=occurrence_id,
            class_starts_at=body.class_starts_at,
            mutation_id=body.mutation_id,
            expected_revision=body.expected_revision,
            taught_skill_ids=body.taught_skill_ids,
            practice=[
                ChildPractice(student_id=row.student_id, skill_ids=tuple(row.skill_ids))
                for row in body.practice
            ],
        ),
        actor,
    )
    state = await recap.get.execute(occurrence_id, actor)
    return _view(state, ai_enabled=recap.ai_enabled, actor=actor)


@router.post("/occurrences/{occurrence_id}/class-reports", response_model=ClassReportView)
async def submit_class_report(
    occurrence_id: str,
    body: SubmitClassReportBody,
    claims: AuthClaims = Depends(require_coach_surface()),
    recap: ClassRecapComposition = Depends(_recap),
) -> ClassReportView:
    report = await recap.submit_report.execute(
        SubmitClassReportCommand(occurrence_id=occurrence_id, **body.model_dump()),
        _actor(claims),
    )
    return _report_view(report, claims.user_id)


@router.post(
    "/occurrences/{occurrence_id}/class-reports/{report_id}/resolve",
    response_model=ClassReportView,
)
async def resolve_class_report(
    occurrence_id: str,
    report_id: str,
    claims: AuthClaims = Depends(require_coach_surface()),
    recap: ClassRecapComposition = Depends(_recap),
) -> ClassReportView:
    report = await recap.resolve_report.execute(occurrence_id, report_id, _actor(claims))
    return _report_view(report, claims.user_id)


@router.post(
    "/occurrences/{occurrence_id}/class-demonstrations",
    response_model=DemonstrationResultsView,
)
async def record_class_demonstration(
    occurrence_id: str,
    body: RecordDemonstrationBody,
    claims: AuthClaims = Depends(require_coach_surface()),
    recap: ClassRecapComposition = Depends(_recap),
) -> DemonstrationResultsView:
    outcomes: list[DemonstrationOutcome] = await recap.record_demonstration.execute(
        RecordClassDemonstrationCommand(occurrence_id=occurrence_id, **body.model_dump()),
        _actor(claims),
    )
    return DemonstrationResultsView(
        results=[DemonstrationOutcomeView(**o.model_dump()) for o in outcomes]
    )
