"""D-15: shared skill notes reach the parent's Progress page (S53).

The real coach note use cases and the parent feed as ``main.py`` wires them,
over the mongomock ``db`` (a real mongod when ``CONTRACT_TESTS_MONGO_URL`` is
set). Synthetic names only.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from backend.v2.composition.parent_coach_notes import compose_parent_coach_notes
from backend.v2.contexts.coaching.application.use_cases.skill_notes import (
    CreateSkillNote,
    CreateSkillNoteCommand,
    SetSkillNoteVisibility,
    SetSkillNoteVisibilityCommand,
)
from backend.v2.contexts.coaching.domain.errors import NoteShareForbidden
from backend.v2.contexts.coaching.infrastructure.mongo_skill_note_repo import (
    MongoSkillNoteRepository,
)
from backend.v2.interfaces.parent.deps import get_parent_use_cases
from backend.v2.interfaces.parent.progress_skill_routes import router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.tenancy import tenant_scope

pytestmark = pytest.mark.asyncio

ACADEMY = "acad-d15"
KID = "stu-kid"
OTHER_KID = "stu-other"


async def _skill(db: Any) -> None:
    await db["skills"].insert_one(
        {
            "academy_id": ACADEMY,
            "skill_id": "sk-grip",
            "level_id": "lv-1",
            "program_id": "prog-1",
            "sequence": 1,
            "name": "Forehand grip",
            "is_active": True,
            "created_at": datetime(2026, 9, 1, tzinfo=UTC),
            "updated_at": datetime(2026, 9, 1, tzinfo=UTC),
        }
    )


async def _note(db: Any, student_id: str, body: str, visibility: str = "shared") -> str:
    note = await CreateSkillNote(notes=MongoSkillNoteRepository(db)).execute(
        CreateSkillNoteCommand(
            student_id=student_id,
            skill_id="sk-grip",
            body=body,
            coach_id="coach-1",
            visibility=visibility,  # type: ignore[arg-type]
        ),
        academy_id=ACADEMY,
    )
    return note.note_id


async def test_feed_shows_only_notes_shared_after_the_cutoff(db: Any) -> None:
    with tenant_scope(ACADEMY):
        await _skill(db)
        await _note(db, KID, "Lovely grip today")
        private_id = await _note(db, KID, "Coach-only thought", visibility="private")
        await _note(db, OTHER_KID, "Another family's note")
        # Ticked "shared" before parents could see skill notes: no shared_at.
        await db["coach_skill_notes"].insert_one(
            {
                "academy_id": ACADEMY,
                "note_id": "legacy-1",
                "student_id": KID,
                "skill_id": "sk-grip",
                "coach_id": "coach-1",
                "body": "Old shared note",
                "created_at": datetime(2026, 9, 1, tzinfo=UTC),
                "visibility": "shared",
            }
        )
        feed = compose_parent_coach_notes(db)

        notes = await feed.execute(KID)
        assert [(n.body, n.skill_name) for n in notes] == [("Lovely grip today", "Forehand grip")]

        visibility = SetSkillNoteVisibility(notes=MongoSkillNoteRepository(db))
        await visibility.execute(
            SetSkillNoteVisibilityCommand(
                student_id=KID, note_id=private_id, visibility="shared", coach_id="coach-1"
            )
        )
        assert {n.body for n in await feed.execute(KID)} == {
            "Lovely grip today",
            "Coach-only thought",
        }
        await visibility.execute(
            SetSkillNoteVisibilityCommand(
                student_id=KID, note_id=private_id, visibility="private", coach_id="coach-1"
            )
        )
        assert [n.body for n in await feed.execute(KID)] == ["Lovely grip today"]


async def test_assistant_still_cannot_share(db: Any) -> None:
    with tenant_scope(ACADEMY), pytest.raises(NoteShareForbidden):
        await CreateSkillNote(notes=MongoSkillNoteRepository(db)).execute(
            CreateSkillNoteCommand(
                student_id=KID,
                skill_id="sk-grip",
                body="x",
                coach_id="asst-1",
                visibility="shared",
                is_assistant=True,
            ),
            academy_id=ACADEMY,
        )


def _app(db: Any) -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api/v2/parent")

    async def children(parent_id: str) -> list[dict[str, str]]:
        return [{"student_id": KID}] if parent_id == "parent-1" else []

    app.dependency_overrides[get_auth_claims] = lambda: AuthClaims(
        user_id="parent-1", email="parent@example.com", academy_id=ACADEMY, roles=("parent",)
    )
    app.dependency_overrides[get_parent_use_cases] = lambda: SimpleNamespace(
        list_children_for_parent=children
    )
    app.state.parent_coach_notes = compose_parent_coach_notes(db)
    return app


async def test_parent_route_reads_own_child_and_404s_another_family(db: Any) -> None:
    with tenant_scope(ACADEMY):
        await _skill(db)
        await _note(db, KID, "Lovely grip today")
        await _note(db, OTHER_KID, "Another family's note")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=_app(db)), base_url="http://test"
        ) as client:
            own = await client.get(f"/api/v2/parent/students/{KID}/coach-notes")
            other = await client.get(f"/api/v2/parent/students/{OTHER_KID}/coach-notes")

    assert own.status_code == 200, own.text
    body = own.json()["notes"]
    assert [n["body"] for n in body] == ["Lovely grip today"]
    assert "coach_id" not in body[0]
    assert other.status_code == 404
