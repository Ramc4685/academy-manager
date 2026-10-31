"""In-memory stand-ins for the family notes / follow-ups stores and ports.

They mirror the Mongo repositories' semantics, not a permissive dict:

* the academy comes from the tenant ContextVar (``current_academy_id()``) on
  every read and write, never from the object passed in;
* ``(academy_id, note_id)`` / ``(academy_id, follow_up_id)`` are unique, so a
  duplicate id raises ``DuplicateCrmRecordId`` the way the unique index does;
* every read filters ``parent_id``; soft-deleted notes are invisible;
* ordering matches the repository sorts.

``test_crm_family_notes_real_mongo.py`` runs the same scenarios against the
real repositories on a real ``mongod`` so the two cannot drift silently.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime

from backend.v2.contexts.crm.domain.errors import DuplicateCrmRecordId
from backend.v2.contexts.crm.domain.family_notes import (
    FamilyFollowUp,
    FamilyNote,
    FollowUpStatus,
)
from backend.v2.shared.tenancy import current_academy_id


class FakeFamilyNoteRepository:
    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], FamilyNote] = {}

    async def add(self, note: FamilyNote) -> FamilyNote:
        academy = current_academy_id()
        key = (academy, note.note_id)
        if key in self.rows:
            raise DuplicateCrmRecordId("note id already exists", note_id=note.note_id)
        stored = note.model_copy(update={"academy_id": academy})
        self.rows[key] = stored
        return stored

    def _live(self, parent_id: str, note_id: str) -> FamilyNote | None:
        row = self.rows.get((current_academy_id(), note_id))
        if row is None or row.parent_id != parent_id or row.deleted_at is not None:
            return None
        return row

    async def get(self, parent_id: str, note_id: str) -> FamilyNote | None:
        return self._live(parent_id, note_id)

    async def list_for_family(self, parent_id: str, *, limit: int = 200) -> list[FamilyNote]:
        academy = current_academy_id()
        rows = [
            r
            for (a, _), r in self.rows.items()
            if a == academy and r.parent_id == parent_id and r.deleted_at is None
        ]
        return sorted(rows, key=lambda r: r.created_at, reverse=True)[:limit]

    async def update_body(
        self, parent_id: str, note_id: str, *, body: str, updated_at: datetime
    ) -> FamilyNote | None:
        row = self._live(parent_id, note_id)
        if row is None:
            return None
        new = row.model_copy(update={"body": body, "updated_at": updated_at})
        self.rows[(current_academy_id(), note_id)] = new
        return new

    async def soft_delete(
        self, parent_id: str, note_id: str, *, deleted_by: str, deleted_at: datetime
    ) -> bool:
        row = self._live(parent_id, note_id)
        if row is None:
            return False
        self.rows[(current_academy_id(), note_id)] = row.model_copy(
            update={"deleted_at": deleted_at, "deleted_by": deleted_by}
        )
        return True


class FakeFamilyFollowUpRepository:
    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], FamilyFollowUp] = {}

    async def add(self, follow_up: FamilyFollowUp) -> FamilyFollowUp:
        academy = current_academy_id()
        key = (academy, follow_up.follow_up_id)
        if key in self.rows:
            raise DuplicateCrmRecordId(
                "follow-up id already exists", follow_up_id=follow_up.follow_up_id
            )
        stored = follow_up.model_copy(update={"academy_id": academy})
        self.rows[key] = stored
        return stored

    async def get(self, parent_id: str, follow_up_id: str) -> FamilyFollowUp | None:
        row = self.rows.get((current_academy_id(), follow_up_id))
        return row if row is not None and row.parent_id == parent_id else None

    async def list_for_family(self, parent_id: str, *, limit: int = 200) -> list[FamilyFollowUp]:
        academy = current_academy_id()
        rows = [r for (a, _), r in self.rows.items() if a == academy and r.parent_id == parent_id]
        return sorted(rows, key=lambda r: r.created_at, reverse=True)[:limit]

    async def update(
        self, parent_id: str, follow_up_id: str, *, changes: Mapping[str, object]
    ) -> FamilyFollowUp | None:
        row = await self.get(parent_id, follow_up_id)
        if row is None:
            return None
        new = row.model_copy(update=dict(changes))
        self.rows[(current_academy_id(), follow_up_id)] = new
        return new

    async def list_by_status(
        self,
        status: FollowUpStatus,
        *,
        assignee_user_id: str | None = None,
        due_before: date | None = None,
        due_on: date | None = None,
        due_after: date | None = None,
        limit: int = 200,
    ) -> list[FamilyFollowUp]:
        academy = current_academy_id()
        rows = [
            r
            for (a, _), r in self.rows.items()
            if a == academy
            and r.status == status
            and (assignee_user_id is None or r.assignee_user_id == assignee_user_id)
            and (due_before is None or r.due_on < due_before)
            and (due_on is None or r.due_on == due_on)
            and (due_after is None or r.due_on > due_after)
        ]
        if status == "done":
            rows.sort(key=lambda r: r.done_at or r.created_at, reverse=True)
        else:
            rows.sort(key=lambda r: (r.due_on, r.created_at))
        return rows[:limit]


@dataclass(frozen=True)
class FakeFamily:
    family_id: str
    parent_name: str | None


class FakeFamilyDirectory:
    """academy_id -> {alias: canonical}; names per academy."""

    def __init__(self) -> None:
        self.aliases: dict[str, dict[str, str]] = {}
        self.names_by_academy: dict[str, dict[str, str | None]] = {}
        self.names_error: Exception | None = None

    def add(self, academy_id: str, family_id: str, name: str | None, *aliases: str) -> None:
        self.aliases.setdefault(academy_id, {})[family_id] = family_id
        for alias in aliases:
            self.aliases[academy_id][alias] = family_id
        self.names_by_academy.setdefault(academy_id, {})[family_id] = name

    async def find(self, academy_id: str, family_id: str) -> FakeFamily | None:
        canonical = self.aliases.get(academy_id, {}).get(family_id)
        if canonical is None:
            return None
        return FakeFamily(canonical, self.names_by_academy[academy_id][canonical])

    async def names(self, academy_id: str) -> Mapping[str, str | None]:
        if self.names_error:
            raise self.names_error
        return dict(self.names_by_academy.get(academy_id, {}))


class FakeStaffDirectory:
    def __init__(self) -> None:
        self.staff: set[tuple[str, str]] = set()

    def add(self, academy_id: str, user_id: str) -> None:
        self.staff.add((academy_id, user_id))

    async def is_staff(self, academy_id: str, user_id: str) -> bool:
        return (academy_id, user_id) in self.staff


def fixed_timezone(name: str | None):
    async def lookup(_academy_id: str) -> str | None:
        return name

    return lookup
