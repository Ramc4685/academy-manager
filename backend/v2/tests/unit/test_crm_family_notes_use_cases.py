"""Family notes and follow-ups use cases, over fakes that mirror the stores.

The fakes (``tests/fixtures/crm_family_fakes.py``) enforce the unique ids,
the tenant ContextVar and the ``parent_id`` filter the Mongo repositories do.
"""

from __future__ import annotations

import itertools
from datetime import UTC, date, datetime, timedelta

import pytest

from backend.v2.contexts.crm.application.use_cases.family_follow_ups import (
    AddFamilyFollowUp,
    FollowUpChanges,
    ListFamilyFollowUps,
    ListFollowUps,
    UpdateFamilyFollowUp,
    academy_today,
)
from backend.v2.contexts.crm.application.use_cases.family_notes import (
    Actor,
    AddFamilyNote,
    DeleteFamilyNote,
    EditFamilyNote,
    ListFamilyNotes,
)
from backend.v2.contexts.crm.domain.errors import (
    DuplicateCrmRecordId,
    FamilyFollowUpNotFound,
    FamilyNoteNotFound,
    FamilyNotFound,
    InvalidFamilyNote,
    InvalidFollowUp,
    NoteEditForbidden,
)
from backend.v2.shared.tenancy import tenant_scope
from backend.v2.tests.fixtures.crm_family_fakes import (
    FakeFamilyDirectory,
    FakeFamilyFollowUpRepository,
    FakeFamilyNoteRepository,
    FakeStaffDirectory,
    fixed_timezone,
)

A = "acad-a"
B = "acad-b"
# 2026-09-24 03:00 UTC is still 2026-09-23 in Chicago.
NOW = datetime(2026, 9, 24, 3, 0, tzinfo=UTC)
TODAY = date(2026, 9, 23)
AUTHOR = Actor(user_id="u-author", roles=("admin",))
OTHER_ADMIN = Actor(user_id="u-other", roles=("admin",))
OWNER = Actor(user_id="u-owner", roles=("admin", "owner"))


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def world():
    families = FakeFamilyDirectory()
    families.add(A, "p-1", "Testparent One", "fb-p-1")
    families.add(A, "p-2", "Testparent Two")
    families.add(B, "p-b", "Testparent Bee")
    staff = FakeStaffDirectory()
    for user in ("u-author", "u-other", "u-owner"):
        staff.add(A, user)
    staff.add(B, "u-b")
    ids = (f"id-{n}" for n in itertools.count(1))
    clock = Clock()
    notes = FakeFamilyNoteRepository()
    follow_ups = FakeFamilyFollowUpRepository()
    tz = fixed_timezone("America/Chicago")

    class W:
        pass

    w = W()
    w.families, w.staff, w.clock, w.notes, w.follow_ups = families, staff, clock, notes, follow_ups
    w.add_note = AddFamilyNote(notes, families, clock=clock, new_id=lambda: next(ids))
    w.list_notes = ListFamilyNotes(notes, families)
    w.edit_note = EditFamilyNote(notes, families, clock=clock)
    w.delete_note = DeleteFamilyNote(notes, families, clock=clock)
    args = (follow_ups, families, staff, tz)
    w.add_fu = AddFamilyFollowUp(*args, clock=clock, new_id=lambda: next(ids))
    w.list_fu = ListFamilyFollowUps(*args, clock=clock)
    w.update_fu = UpdateFamilyFollowUp(*args, clock=clock)
    w.queue = ListFollowUps(*args, clock=clock)
    return w


# ------------------------------------------------------------------ notes


async def test_add_and_list_notes_newest_first_on_the_canonical_family(world) -> None:
    with tenant_scope(A):
        first = await world.add_note.execute(
            academy_id=A, parent_id="fb-p-1", body=" Asked about fees ", actor=AUTHOR
        )
        world.clock.now = NOW + timedelta(minutes=5)
        second = await world.add_note.execute(
            academy_id=A, parent_id="p-1", body="Paid by cash", actor=OTHER_ADMIN
        )
        family_id, notes = await world.list_notes.execute(academy_id=A, parent_id="fb-p-1")

    assert first.parent_id == "p-1"  # the alias resolved to the canonical id
    assert first.body == "Asked about fees"
    assert first.academy_id == A
    assert family_id == "p-1"
    assert [n.note_id for n in notes] == [second.note_id, first.note_id]


