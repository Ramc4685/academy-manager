"""Interface tests for GET /parent/messages and POST /parent/messages/{id}/read."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.interfaces.parent.deps import get_parent_use_cases
from backend.v2.interfaces.parent.router import router as parent_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.comms import Message
from backend.v2.shared.http import register_exception_handlers


def _claims(role: str = "parent", user_id: str = "p1") -> AuthClaims:
    return AuthClaims(
        user_id=user_id,
        email=f"{role}@example.com",
        academy_id="acad",
        roles=(role,),  # type: ignore[arg-type]
    )


def _message(**overrides) -> Message:
    base = dict(
        message_id="m-1",
        academy_id="acad",
        kind="dm",
        sender_id="adm",
        sender_persona="admin",
        recipient_id="p1",
        body="Please sign the waiver",
        created_at=datetime(2026, 5, 16, 8, 0, tzinfo=UTC),
        read_by=[],
    )
    base.update(overrides)
    return Message(**base)


@dataclass
class _FakeMessageRepo:
    rows: dict[str, Message] = field(default_factory=dict)

    def _visible(self, m: Message, recipient_id: str, visible_session_ids) -> bool:
        """Mirrors MongoMessageRepository._visibility_filter (#614)."""
        if m.deleted_at is not None:
            return False
        if m.recipient_id == recipient_id:
            return True
        if m.kind != "announcement":
            return False
        if m.scope_type != "session":
            return True
        return m.scope_id in set(visible_session_ids)

    async def for_recipient(self, recipient_id: str, *, visible_session_ids) -> list[Message]:
        return sorted(
            (m for m in self.rows.values() if self._visible(m, recipient_id, visible_session_ids)),
            key=lambda m: m.created_at,
            reverse=True,
        )

    async def mark_read(self, message_id: str, user_id: str, *, visible_session_ids) -> None:
        # Mirrors MongoMessageRepository.mark_read: only messages the caller
        # can actually read are markable.
        m = self.rows.get(message_id)
        if m is None or not self._visible(m, user_id, visible_session_ids):
            return
        if user_id not in m.read_by:
            m.read_by.append(user_id)


class _FakeParentUseCases:
    """Mirrors composition/parent.py: the closure resolves the parent's live
    active-enrollment session ids and hands them to the repository. The routes
    themselves take no session argument, which is why the scoping has to be
    tested through this shape rather than against the repo directly."""

    def __init__(self, repo: _FakeMessageRepo, visible_session_ids=()) -> None:
        self._repo = repo
        self._visible = tuple(visible_session_ids)

    async def list_messages(self, parent_id: str) -> list[Message]:
        return await self._repo.for_recipient(parent_id, visible_session_ids=self._visible)

    async def mark_message_read(self, message_id: str, user_id: str) -> None:
        await self._repo.mark_read(message_id, user_id, visible_session_ids=self._visible)


@contextmanager
def _make_client(
    repo: _FakeMessageRepo | None = None,
    role: str = "parent",
    user_id: str = "p1",
    visible_session_ids=(),
) -> Iterator[TestClient]:
    repo = repo if repo is not None else _FakeMessageRepo()
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(parent_router, prefix="/api/v2")
    app.dependency_overrides[get_auth_claims] = lambda: _claims(role, user_id)
    app.dependency_overrides[get_parent_use_cases] = lambda: _FakeParentUseCases(
        repo, visible_session_ids
    )
    with TestClient(app) as client:
        client.messages_repo = repo  # type: ignore[attr-defined]
        yield client


@contextmanager
def _anon_client() -> Iterator[TestClient]:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(parent_router, prefix="/api/v2")
    app.dependency_overrides[get_parent_use_cases] = lambda: _FakeParentUseCases(_FakeMessageRepo())
    with TestClient(app) as client:
        yield client


def test_parent_sees_own_dms_and_announcements():
    repo = _FakeMessageRepo(
        rows={
            "m-1": _message(message_id="m-1"),
            "m-2": _message(
                message_id="m-2", kind="announcement", recipient_id=None, body="Tournament"
            ),
            "m-3": _message(message_id="m-3", recipient_id="p2", body="Not for p1"),
        }
    )
    with _make_client(repo) as client:
        r = client.get("/api/v2/parent/messages")

    assert r.status_code == 200, r.text
    bodies = {m["body"] for m in r.json()["messages"]}
    assert bodies == {"Please sign the waiver", "Tournament"}


def test_parent_message_read_flag_reflects_read_by():
    repo = _FakeMessageRepo(
        rows={
            "m-1": _message(message_id="m-1", read_by=["p1"]),
            "m-2": _message(message_id="m-2", read_by=[]),
        }
    )
    with _make_client(repo) as client:
        r = client.get("/api/v2/parent/messages")

    assert r.status_code == 200, r.text
    by_id = {m["message_id"]: m["read"] for m in r.json()["messages"]}
    assert by_id == {"m-1": True, "m-2": False}


def test_parent_mark_message_read_is_idempotent():
    repo = _FakeMessageRepo(rows={"m-1": _message(message_id="m-1", read_by=[])})
    with _make_client(repo) as client:
        r1 = client.post("/api/v2/parent/messages/m-1/read")
        assert r1.status_code == 200, r1.text
        r2 = client.post("/api/v2/parent/messages/m-1/read")
        assert r2.status_code == 200, r2.text

    assert repo.rows["m-1"].read_by == ["p1"]


def test_parent_cannot_see_other_parents_dm():
    repo = _FakeMessageRepo(
        rows={"m-1": _message(message_id="m-1", recipient_id="p2", body="Only for p2")}
    )
    with _make_client(repo) as client:
        r = client.get("/api/v2/parent/messages")

    assert r.status_code == 200, r.text
    assert r.json()["messages"] == []


def test_parent_mark_read_on_unreadable_dm_is_a_noop():
    """A DM addressed to another parent cannot be stamped as read."""
    repo = _FakeMessageRepo(
        rows={"m-1": _message(message_id="m-1", recipient_id="p2", body="Only for p2")}
    )
    with _make_client(repo) as client:
        r = client.post("/api/v2/parent/messages/m-1/read")

    assert r.status_code == 200, r.text
    assert repo.rows["m-1"].read_by == []


def test_parent_can_mark_announcement_read():
    repo = _FakeMessageRepo(
        rows={
            "m-1": _message(
                message_id="m-1", kind="announcement", recipient_id=None, body="All hands"
            )
        }
    )
    with _make_client(repo) as client:
        r = client.post("/api/v2/parent/messages/m-1/read")

    assert r.status_code == 200, r.text
    assert repo.rows["m-1"].read_by == ["p1"]


def test_parent_messages_wrong_persona_404():
    with _make_client(role="coach", user_id="c1") as client:
        r = client.get("/api/v2/parent/messages")
    assert r.status_code == 404


def test_parent_mark_read_wrong_persona_404():
    with _make_client(role="admin", user_id="adm") as client:
        r = client.post("/api/v2/parent/messages/m-1/read")
    assert r.status_code == 404


def test_parent_messages_requires_auth():
    with _anon_client() as client:
        r = client.get("/api/v2/parent/messages")
    assert r.status_code == 401


# --- #614 session announcement scoping ---------------------------------


def _session_announcement(**overrides) -> Message:
    return _message(
        message_id="ann-1",
        kind="announcement",
        recipient_id=None,
        body="Court 3 is closed tonight",
        scope_type="session",
        scope_id="sess-1",
        scope_label="Tuesday Juniors",
        urgency="urgent",
        author_display_name="Coach Riya",
        **overrides,
    )


def test_enrolled_parent_sees_the_session_announcement_with_its_label():
    repo = _FakeMessageRepo(rows={"ann-1": _session_announcement()})
    with _make_client(repo, visible_session_ids=("sess-1",)) as client:
        r = client.get("/api/v2/parent/messages")

    assert r.status_code == 200, r.text
    [view] = r.json()["messages"]
    assert view["body"] == "Court 3 is closed tonight"
    # The label is what tells a family with three children in three classes
    # WHICH class was cancelled.
    assert view["scope_label"] == "Tuesday Juniors"
    assert view["urgency"] == "urgent"
    assert view["author_display_name"] == "Coach Riya"


def test_parent_without_the_enrollment_cannot_see_the_session_announcement():
    """THE #614 LEAK REGRESSION TEST.

    Same academy, same endpoint, no active enrollment in that session. Before
    the fix ``for_recipient`` matched every ``kind == "announcement"`` document
    in the tenant, so this parent would have read another class's message.
    """
    repo = _FakeMessageRepo(
        rows={
            "ann-1": _session_announcement(),
            "m-2": _message(
                message_id="m-2", kind="announcement", recipient_id=None, body="Academy closed"
            ),
        }
    )
    with _make_client(repo, user_id="p2", visible_session_ids=()) as client:
        r = client.get("/api/v2/parent/messages")

    assert r.status_code == 200, r.text
    bodies = [m["body"] for m in r.json()["messages"]]
    # The academy-wide announcement still arrives — no regression there.
    assert bodies == ["Academy closed"]


def test_unenrolled_parent_cannot_forge_a_read_receipt_on_a_session_announcement():
    repo = _FakeMessageRepo(rows={"ann-1": _session_announcement()})
    with _make_client(repo, user_id="p2", visible_session_ids=()) as client:
        r = client.post("/api/v2/parent/messages/ann-1/read")

    # 200 either way: the endpoint must not become an existence oracle.
    assert r.status_code == 200, r.text
    assert repo.rows["ann-1"].read_by == []


def test_enrolled_parent_can_mark_the_session_announcement_read():
    repo = _FakeMessageRepo(rows={"ann-1": _session_announcement()})
    with _make_client(repo, visible_session_ids=("sess-1",)) as client:
        r = client.post("/api/v2/parent/messages/ann-1/read")

    assert r.status_code == 200, r.text
    assert repo.rows["ann-1"].read_by == ["p1"]
