"""Admin curriculum pathway routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.v2.contexts.curriculum.application.use_cases.manage_criteria import (
    AddSkillCriterionCommand,
)
from backend.v2.contexts.curriculum.application.use_cases.manage_levels import (
    CreateLevelCommand,
    UpdateLevelCommand,
)
from backend.v2.contexts.curriculum.application.use_cases.manage_program import (
    CreateProgramCommand,
)
from backend.v2.contexts.curriculum.application.use_cases.manage_refs import (
    AddExternalReferenceCommand,
)
from backend.v2.contexts.curriculum.application.use_cases.manage_skills import (
    CreateSkillCommand,
    UpdateSkillCommand,
)
from backend.v2.contexts.curriculum.application.errors import (
    LevelNotFound,
    ProgramNotFound,
    SkillNotFound,
)
from backend.v2.interfaces.admin.deps import AdminUseCases, get_admin_use_cases
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["admin-pathway"])


# ---------------------------------------------------------------------------
# Request body models
# ---------------------------------------------------------------------------


class CreateProgramBody(BaseModel):
    sport: str
    name: str
    description: str = ""


class CreateLevelBody(BaseModel):
    sequence: int = Field(ge=1)
    name: str
    description: str = ""
    completion_rule: str = "ALL_REQUIRED_SKILLS"
    requires_coach_recommendation: bool = True
    requires_admin_approval: bool = False


class UpdateLevelBody(BaseModel):
    name: str | None = None
    description: str | None = None
    completion_rule: str | None = None
    requires_coach_recommendation: bool | None = None
    requires_admin_approval: bool | None = None


class CreateSkillBody(BaseModel):
    program_id: str
    sequence: int = Field(ge=1)
    name: str
    description: str = ""
    is_required: bool = True
    scoring_type: str = "ATTEMPT_BASED"
    pass_threshold_pct: float = Field(default=70.0, ge=0.0, le=100.0)
    coach_override_allowed: bool = False


class UpdateSkillBody(BaseModel):
    name: str | None = None
    description: str | None = None
    is_required: bool | None = None
    scoring_type: str | None = None
    pass_threshold_pct: float | None = None
    coach_override_allowed: bool | None = None


class AddCriterionBody(BaseModel):
    level_id: str
    program_id: str
    description: str
    display_order: int = Field(ge=0, default=0)


class AddExternalRefBody(BaseModel):
    source: str
    source_title: str
    module_name: str
    lesson_range: str
    reference_title: str
    page_hint: str | None = None
    internal_note: str = ""


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/programs", status_code=201)
async def create_program(
    body: CreateProgramBody,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> object:
    if use_cases.curriculum is None:
        raise HTTPException(status_code=503, detail="Curriculum service not configured")
    program = await use_cases.curriculum.create_program.execute(
        CreateProgramCommand(
            sport=body.sport,
            name=body.name,
            description=body.description,
            created_by=claims.user_id,
        )
    )
    return program.model_dump()


@router.get("/programs")
async def list_programs(
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> object:
    if use_cases.curriculum is None:
        raise HTTPException(status_code=503, detail="Curriculum service not configured")
    programs = await use_cases.curriculum.list_programs.execute()
    return {"programs": [p.model_dump() for p in programs]}


@router.get("/programs/{program_id}/pathway")
async def get_pathway(
    program_id: str,
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> object:
    if use_cases.curriculum is None:
        raise HTTPException(status_code=503, detail="Curriculum service not configured")
    try:
        pathway = await use_cases.curriculum.get_full_pathway.execute(program_id)
    except ProgramNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return pathway.model_dump()


@router.post("/programs/{program_id}/levels", status_code=201)
async def create_level(
    program_id: str,
    body: CreateLevelBody,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> object:
    if use_cases.curriculum is None:
        raise HTTPException(status_code=503, detail="Curriculum service not configured")
    try:
        level = await use_cases.curriculum.create_level.execute(
            CreateLevelCommand(
                program_id=program_id,
                sequence=body.sequence,
                name=body.name,
                description=body.description,
                completion_rule=body.completion_rule,  # type: ignore[arg-type]
                requires_coach_recommendation=body.requires_coach_recommendation,
                requires_admin_approval=body.requires_admin_approval,
                created_by=claims.user_id,
            )
        )
    except ProgramNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return level.model_dump()


@router.put("/levels/{level_id}")
async def update_level(
    level_id: str,
    body: UpdateLevelBody,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> object:
    if use_cases.curriculum is None:
        raise HTTPException(status_code=503, detail="Curriculum service not configured")
    try:
        level = await use_cases.curriculum.update_level.execute(
            UpdateLevelCommand(
                level_id=level_id,
                name=body.name,
                description=body.description,
                completion_rule=body.completion_rule,  # type: ignore[arg-type]
                requires_coach_recommendation=body.requires_coach_recommendation,
                requires_admin_approval=body.requires_admin_approval,
                updated_by=claims.user_id,
            )
        )
    except LevelNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return level.model_dump()


@router.post("/levels/{level_id}/skills", status_code=201)
async def create_skill(
    level_id: str,
    body: CreateSkillBody,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> object:
    if use_cases.curriculum is None:
        raise HTTPException(status_code=503, detail="Curriculum service not configured")
    try:
        skill = await use_cases.curriculum.create_skill.execute(
            CreateSkillCommand(
                level_id=level_id,
                program_id=body.program_id,
                sequence=body.sequence,
                name=body.name,
                description=body.description,
                is_required=body.is_required,
                scoring_type=body.scoring_type,  # type: ignore[arg-type]
                pass_threshold_pct=body.pass_threshold_pct,
                coach_override_allowed=body.coach_override_allowed,
                created_by=claims.user_id,
            )
        )
    except LevelNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return skill.model_dump()


@router.put("/skills/{skill_id}")
async def update_skill(
    skill_id: str,
    body: UpdateSkillBody,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> object:
    if use_cases.curriculum is None:
        raise HTTPException(status_code=503, detail="Curriculum service not configured")
    try:
        skill = await use_cases.curriculum.update_skill.execute(
            UpdateSkillCommand(
                skill_id=skill_id,
                name=body.name,
                description=body.description,
                is_required=body.is_required,
                scoring_type=body.scoring_type,  # type: ignore[arg-type]
                pass_threshold_pct=body.pass_threshold_pct,
                coach_override_allowed=body.coach_override_allowed,
                updated_by=claims.user_id,
            )
        )
    except SkillNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return skill.model_dump()


@router.post("/skills/{skill_id}/criteria", status_code=201)
async def add_criterion(
    skill_id: str,
    body: AddCriterionBody,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> object:
    if use_cases.curriculum is None:
        raise HTTPException(status_code=503, detail="Curriculum service not configured")
    try:
        criterion = await use_cases.curriculum.add_criterion.execute(
            AddSkillCriterionCommand(
                skill_id=skill_id,
                level_id=body.level_id,
                program_id=body.program_id,
                description=body.description,
                display_order=body.display_order,
                created_by=claims.user_id,
            )
        )
    except SkillNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return criterion.model_dump()


@router.post("/skills/{skill_id}/external-refs", status_code=201)
async def add_external_ref(
    skill_id: str,
    body: AddExternalRefBody,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> object:
    if use_cases.curriculum is None:
        raise HTTPException(status_code=503, detail="Curriculum service not configured")
    try:
        ref = await use_cases.curriculum.add_external_ref.execute(
            AddExternalReferenceCommand(
                skill_id=skill_id,
                source=body.source,  # type: ignore[arg-type]
                source_title=body.source_title,
                module_name=body.module_name,
                lesson_range=body.lesson_range,
                reference_title=body.reference_title,
                page_hint=body.page_hint,
                internal_note=body.internal_note,
                created_by=claims.user_id,
            )
        )
    except SkillNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ref.model_dump()


@router.post("/programs/{program_id}/seed-badminton")
async def seed_badminton(
    program_id: str,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> object:
    if use_cases.curriculum is None:
        raise HTTPException(status_code=503, detail="Curriculum service not configured")
    program = await use_cases.curriculum.seed_badminton.execute(created_by=claims.user_id)
    return {"program_id": program.program_id, "name": program.name}  # type: ignore[union-attr]