async def test_a_family_of_another_academy_is_not_found(world) -> None:
    with tenant_scope(A):
        with pytest.raises(FamilyNotFound):
            await world.add_note.execute(academy_id=A, parent_id="p-b", body="x", actor=AUTHOR)
        with pytest.raises(FamilyNotFound):
            await world.list_notes.execute(academy_id=A, parent_id="p-b")
        with pytest.raises(FamilyNotFound):
            await world.list_fu.execute(academy_id=A, parent_id="nobody")


async def test_empty_note_is_rejected_before_any_write(world) -> None:
    with tenant_scope(A), pytest.raises(InvalidFamilyNote):
        await world.add_note.execute(academy_id=A, parent_id="p-1", body="  ", actor=AUTHOR)
    assert world.notes.rows == {}


async def test_only_author_or_owner_edits_and_deletes(world) -> None:
    with tenant_scope(A):
        note = await world.add_note.execute(
            academy_id=A, parent_id="p-1", body="Original", actor=AUTHOR
        )
        with pytest.raises(NoteEditForbidden):
            await world.edit_note.execute(
                academy_id=A, parent_id="p-1", note_id=note.note_id, body="x", actor=OTHER_ADMIN
            )
        with pytest.raises(NoteEditForbidden):
            await world.delete_note.execute(
                academy_id=A, parent_id="p-1", note_id=note.note_id, actor=OTHER_ADMIN
            )
        world.clock.now = NOW + timedelta(minutes=1)
        edited = await world.edit_note.execute(
            academy_id=A, parent_id="p-1", note_id=note.note_id, body="Edited", actor=AUTHOR
        )
        assert edited.body == "Edited"
        assert edited.updated_at > edited.created_at
        await world.edit_note.execute(
            academy_id=A, parent_id="p-1", note_id=note.note_id, body="By owner", actor=OWNER
        )
        await world.delete_note.execute(
            academy_id=A, parent_id="p-1", note_id=note.note_id, actor=OWNER
        )
        _, notes = await world.list_notes.execute(academy_id=A, parent_id="p-1")
        assert notes == []
        with pytest.raises(FamilyNoteNotFound):
            await world.delete_note.execute(
                academy_id=A, parent_id="p-1", note_id=note.note_id, actor=OWNER
            )

    stored = world.notes.rows[(A, note.note_id)]
    assert stored.deleted_by == "u-owner"  # soft delete: the row is kept
    assert stored.body == "By owner"


async def test_a_note_is_only_found_on_its_own_family(world) -> None:
    with tenant_scope(A):
        note = await world.add_note.execute(
            academy_id=A, parent_id="p-1", body="On family one", actor=AUTHOR
        )
        with pytest.raises(FamilyNoteNotFound):
            await world.edit_note.execute(
                academy_id=A, parent_id="p-2", note_id=note.note_id, body="x", actor=AUTHOR
            )


async def test_duplicate_note_id_is_rejected_like_the_unique_index(world) -> None:
    add = AddFamilyNote(world.notes, world.families, clock=world.clock, new_id=lambda: "same")
    with tenant_scope(A):
        await add.execute(academy_id=A, parent_id="p-1", body="one", actor=AUTHOR)
        with pytest.raises(DuplicateCrmRecordId):
            await add.execute(academy_id=A, parent_id="p-1", body="two", actor=AUTHOR)
    with tenant_scope(B):  # unique per academy, not global
        await add.execute(academy_id=B, parent_id="p-b", body="bee", actor=AUTHOR)


# ------------------------------------------------------------------ follow-ups


async def _add_fu(world, due: date, assignee: str = "u-author", parent: str = "p-1"):
    return await world.add_fu.execute(
        academy_id=A,
        parent_id=parent,
        title=f"Call {due.isoformat()}",
        due_on=due,
        assignee_user_id=assignee,
        actor=AUTHOR,
    )


async def test_add_follow_up_validates_assignee_title_and_date(world) -> None:
    with tenant_scope(A):
        with pytest.raises(InvalidFollowUp) as exc:
            await _add_fu(world, TODAY, assignee="u-b")  # staff of academy B only
        assert exc.value.details["field"] == "assignee"
        with pytest.raises(InvalidFollowUp):
            await world.add_fu.execute(
                academy_id=A,
                parent_id="p-1",
                title=" ",
                due_on=TODAY,
                assignee_user_id="u-author",
                actor=AUTHOR,
            )
        with pytest.raises(InvalidFollowUp):
            await _add_fu(world, TODAY + timedelta(days=5 * 365))
        row = await _add_fu(world, TODAY)
    assert row.status == "open"
    assert row.created_by == "u-author"
    assert row.parent_id == "p-1"


