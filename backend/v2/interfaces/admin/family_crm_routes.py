"""Admin BFF: family notes and follow-ups (People CRM spec §5, Phase 4a).

* ``GET/POST /admin/families/{parent_id}/notes``
* ``PATCH/DELETE /admin/families/{parent_id}/notes/{note_id}`` (author or
  owner only; DELETE is a soft delete)
* ``GET/POST /admin/families/{parent_id}/follow-ups``
* ``PATCH /admin/families/{parent_id}/follow-ups/{follow_up_id}``
* ``GET /admin/follow-ups?assignee=me|all&bucket=overdue|today|upcoming|done``

Every route is ``require_persona("admin")``: a coach or parent gets the same
404 every wrong-persona call gets (docs/security-matrix.md). The academy is
the request's tenant; no body carries one. ``parent_id`` must be a family of
that academy (404 otherwise), resolved to its canonical id.

Services hang off ``app.state.admin_family_index`` (``composition/
families_crm.py``). Domain errors (404 not found, 403 not the author, 422
validation, 409 duplicate id) are mapped by the registered handler.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from backend.v2.contexts.crm.application.use_cases.family_follow_ups import (
    MAX_FOLLOW_UP_TITLE_LEN,
    FamilyFollowUp,
    FollowUpChanges,
    follow_up_bucket,
)
from backend.v2.contexts.crm.application.use_cases.family_notes import (
    MAX_NOTE_BODY_LEN,
    Actor,
    FamilyNote,
    can_edit_note,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona
from backend.v2.shared.tenancy import TenantContextUnset, current_academy_id

from .family_contacts_routes import router as family_contacts_router
from .family_import_routes import router as family_import_router
from .family_messages_routes import router as family_messages_router
from .family_timeline_routes import router as family_timeline_router
from .people_duplicate_routes import router as people_duplicate_router

router = APIRouter(tags=["admin.families"])
# Phase 4b family contacts and details ride on this router so admin/router.py
# needs no new line (family_contacts_routes.py).
router.include_router(family_contacts_router)
# Phase 4c: the duplicate warning on Add family / Add user / Add contact.
router.include_router(people_duplicate_router)
# Phase 5: the unified family timeline.
router.include_router(family_timeline_router)
# Phase 6: the family Messages tab (send logs + logged contacts).
router.include_router(family_messages_router)
# Roadmap L8a: CSV family and student import (preview and commit).
router.include_router(family_import_router)

# Raw-body caps sit a little above the domain caps so the domain's clearer
# message wins for "just over"; anything far over is refused by pydantic.
_BODY_CAP = MAX_NOTE_BODY_LEN * 2
_TITLE_CAP = MAX_FOLLOW_UP_TITLE_LEN * 2


def get_admin_family_crm(request: Request) -> Any:
    services = getattr(request.app.state, "admin_family_index", None)
    if services is None or getattr(services, "notes", None) is None:
        raise HTTPException(status_code=503, detail="family notes are not configured")
    return services


def _academy_id(claims: AuthClaims) -> str:
    try:
        return current_academy_id()
    except TenantContextUnset:
        return claims.academy_id


def _actor(claims: AuthClaims) -> Actor:
    return Actor(user_id=claims.user_id, roles=tuple(claims.roles))


# ------------------------------------------------------------------ views


class FamilyNoteView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note_id: str
    parent_id: str
    body: str
    author_user_id: str
    created_at: datetime
    updated_at: datetime
    edited: bool
    can_edit: bool


class FamilyNoteList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    family_id: str
    notes: list[FamilyNoteView]


class FollowUpView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    follow_up_id: str
    parent_id: str
    family_name: str | None = None
    title: str
    due_on: date
    assignee_user_id: str
    status: Literal["open", "done"]
    bucket: Literal["overdue", "today", "upcoming", "done"]
    created_by: str
    created_at: datetime
    updated_at: datetime
    done_at: datetime | None = None
    done_by: str | None = None


class FamilyFollowUpList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    family_id: str
    today: date
    follow_ups: list[FollowUpView]


class FollowUpQueueView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    today: date
    assignee: Literal["me", "all"]
    bucket: Literal["overdue", "today", "upcoming", "done"] | None
    follow_ups: list[FollowUpView]


def _note_view(note: FamilyNote, claims: AuthClaims) -> FamilyNoteView:
    return FamilyNoteView(
        note_id=note.note_id,
        parent_id=note.parent_id,
        body=note.body,
        author_user_id=note.author_user_id,
        created_at=note.created_at,
        updated_at=note.updated_at,
        edited=note.updated_at > note.created_at,
        can_edit=can_edit_note(note, user_id=claims.user_id, roles=claims.roles),
    )


def _follow_up_view(
    row: FamilyFollowUp, today: date, family_name: str | None = None
) -> FollowUpView:
    return FollowUpView(
        follow_up_id=row.follow_up_id,
        parent_id=row.parent_id,
        family_name=family_name,
        title=row.title,
        due_on=row.due_on,
        assignee_user_id=row.assignee_user_id,
        status=row.status,
        bucket=follow_up_bucket(row, today),
        created_by=row.created_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
        done_at=row.done_at,
        done_by=row.done_by,
    )


# ------------------------------------------------------------------ requests


class NoteBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str = Field(max_length=_BODY_CAP)


class NewFollowUp(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(max_length=_TITLE_CAP)
    due_on: date
    assignee_user_id: str = Field(min_length=1, max_length=128)


class FollowUpPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=_TITLE_CAP)
    due_on: date | None = None
    assignee_user_id: str | None = Field(default=None, min_length=1, max_length=128)
    status: Literal["open", "done"] | None = None


# ------------------------------------------------------------------ notes


@router.get("/families/{parent_id}/notes", response_model=FamilyNoteList)
async def list_family_notes(
    parent_id: str,
    claims: AuthClaims = Depends(require_persona("admin")),
    services: Any = Depends(get_admin_family_crm),
) -> FamilyNoteList:
    family_id, notes = await services.notes.list.execute(
        academy_id=_academy_id(claims), parent_id=parent_id
    )
    return FamilyNoteList(family_id=family_id, notes=[_note_view(n, claims) for n in notes])


@router.post("/families/{parent_id}/notes", response_model=FamilyNoteView, status_code=201)
async def add_family_note(
    parent_id: str,
    payload: NoteBody,
    claims: AuthClaims = Depends(require_persona("admin")),
    services: Any = Depends(get_admin_family_crm),
) -> FamilyNoteView:
    note = await services.notes.add.execute(
        academy_id=_academy_id(claims),
        parent_id=parent_id,
        body=payload.body,
        actor=_actor(claims),
    )
    return _note_view(note, claims)


@router.patch("/families/{parent_id}/notes/{note_id}", response_model=FamilyNoteView)
async def edit_family_note(
    parent_id: str,
    note_id: str,
    payload: NoteBody,
    claims: AuthClaims = Depends(require_persona("admin")),
    services: Any = Depends(get_admin_family_crm),
) -> FamilyNoteView:
    note = await services.notes.edit.execute(
        academy_id=_academy_id(claims),
        parent_id=parent_id,
        note_id=note_id,
        body=payload.body,
        actor=_actor(claims),
    )
    return _note_view(note, claims)


@router.delete("/families/{parent_id}/notes/{note_id}", status_code=204)
async def delete_family_note(
    parent_id: str,
    note_id: str,
    claims: AuthClaims = Depends(require_persona("admin")),
    services: Any = Depends(get_admin_family_crm),
) -> Response:
    await services.notes.delete.execute(
        academy_id=_academy_id(claims),
        parent_id=parent_id,
        note_id=note_id,
        actor=_actor(claims),
    )
    return Response(status_code=204)


# ------------------------------------------------------------------ follow-ups


@router.get("/families/{parent_id}/follow-ups", response_model=FamilyFollowUpList)
async def list_family_follow_ups(
    parent_id: str,
    claims: AuthClaims = Depends(require_persona("admin")),
    services: Any = Depends(get_admin_family_crm),
) -> FamilyFollowUpList:
    result = await services.follow_ups.list.execute(
        academy_id=_academy_id(claims), parent_id=parent_id
    )
    return FamilyFollowUpList(
        family_id=result.family_id,
        today=result.today,
        follow_ups=[_follow_up_view(row, result.today) for row in result.follow_ups],
    )


@router.post("/families/{parent_id}/follow-ups", response_model=FollowUpView, status_code=201)
async def add_family_follow_up(
    parent_id: str,
    payload: NewFollowUp,
    claims: AuthClaims = Depends(require_persona("admin")),
    services: Any = Depends(get_admin_family_crm),
) -> FollowUpView:
    row = await services.follow_ups.add.execute(
        academy_id=_academy_id(claims),
        parent_id=parent_id,
        title=payload.title,
        due_on=payload.due_on,
        assignee_user_id=payload.assignee_user_id,
        actor=_actor(claims),
    )
    today = await services.follow_ups.add.today(_academy_id(claims))
    return _follow_up_view(row, today)


@router.patch("/families/{parent_id}/follow-ups/{follow_up_id}", response_model=FollowUpView)
async def update_family_follow_up(
    parent_id: str,
    follow_up_id: str,
    payload: FollowUpPatch,
    claims: AuthClaims = Depends(require_persona("admin")),
    services: Any = Depends(get_admin_family_crm),
) -> FollowUpView:
    row = await services.follow_ups.update.execute(
        academy_id=_academy_id(claims),
        parent_id=parent_id,
        follow_up_id=follow_up_id,
        changes=FollowUpChanges(
            title=payload.title,
            due_on=payload.due_on,
            assignee_user_id=payload.assignee_user_id,
            status=payload.status,
        ),
        actor=_actor(claims),
    )
    today = await services.follow_ups.update.today(_academy_id(claims))
    return _follow_up_view(row, today)


@router.get("/follow-ups", response_model=FollowUpQueueView)
async def list_follow_ups(
    assignee: Literal["me", "all"] = "me",
    bucket: Literal["overdue", "today", "upcoming", "done"] | None = None,
    claims: AuthClaims = Depends(require_persona("admin")),
    services: Any = Depends(get_admin_family_crm),
) -> FollowUpQueueView:
    queue = await services.follow_ups.queue.execute(
        academy_id=_academy_id(claims),
        assignee_user_id=claims.user_id if assignee == "me" else None,
        bucket=bucket,
    )
    return FollowUpQueueView(
        today=queue.today,
        assignee=assignee,
        bucket=bucket,
        follow_ups=[
            _follow_up_view(item.follow_up, queue.today, item.family_name) for item in queue.items
        ],
    )
