"""Family notes / follow-ups repositories on a real ``mongod`` (migration 0195 applied).

``real_db`` replays every migration, so the unique ``(academy_id, note_id)``
and ``(academy_id, follow_up_id)`` indexes are the production ones. Checks:
academy B can neither read nor change academy A's rows even by exact id, a
duplicate id is rejected by the index (and is fine in another academy),
soft-deleted notes vanish from reads, the queue windows and sorts, and the
queue lookups are served by their 0195 indexes. Skipped without a ``mongod``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from backend.v2.contexts.crm.domain.errors import DuplicateCrmRecordId
from backend.v2.contexts.crm.domain.family_notes import FamilyFollowUp, FamilyNote
from backend.v2.contexts.crm.infrastructure.mongo_family_notes_repo import (
    MongoFamilyFollowUpRepository,
    MongoFamilyNoteRepository,
)
from backend.v2.shared.tenancy import tenant_scope

A = "acad-notes-a"
B = "acad-notes-b"
NOW = datetime(2026, 9, 23, 15, 0, tzinfo=UTC)
TODAY = date(2026, 9, 23)


def _note(note_id: str, parent_id: str = "p-1", *, at: datetime = NOW) -> FamilyNote:
    return FamilyNote(
        note_id=note_id,
        academy_id=B,  # forged: the repository must stamp the tenant instead
        parent_id=parent_id,
        body=f"Note {note_id}",
        author_user_id="u-1",
        created_at=at,
        updated_at=at,
    )


def _fu(
    follow_up_id: str, due_on: date, *, assignee: str = "u-1", parent_id: str = "p-1"
) -> FamilyFollowUp:
    return FamilyFollowUp(
        follow_up_id=follow_up_id,
        academy_id=B,
        parent_id=parent_id,
        title=f"Follow up {follow_up_id}",
        due_on=due_on,
        assignee_user_id=assignee,
        created_by="u-1",
        created_at=NOW,
        updated_at=NOW,
    )


async def test_notes_are_tenant_scoped_unique_and_soft_deleted(real_db: Any) -> None:
    with tenant_scope(A):
        repo = MongoFamilyNoteRepository(real_db)
        stored = await repo.add(_note("n-1"))
        await repo.add(_note("n-2", at=NOW + timedelta(minutes=1)))
        with pytest.raises(DuplicateCrmRecordId):
            await repo.add(_note("n-1"))
    assert stored.academy_id == A
    row = await real_db["family_notes"].find_one({"note_id": "n-1"})
    assert row["academy_id"] == A

    with tenant_scope(B):
        other = MongoFamilyNoteRepository(real_db)
        assert await other.get("p-1", "n-1") is None
        assert await other.list_for_family("p-1") == []
        assert await other.update_body("p-1", "n-1", body="hijack", updated_at=NOW) is None
        assert await other.soft_delete("p-1", "n-1", deleted_by="u-b", deleted_at=NOW) is False
        # The same id is free in another academy: uniqueness is per academy.
        await other.add(_note("n-1"))

    with tenant_scope(A):
        repo = MongoFamilyNoteRepository(real_db)
        assert (await repo.get("p-1", "n-1")).body == "Note n-1"  # type: ignore[union-attr]
        assert await repo.get("p-2", "n-1") is None  # wrong family
        assert [n.note_id for n in await repo.list_for_family("p-1")] == ["n-2", "n-1"]
        edited = await repo.update_body(
            "p-1", "n-1", body="Edited", updated_at=NOW + timedelta(hours=1)
        )
        assert edited is not None and edited.body == "Edited"
        assert await repo.soft_delete("p-1", "n-1", deleted_by="u-1", deleted_at=NOW)
        assert await repo.get("p-1", "n-1") is None
        assert await repo.update_body("p-1", "n-1", body="x", updated_at=NOW) is None
        assert [n.note_id for n in await repo.list_for_family("p-1")] == ["n-2"]
    kept = await real_db["family_notes"].find_one({"academy_id": A, "note_id": "n-1"})
    assert kept["deleted_by"] == "u-1" and kept["body"] == "Edited"


async def test_follow_ups_are_tenant_scoped_and_queue_windows_work(real_db: Any) -> None:
    with tenant_scope(A):
        repo = MongoFamilyFollowUpRepository(real_db)
        await repo.add(_fu("f-late", TODAY - timedelta(days=3)))
        await repo.add(_fu("f-today", TODAY))
        await repo.add(_fu("f-soon", TODAY + timedelta(days=2)))
        await repo.add(_fu("f-theirs", TODAY, assignee="u-2", parent_id="p-2"))
        with pytest.raises(DuplicateCrmRecordId):
            await repo.add(_fu("f-today", TODAY))
        done = await repo.update(
            "p-1", "f-late", changes={"status": "done", "done_at": NOW, "done_by": "u-1"}
        )
        assert done is not None and done.status == "done"
        moved = await repo.update("p-1", "f-soon", changes={"due_on": TODAY + timedelta(days=9)})
        assert moved is not None and moved.due_on == TODAY + timedelta(days=9)
        assert await repo.update("p-2", "f-today", changes={"status": "done"}) is None

        async def ids(**kwargs: Any) -> list[str]:
            status = kwargs.pop("status", "open")
            return [r.follow_up_id for r in await repo.list_by_status(status, **kwargs)]

        assert await ids(assignee_user_id="u-1") == ["f-today", "f-soon"]
        assert set(await ids(due_on=TODAY)) == {"f-today", "f-theirs"}
        assert await ids(assignee_user_id="u-1", due_after=TODAY) == ["f-soon"]
        assert await ids(assignee_user_id="u-1", due_before=TODAY) == []
        assert await ids(status="done") == ["f-late"]
        assert [r.follow_up_id for r in await repo.list_for_family("p-2")] == ["f-theirs"]

    row = await real_db["family_follow_ups"].find_one({"follow_up_id": "f-today"})
    assert row["due_on"] == TODAY.isoformat()
    assert row["academy_id"] == A

    with tenant_scope(B):
        other = MongoFamilyFollowUpRepository(real_db)
        assert await other.get("p-1", "f-today") is None
        assert await other.list_by_status("open") == []
        assert await other.update("p-1", "f-today", changes={"status": "done"}) is None
    with tenant_scope(A):
        still = await MongoFamilyFollowUpRepository(real_db).get("p-1", "f-today")
        assert still is not None and still.status == "open"


def _index_names(plan: dict[str, Any]) -> set[str]:
    found: set[str] = set()
    if plan.get("indexName"):
        found.add(plan["indexName"])
    for key in ("inputStage", "queryPlan"):
        if isinstance(plan.get(key), dict):
            found |= _index_names(plan[key])
    for child in plan.get("inputStages", []) or []:
        found |= _index_names(child)
    return found


@pytest.mark.parametrize(
    ("filter_", "sort", "index"),
    [
        (
            {"academy_id": A, "assignee_user_id": "u-1", "status": "open", "due_on": {"$lt": "x"}},
            {"due_on": 1, "created_at": 1},
            "family_follow_ups_academy_assignee_status_due",
        ),
        (
            {"academy_id": A, "status": "open", "due_on": "2026-09-23"},
            {"due_on": 1, "created_at": 1},
            "family_follow_ups_academy_status_due",
        ),
        (
            {"academy_id": A, "parent_id": "p-1"},
            {"created_at": -1},
            "family_follow_ups_academy_parent_created",
        ),
    ],
)
async def test_queue_lookups_use_their_indexes(
    real_db: Any, filter_: dict[str, Any], sort: dict[str, int], index: str
) -> None:
    explained = await real_db.command(
        "explain",
        {"find": "family_follow_ups", "filter": filter_, "sort": sort},
        verbosity="queryPlanner",
    )
    assert index in _index_names(explained["queryPlanner"]["winningPlan"])