async def test_mark_done_and_reopen(world) -> None:
    with tenant_scope(A):
        row = await _add_fu(world, TODAY)
        world.clock.now = NOW + timedelta(hours=1)
        done = await world.update_fu.execute(
            academy_id=A,
            parent_id="p-1",
            follow_up_id=row.follow_up_id,
            changes=FollowUpChanges(status="done"),
            actor=OTHER_ADMIN,
        )
        assert done.status == "done"
        assert done.done_by == "u-other"
        assert done.done_at == NOW + timedelta(hours=1)
        reopened = await world.update_fu.execute(
            academy_id=A,
            parent_id="p-1",
            follow_up_id=row.follow_up_id,
            changes=FollowUpChanges(status="open", title="Call again", due_on=TODAY),
            actor=AUTHOR,
        )
        assert reopened.status == "open"
        assert reopened.done_at is None and reopened.done_by is None
        assert reopened.title == "Call again"
        unchanged = await world.update_fu.execute(
            academy_id=A,
            parent_id="p-1",
            follow_up_id=row.follow_up_id,
            changes=FollowUpChanges(),
            actor=AUTHOR,
        )
        assert unchanged == reopened
        with pytest.raises(FamilyFollowUpNotFound):
            await world.update_fu.execute(
                academy_id=A,
                parent_id="p-2",
                follow_up_id=row.follow_up_id,
                changes=FollowUpChanges(status="done"),
                actor=AUTHOR,
            )
        with pytest.raises(InvalidFollowUp):
            await world.update_fu.execute(
                academy_id=A,
                parent_id="p-1",
                follow_up_id=row.follow_up_id,
                changes=FollowUpChanges(assignee_user_id="stranger"),
                actor=AUTHOR,
            )


async def test_today_is_the_academy_local_date() -> None:
    assert await academy_today(fixed_timezone("America/Chicago"), A, NOW) == TODAY
    assert await academy_today(fixed_timezone(None), A, NOW) == date(2026, 9, 24)
    assert await academy_today(fixed_timezone("Not/AZone"), A, NOW) == date(2026, 9, 24)


async def test_queue_buckets_mine_and_all(world) -> None:
    with tenant_scope(A):
        late = await _add_fu(world, TODAY - timedelta(days=2))
        now_ = await _add_fu(world, TODAY)
        soon = await _add_fu(world, TODAY + timedelta(days=3))
        theirs = await _add_fu(world, TODAY, assignee="u-other", parent="p-2")
        finished = await _add_fu(world, TODAY - timedelta(days=1))
        await world.update_fu.execute(
            academy_id=A,
            parent_id="p-1",
            follow_up_id=finished.follow_up_id,
            changes=FollowUpChanges(status="done"),
            actor=AUTHOR,
        )

        async def ids(assignee: str | None, bucket: str | None) -> list[str]:
            q = await world.queue.execute(academy_id=A, assignee_user_id=assignee, bucket=bucket)
            assert q.today == TODAY
            return [i.follow_up.follow_up_id for i in q.items]

        assert await ids("u-author", "overdue") == [late.follow_up_id]
        assert await ids("u-author", "today") == [now_.follow_up_id]
        assert await ids("u-author", "upcoming") == [soon.follow_up_id]
        assert await ids("u-author", "done") == [finished.follow_up_id]
        assert await ids("u-author", None) == [
            late.follow_up_id,
            now_.follow_up_id,
            soon.follow_up_id,
        ]
        assert set(await ids(None, "today")) == {now_.follow_up_id, theirs.follow_up_id}
        with pytest.raises(InvalidFollowUp):
            await ids(None, "someday")

        queue = await world.queue.execute(academy_id=A, assignee_user_id=None, bucket="today")
        assert {i.family_name for i in queue.items} == {"Testparent One", "Testparent Two"}

    with tenant_scope(B):  # academy B sees none of A's follow-ups
        q = await world.queue.execute(academy_id=B, assignee_user_id=None, bucket=None)
        assert q.items == []


async def test_queue_survives_family_names_being_unavailable(world) -> None:
    with tenant_scope(A):
        await _add_fu(world, TODAY)
        world.families.names_error = RuntimeError("index down")
        q = await world.queue.execute(academy_id=A, assignee_user_id=None, bucket="today")
    assert len(q.items) == 1
    assert q.items[0].family_name is None
