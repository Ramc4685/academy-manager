"""Admin BFF: CSV family and student import (roadmap L8a).

* ``POST /admin/imports/families/preview`` with ``{filename?, csv}``: a dry
  run. Parses the file, checks every row (strict columns, formula-injection
  sanitising, per-row errors, duplicates against this academy's families via
  the People CRM duplicate finder) and stores the plan as an import batch.
  Writes no family or student. Answers the batch: its id, a summary and one
  result per row.
* ``POST /admin/imports/families/commit`` with ``{import_batch_id}``: writes
  the rows the batch planned ``create``, after checking them again against
  the data as it is now. Idempotent by batch id: a second commit answers the
  stored result (``already_committed: true``) and writes nothing.

Rules:

* ``require_persona("admin")`` (owners hold it too): a coach, parent, or a
  billing or front desk member gets the wrong-persona 404
  (docs/security-matrix.md).
* Tenant-scoped: the academy is the request's tenant; the body carries none
  (extra fields are refused) and a batch id of another academy is a 404.
* The raw body is read in chunks and refused past :data:`MAX_BODY_BYTES`
  before any parsing; the CSV itself is capped at ``MAX_IMPORT_BYTES``
  bytes and ``MAX_IMPORT_ROWS`` rows (422 ``Crm.InvalidImportFile``).
* Rate-limited per client (``_PATH_LIMIT_OVERRIDES``).

Services are composed on first use and kept on
``app.state.admin_family_import`` (``composition/family_import.py``). This
router is included by ``family_crm_routes.router``.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.v2.composition.family_import import compose_admin_family_import
from backend.v2.contexts.crm.application.use_cases.family_import import (
    MAX_IMPORT_BYTES,
    ImportBatch,
    ImportSummary,
    PlannedRow,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona
from backend.v2.shared.tenancy import TenantContextUnset, current_academy_id

router = APIRouter(tags=["admin.imports"])

#: JSON escaping can double a CSV's size (every quote and newline), plus
#: room for the envelope. Anything larger is refused unread.
MAX_BODY_BYTES = 2 * MAX_IMPORT_BYTES + 4_096
_FILENAME_CAP = 200
_BATCH_ID_CAP = 64


def get_admin_family_import(request: Request) -> Any:
    state = request.app.state
    services = getattr(state, "admin_family_import", None)
    if services is not None:
        return services
    db = getattr(state, "db", None)
    if db is None:
        raise HTTPException(status_code=503, detail="import is not configured")
    services = compose_admin_family_import(db)
    state.admin_family_import = services
    return services


def _academy_id(claims: AuthClaims) -> str:
    try:
        return current_academy_id()
    except TenantContextUnset:
        return claims.academy_id


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str | None = Field(default=None, max_length=_FILENAME_CAP)
    csv: str


class CommitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    import_batch_id: str = Field(min_length=1, max_length=_BATCH_ID_CAP)


class RowIssueView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    message: str


class ImportRowView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    line: int
    status: Literal["create", "skip", "error"]
    family_action: Literal["new", "existing"] | None = None
    family_id: str | None = None
    #: Opens an existing family; None for a new one (it exists after commit).
    family_link: str | None = None
    family_name: str | None = None
    parent_name: str
    parent_email: str | None = None
    parent_phone: str | None = None
    student_name: str
    student_date_of_birth: str | None = None
    errors: list[RowIssueView]
    warnings: list[str]


class ImportSummaryView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rows_total: int
    rows_create: int
    rows_skip: int
    rows_error: int
    families_new: int
    families_existing: int


class ImportBatchView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    import_batch_id: str
    status: Literal["previewed", "committing", "committed"]
    filename: str | None = None
    created_at: datetime
    committed_at: datetime | None = None
    #: True when the plan has no error rows (the commit may still find new
    #: conflicts; it checks again).
    can_commit: bool
    summary: ImportSummaryView
    rows: list[ImportRowView]


class CommitResponse(ImportBatchView):
    already_committed: bool
    students_inserted: int


def _row_view(planned: PlannedRow) -> ImportRowView:
    row = planned.row
    existing = planned.family_action == "existing" and planned.family_id
    return ImportRowView(
        line=row.line,
        status=planned.status,
        family_action=planned.family_action,
        family_id=planned.family_id,
        family_link=(
            f"/admin/families/{quote(str(planned.family_id), safe='')}" if existing else None
        ),
        family_name=planned.family_name,
        parent_name=row.parent_name,
        parent_email=row.parent_email,
        parent_phone=row.parent_phone,
        student_name=row.student_name,
        student_date_of_birth=row.student_date_of_birth,
        errors=[RowIssueView(field=i.field, message=i.message) for i in planned.errors],
        warnings=list(planned.warnings),
    )


def _summary_view(summary: ImportSummary) -> ImportSummaryView:
    return ImportSummaryView(
        rows_total=summary.rows_total,
        rows_create=summary.rows_create,
        rows_skip=summary.rows_skip,
        rows_error=summary.rows_error,
        families_new=summary.families_new,
        families_existing=summary.families_existing,
    )


def _batch_fields(batch: ImportBatch) -> dict[str, Any]:
    return {
        "import_batch_id": batch.import_batch_id,
        "status": batch.status,
        "filename": batch.filename,
        "created_at": batch.created_at,
        "committed_at": batch.committed_at,
        "can_commit": batch.status == "previewed" and not batch.summary.has_errors,
        "summary": _summary_view(batch.summary),
        "rows": [_row_view(row) for row in batch.rows],
    }


async def _read_body(request: Request) -> bytes:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="The upload is too large.")
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BODY_BYTES:
            raise HTTPException(status_code=413, detail="The upload is too large.")
        chunks.append(chunk)
    return b"".join(chunks)


def _parse_preview(raw: bytes) -> PreviewRequest:
    try:
        return PreviewRequest.model_validate(json.loads(raw or b"null"))
    except (ValueError, ValidationError) as exc:
        errors = exc.errors() if isinstance(exc, ValidationError) else []
        detail = [{"loc": list(e.get("loc", ())), "msg": e.get("msg")} for e in errors]
        raise HTTPException(
            status_code=422, detail=detail or "The body must be JSON {filename?, csv}."
        ) from None


@router.post("/imports/families/preview", response_model=ImportBatchView)
async def preview_family_import(
    request: Request,
    claims: AuthClaims = Depends(require_persona("admin")),
    services: Any = Depends(get_admin_family_import),
) -> ImportBatchView:
    body = _parse_preview(await _read_body(request))
    academy_id = _academy_id(claims)
    batch = await services.preview.execute(
        academy_id,
        csv_text=body.csv,
        filename=body.filename,
        actor_id=claims.user_id,
        today=await services.academy_today(academy_id),
    )
    return ImportBatchView(**_batch_fields(batch))


@router.post("/imports/families/commit", response_model=CommitResponse)
async def commit_family_import(
    body: CommitRequest,
    claims: AuthClaims = Depends(require_persona("admin")),
    services: Any = Depends(get_admin_family_import),
) -> CommitResponse:
    result = await services.commit.execute(
        _academy_id(claims), import_batch_id=body.import_batch_id, actor_id=claims.user_id
    )
    return CommitResponse(
        **_batch_fields(result.batch),
        already_committed=result.already_committed,
        students_inserted=result.students_inserted,
    )
