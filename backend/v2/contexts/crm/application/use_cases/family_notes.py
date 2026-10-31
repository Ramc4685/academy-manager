"""Family notes: list, add, edit, soft delete (People CRM spec §5 "Notes").

Every use case first proves ``parent_id`` is a family of the caller's academy
through ``FamilyDirectory`` (404 otherwise) and then works on the canonical
family id, so a note written from an alias URL lands on the same family.
Edit and delete are for the note's author or an academy owner (403 for any
other admin). Delete is soft: the row keeps its body and gains
``deleted_at`` / ``deleted_by``, and every read skips it.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from backend.v2.contexts.crm.application.ports import FamilyDirectory, FamilyNoteRepository
from backend.v2.contexts.crm.domain.errors import (
    FamilyNoteNotFound,
    FamilyNotFound,
    NoteEditForbidden,
)
from backend.v2.contexts.crm.domain.family_notes import (
    MAX_NOTE_BODY_LEN,
    FamilyNote,
    can_edit_note,
    normalize_note_body,
)
from backend.v2.shared.ids import new_ulid

# Re-exported for the admin BFF (interfaces may not import the domain).
__all__ = [
    "MAX_NOTE_BODY_LEN",
    "Actor",
    "AddFamilyNote",
    "DeleteFamilyNote",
    "EditFamilyNote",
    "FamilyNote",
    "ListFamilyNotes",
    "can_edit_note",
    "resolve_family",
    "utc_now_ms",
]


def utc_now_ms() -> datetime:
    now = datetime.now(UTC)
    return now.replace(microsecond=(now.microsecond // 1000) * 1000)


@dataclass(frozen=True)
class Actor:
    """Who is acting: the signed-in staff member and their academy roles."""

    user_id: str
    roles: Sequence[str] = ()


async def resolve_family(directory: FamilyDirectory, academy_id: str, parent_id: str) -> str:
    """The canonical family id, or ``FamilyNotFound``."""
    family = await directory.find(academy_id, parent_id)
    if family is None:
        raise FamilyNotFound("family not found", parent_id=parent_id)
    return family.family_id


class ListFamilyNotes:
    def __init__(self, notes: FamilyNoteRepository, families: FamilyDirectory) -> None:
        self._notes = notes
        self._families = families

    async def execute(self, *, academy_id: str, parent_id: str) -> tuple[str, list[FamilyNote]]:
        family_id = await resolve_family(self._families, academy_id, parent_id)
        return family_id, await self._notes.list_for_family(family_id)


class AddFamilyNote:
    def __init__(
        self,
        notes: FamilyNoteRepository,
        families: FamilyDirectory,
        *,
        clock: Callable[[], datetime] = utc_now_ms,
        new_id: Callable[[], str] = new_ulid,
    ) -> None:
        self._notes = notes
        self._families = families
        self._clock = clock
        self._new_id = new_id

    async def execute(
        self, *, academy_id: str, parent_id: str, body: str, actor: Actor
    ) -> FamilyNote:
        text = normalize_note_body(body)
        family_id = await resolve_family(self._families, academy_id, parent_id)
        now = self._clock()
        return await self._notes.add(
            FamilyNote(
                note_id=self._new_id(),
                academy_id=academy_id,
                parent_id=family_id,
                body=text,
                author_user_id=actor.user_id,
                created_at=now,
                updated_at=now,
            )
        )


class _NoteWriter:
    def __init__(
        self,
        notes: FamilyNoteRepository,
        families: FamilyDirectory,
        *,
        clock: Callable[[], datetime] = utc_now_ms,
    ) -> None:
        self._notes = notes
        self._families = families
        self._clock = clock

    async def _editable(
        self, academy_id: str, parent_id: str, note_id: str, actor: Actor
    ) -> tuple[str, FamilyNote]:
        family_id = await resolve_family(self._families, academy_id, parent_id)
        note = await self._notes.get(family_id, note_id)
        if note is None:
            raise FamilyNoteNotFound("note not found", note_id=note_id)
        if not can_edit_note(note, user_id=actor.user_id, roles=actor.roles):
            raise NoteEditForbidden(
                "Only the person who wrote this note, or the academy owner, can change it.",
                note_id=note_id,
            )
        return family_id, note


class EditFamilyNote(_NoteWriter):
    async def execute(
        self, *, academy_id: str, parent_id: str, note_id: str, body: str, actor: Actor
    ) -> FamilyNote:
        text = normalize_note_body(body)
        family_id, _note = await self._editable(academy_id, parent_id, note_id, actor)
        updated = await self._notes.update_body(
            family_id, note_id, body=text, updated_at=self._clock()
        )
        if updated is None:  # deleted between the read and the write
            raise FamilyNoteNotFound("note not found", note_id=note_id)
        return updated


class DeleteFamilyNote(_NoteWriter):
    async def execute(self, *, academy_id: str, parent_id: str, note_id: str, actor: Actor) -> None:
        family_id, _note = await self._editable(academy_id, parent_id, note_id, actor)
        deleted = await self._notes.soft_delete(
            family_id, note_id, deleted_by=actor.user_id, deleted_at=self._clock()
        )
        if not deleted:
            raise FamilyNoteNotFound("note not found", note_id=note_id)
