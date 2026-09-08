"""Coach note visibility (coach phone slice 3).

Progress notes and skill notes default to ``private``. An assistant-only
coach may write notes but never share them or change visibility
(``NoteShareForbidden``). After creation the author or a supervisor may flip
the flag; anyone else gets ``NoteNotFound``. Supervisors listing a session's
progress notes see every author.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.contexts.coaching.application.use_cases.session_notes import (
    CreateProgressNote,
    CreateProgressNoteCommand,
    ListProgressNotes,
    ProgressNote,
    SetProgressNoteVisibility,
    SetProgressNoteVisibilityCommand,
)
from backend.v2.contexts.coaching.application.use_cases.skill_notes import (
    CreateSkillNote,
    CreateSkillNoteCommand,
    SetSkillNoteVisibility,
    SetSkillNoteVisibilityCommand,
)
from backend.v2.contexts.coaching.domain.errors import (
    NoteNotFound,
    NoteShareForbidden,
    SessionNotAssigned,
)
from backend.v2.contexts.coaching.domain.models import CoachSkillNote
from backend.v2.contexts.coaching.infrastructure.mongo_session_notes_repo import (
    MongoCoachingNotesRepository,
)
from backend.v2.contexts.coaching.infrastructure.mongo_skill_note_repo import (
    MongoSkillNoteRepository,
)
from backend.v2.shared.tenancy import tenant_scope

SESSION = "s-1"
NOW = datetime(2026, 9, 5, 10, 0, tzinfo=UTC)


class _Notes:
    def __init__(self) -> None:
        self.notes: list[ProgressNote] = []

    async def add_progress_note(self, note: ProgressNote) -> None:
        self.notes.append(note)

    async def list_progress_notes(self, session_id: str, coach_id: str | None):
        return [
            n
            for n in self.notes
            if n.session_id == session_id and (coach_id is None or n.coach_id == coach_id)
        ]

    async def get_progress_note(self, session_id: str, note_id: str):
        return next(
            (n for n in self.notes if n.session_id == session_id and n.note_id == note_id), None
        )

    async def set_progress_note_visibility(self, session_id: str, note_id: str, visibility):
        note = await self.get_progress_note(session_id, note_id)
        if note is None:
            return None
        updated = note.model_copy(update={"visibility": visibility})
        self.notes = [updated if n is note else n for n in self.notes]
        return updated

    async def add_lesson_plan(self, plan) -> None:  # pragma: no cover - protocol filler
        raise NotImplementedError

    async def list_lesson_plans(self, session_id, coach_id):  # pragma: no cover
        raise NotImplementedError


class _Sessions:
    def __init__(self, assigned: dict[str, set[str]]) -> None:
        self._assigned = assigned

    async def is_coach_assigned(self, coach_id: str, session_id: str) -> bool:
        return session_id in self._assigned.get(coach_id, set())


class _Enrollments:
    async def is_active(self, session_id: str, student_id: str) -> bool:
        return True


def _note(note_id: str, coach_id: str, visibility: str = "private") -> ProgressNote:
    return ProgressNote(
        note_id=note_id,
        session_id=SESSION,
        student_id="st1",
        coach_id=coach_id,
        body="b",
        created_at=NOW,
        visibility=visibility,  # type: ignore[arg-type]
    )


def _progress_stack():
    notes = _Notes()
    sessions = _Sessions({"coach-1": {SESSION}, "asst-1": {SESSION}, "adm": {SESSION}})
    return notes, sessions


# --- progress notes: create ---------------------------------------------


async def test_progress_note_defaults_to_private() -> None:
    notes, sessions = _progress_stack()
    uc = CreateProgressNote(notes=notes, sessions=sessions, enrollments=_Enrollments())
    note = await uc.execute(
        CreateProgressNoteCommand(
            coach_id="coach-1", session_id=SESSION, student_id="st1", body="b"
        )
    )
    assert note.visibility == "private"
    assert notes.notes[0].visibility == "private"


async def test_lead_coach_can_create_a_shared_progress_note() -> None:
    notes, sessions = _progress_stack()
    uc = CreateProgressNote(notes=notes, sessions=sessions, enrollments=_Enrollments())
    note = await uc.execute(
        CreateProgressNoteCommand(
            coach_id="coach-1",
            session_id=SESSION,
            student_id="st1",
            body="b",
            visibility="shared",
        )
    )
    assert note.visibility == "shared"


async def test_assistant_share_on_create_is_refused_before_any_write() -> None:
    notes, sessions = _progress_stack()
    uc = CreateProgressNote(notes=notes, sessions=sessions, enrollments=_Enrollments())
    with pytest.raises(NoteShareForbidden):
        await uc.execute(
            CreateProgressNoteCommand(
                coach_id="asst-1",
                session_id=SESSION,
                student_id="st1",
                body="b",
                visibility="shared",
                is_assistant=True,
            )
        )
    assert notes.notes == []


async def test_assistant_private_note_is_accepted() -> None:
    notes, sessions = _progress_stack()
    uc = CreateProgressNote(notes=notes, sessions=sessions, enrollments=_Enrollments())
    note = await uc.execute(
        CreateProgressNoteCommand(
            coach_id="asst-1", session_id=SESSION, student_id="st1", body="b", is_assistant=True
        )
    )
    assert note.visibility == "private"


# --- progress notes: set visibility -------------------------------------


def _set_cmd(coach_id: str, note_id: str, visibility: str = "shared", **flags):
    return SetProgressNoteVisibilityCommand(
        coach_id=coach_id,
        session_id=SESSION,
        note_id=note_id,
        visibility=visibility,  # type: ignore[arg-type]
        **flags,
    )


async def test_author_flips_visibility_both_ways() -> None:
    notes, sessions = _progress_stack()
    notes.notes.append(_note("n1", "coach-1"))
    uc = SetProgressNoteVisibility(notes=notes, sessions=sessions)
    assert (await uc.execute(_set_cmd("coach-1", "n1", "shared"))).visibility == "shared"
    assert (await uc.execute(_set_cmd("coach-1", "n1", "private"))).visibility == "private"
    assert notes.notes[0].visibility == "private"


async def test_assistant_cannot_change_visibility_even_to_private() -> None:
    notes, sessions = _progress_stack()
    notes.notes.append(_note("n1", "asst-1", "shared"))
    uc = SetProgressNoteVisibility(notes=notes, sessions=sessions)
    with pytest.raises(NoteShareForbidden):
        await uc.execute(_set_cmd("asst-1", "n1", "private", is_assistant=True))
    assert notes.notes[0].visibility == "shared"


async def test_other_coach_gets_not_found_not_forbidden() -> None:
    notes, sessions = _progress_stack()
    notes.notes.append(_note("n1", "coach-2"))
    uc = SetProgressNoteVisibility(notes=notes, sessions=sessions)
    with pytest.raises(NoteNotFound):
        await uc.execute(_set_cmd("coach-1", "n1"))
    assert notes.notes[0].visibility == "private"


async def test_supervisor_may_change_any_authors_note() -> None:
    notes, sessions = _progress_stack()
    notes.notes.append(_note("n1", "coach-2"))
    uc = SetProgressNoteVisibility(notes=notes, sessions=sessions)
    updated = await uc.execute(_set_cmd("adm", "n1", is_supervisor=True))
    assert updated.visibility == "shared"
    assert updated.coach_id == "coach-2", "the author never changes"


async def test_unknown_note_is_not_found_even_for_supervisor() -> None:
    notes, sessions = _progress_stack()
    uc = SetProgressNoteVisibility(notes=notes, sessions=sessions)
    with pytest.raises(NoteNotFound):
        await uc.execute(_set_cmd("adm", "nope", is_supervisor=True))


async def test_unassigned_session_is_session_not_assigned() -> None:
    notes, sessions = _progress_stack()
    notes.notes.append(_note("n1", "coach-9"))
    uc = SetProgressNoteVisibility(notes=notes, sessions=sessions)
    with pytest.raises(SessionNotAssigned):
        await uc.execute(_set_cmd("coach-9", "n1"))


# --- progress notes: listing --------------------------------------------


async def test_listing_is_own_notes_unless_all_authors() -> None:
    notes, sessions = _progress_stack()
    notes.notes.extend([_note("n1", "coach-1"), _note("n2", "asst-1"), _note("n3", "coach-2")])
    uc = ListProgressNotes(notes=notes, sessions=sessions)
    assert [n.note_id for n in await uc.execute("coach-1", SESSION)] == ["n1"]
    assert [n.note_id for n in await uc.execute("adm", SESSION)] == []
    assert {n.note_id for n in await uc.execute("adm", SESSION, all_authors=True)} == {
        "n1",
        "n2",
        "n3",
    }


# --- skill notes ----------------------------------------------------------


class _SkillNotes:
    def __init__(self) -> None:
        self.saved: list[CoachSkillNote] = []

    async def save(self, note: CoachSkillNote) -> None:
        self.saved.append(note)

    async def list_for_student_skill(self, student_id: str, skill_id: str):
        return list(self.saved)

    async def get(self, student_id: str, note_id: str):
        return next(
            (n for n in self.saved if n.student_id == student_id and n.note_id == note_id), None
        )

    async def set_visibility(self, student_id: str, note_id: str, visibility):
        note = await self.get(student_id, note_id)
        if note is None:
            return None
        updated = note.model_copy(update={"visibility": visibility})
        self.saved = [updated if n is note else n for n in self.saved]
        return updated


def _skill_note(note_id: str, coach_id: str, visibility: str = "private") -> CoachSkillNote:
    return CoachSkillNote(
        note_id=note_id,
        academy_id="acad",
        student_id="st1",
        skill_id="sk1",
        coach_id=coach_id,
        body="b",
        created_at=NOW,
        visibility=visibility,  # type: ignore[arg-type]
    )


async def test_skill_note_defaults_to_private_and_shared_is_honoured_for_leads() -> None:
    repo = _SkillNotes()
    uc = CreateSkillNote(notes=repo)
    base = dict(student_id="st1", skill_id="sk1", body="b", coach_id="coach-1")
    default = await uc.execute(CreateSkillNoteCommand(**base), academy_id="acad")  # type: ignore[arg-type]
    shared = await uc.execute(
        CreateSkillNoteCommand(**base, visibility="shared"),  # type: ignore[arg-type]
        academy_id="acad",
    )
    assert default.visibility == "private"
    assert shared.visibility == "shared"


async def test_assistant_skill_note_share_is_refused() -> None:
    repo = _SkillNotes()
    uc = CreateSkillNote(notes=repo)
    with pytest.raises(NoteShareForbidden):
        await uc.execute(
            CreateSkillNoteCommand(
                student_id="st1",
                skill_id="sk1",
                body="b",
                coach_id="asst-1",
                visibility="shared",
                is_assistant=True,
            ),
            academy_id="acad",
        )
    assert repo.saved == []


async def test_skill_note_visibility_author_supervisor_and_stranger_rules() -> None:
    repo = _SkillNotes()
    repo.saved.append(_skill_note("n1", "coach-1"))
    uc = SetSkillNoteVisibility(notes=repo)

    def cmd(coach_id: str, note_id: str = "n1", **flags):
        return SetSkillNoteVisibilityCommand(
            student_id="st1", note_id=note_id, visibility="shared", coach_id=coach_id, **flags
        )

    with pytest.raises(NoteShareForbidden):
        await uc.execute(cmd("asst-1", is_assistant=True))
    with pytest.raises(NoteNotFound):
        await uc.execute(cmd("coach-2"))
    with pytest.raises(NoteNotFound):
        await uc.execute(cmd("adm", note_id="missing", is_supervisor=True))
    assert (await uc.execute(cmd("coach-1"))).visibility == "shared"
    assert (await uc.execute(cmd("adm", is_supervisor=True))).visibility == "shared"


# --- Mongo repositories: persistence + legacy read ------------------------


def _mongo_db():
    mongomock_motor = pytest.importorskip("mongomock_motor")
    return mongomock_motor.AsyncMongoMockClient()["notes-visibility"]


async def test_mongo_progress_note_repo_round_trips_visibility_and_reads_legacy_as_private():
    db = _mongo_db()
    repo = MongoCoachingNotesRepository(db)
    with tenant_scope("acad"):
        await repo.add_progress_note(_note("n1", "coach-1", "shared"))
        await db["progress_notes"].insert_one(
            {  # pre-0167 document: no visibility field at all
                "academy_id": "acad",
                "note_id": "legacy",
                "session_id": SESSION,
                "student_id": "st1",
                "coach_id": "coach-2",
                "body": "old",
                "created_at": NOW,
            }
        )
        await db["progress_notes"].insert_one(
            {  # another tenant's note with the same ids: never visible here
                "academy_id": "other",
                "note_id": "n1",
                "session_id": SESSION,
                "student_id": "st1",
                "coach_id": "coach-1",
                "body": "x",
                "created_at": NOW,
                "visibility": "shared",
            }
        )

        stored = await db["progress_notes"].find_one({"academy_id": "acad", "note_id": "n1"})
        assert stored is not None and stored["visibility"] == "shared"

        assert (await repo.get_progress_note(SESSION, "n1")).visibility == "shared"  # type: ignore[union-attr]
        legacy = await repo.get_progress_note(SESSION, "legacy")
        assert legacy is not None and legacy.visibility == "private"

        own = await repo.list_progress_notes(SESSION, "coach-1")
        assert [n.note_id for n in own] == ["n1"]
        everyone = await repo.list_progress_notes(SESSION, None)
        assert {n.note_id for n in everyone} == {"n1", "legacy"}

        flipped = await repo.set_progress_note_visibility(SESSION, "n1", "private")
        assert flipped is not None and flipped.visibility == "private"
        assert await repo.set_progress_note_visibility(SESSION, "nope", "shared") is None

    with tenant_scope("other"):
        # The other tenant's copy was not touched by the update above.
        theirs = await repo.get_progress_note(SESSION, "n1")
        assert theirs is not None and theirs.visibility == "shared"


async def test_mongo_skill_note_repo_round_trips_visibility_and_reads_legacy_as_private():
    db = _mongo_db()
    repo = MongoSkillNoteRepository(db)
    with tenant_scope("acad"):
        await repo.save(_skill_note("n1", "coach-1", "shared"))
        await db["coach_skill_notes"].insert_one(
            {
                "academy_id": "acad",
                "note_id": "legacy",
                "student_id": "st1",
                "skill_id": "sk1",
                "coach_id": "coach-1",
                "session_id": None,
                "body": "old",
                "created_at": NOW,
            }
        )
        stored = await db["coach_skill_notes"].find_one({"note_id": "n1"})
        assert stored is not None and stored["visibility"] == "shared"

        got = await repo.get("st1", "n1")
        assert got is not None and got.visibility == "shared"
        legacy = await repo.get("st1", "legacy")
        assert legacy is not None and legacy.visibility == "private"
        assert await repo.get("someone-else", "n1") is None

        flipped = await repo.set_visibility("st1", "n1", "private")
        assert flipped is not None and flipped.visibility == "private"
        assert await repo.set_visibility("st1", "nope", "shared") is None
        listed = await repo.list_for_student_skill("st1", "sk1")
        assert {(n.note_id, n.visibility) for n in listed} == {
            ("n1", "private"),
            ("legacy", "private"),
        }
