"""Application-layer tests for CreateSessionFeedback use case."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.contexts.coaching.application.use_cases.session_feedback import (
    CreateFeedbackCommand,
    CreateSessionFeedback,
    ListSessionFeedback,
)
from backend.v2.contexts.coaching.domain.errors import SessionNotAssigned
from backend.v2.contexts.coaching.domain.models import SessionFeedback

# --- in-memory fakes ---


class _FakeFeedbackRepo:
    def __init__(self) -> None:
        self.saved: list[SessionFeedback] = []

    async def save(self, feedback: SessionFeedback) -> None:
        self.saved.append(feedback)

    async def list_for_session(self, session_id: str, *, limit: int = 100) -> list[SessionFeedback]:
        return [f for f in self.saved if f.session_id == session_id][:limit]

    async def list_for_student(self, student_id: str, *, limit: int = 100) -> list[SessionFeedback]:
        return [f for f in self.saved if f.student_id == student_id][:limit]


class _FakeAssignmentLookup:
    def __init__(self, assigned_sessions: set[str]) -> None:
        self._assigned = assigned_sessions

    async def is_coach_assigned(self, coach_id: str, session_id: str) -> bool:
        return session_id in self._assigned


class _FakeOutbox:
    def __init__(self) -> None:
        self.appended: list = []

    async def append(self, event, *, session=None) -> None:
        self.appended.append(event)


_FIXED_NOW = datetime(2026, 5, 31, 10, 0, tzinfo=UTC)


def _make_use_case(
    assigned: set[str] | None = None,
) -> tuple[CreateSessionFeedback, _FakeFeedbackRepo, _FakeOutbox]:
    repo = _FakeFeedbackRepo()
    outbox = _FakeOutbox()
    lookup = _FakeAssignmentLookup(assigned or {"sess-1"})
    uc = CreateSessionFeedback(
        feedback_repo=repo,
        assignment_lookup=lookup,
        outbox=outbox,
        clock=lambda: _FIXED_NOW,
    )
    return uc, repo, outbox


# --- tests ---


@pytest.mark.asyncio
async def test_happy_path_saves_feedback():
    uc, repo, _ = _make_use_case(assigned={"sess-1"})
    cmd = CreateFeedbackCommand(session_id="sess-1", student_id="stu-1", body="Great session!")
    result = await uc.execute(cmd, coach_id="coach-1")

    assert result.session_id == "sess-1"
    assert result.student_id == "stu-1"
    assert result.coach_id == "coach-1"
    assert result.body == "Great session!"
    assert result.rating is None
    assert result.created_at == _FIXED_NOW
    assert len(repo.saved) == 1
    assert repo.saved[0].feedback_id == result.feedback_id


@pytest.mark.asyncio
async def test_happy_path_with_rating():
    uc, _repo, _ = _make_use_case(assigned={"sess-1"})
    cmd = CreateFeedbackCommand(session_id="sess-1", student_id="stu-1", body="Good", rating=5)
    result = await uc.execute(cmd, coach_id="coach-1")
    assert result.rating == 5


@pytest.mark.asyncio
async def test_event_emitted_on_success():
    uc, _, outbox = _make_use_case(assigned={"sess-1"})
    cmd = CreateFeedbackCommand(session_id="sess-1", student_id="stu-1", body="Nice work")
    result = await uc.execute(cmd, coach_id="coach-1")

    assert len(outbox.appended) == 1
    event = outbox.appended[0]
    assert event.name == "Coaching.SessionFeedbackPosted"
    assert event.feedback_id == result.feedback_id
    assert event.session_id == "sess-1"
    assert event.coach_id == "coach-1"
    assert event.student_id == "stu-1"


@pytest.mark.asyncio
async def test_unassigned_raises_session_not_assigned():
    uc, repo, outbox = _make_use_case(assigned={"other-sess"})
    cmd = CreateFeedbackCommand(session_id="sess-1", student_id="stu-1", body="Nope")

    with pytest.raises(SessionNotAssigned):
        await uc.execute(cmd, coach_id="coach-1")

    assert len(repo.saved) == 0
    assert len(outbox.appended) == 0


@pytest.mark.asyncio
async def test_list_feedback_returns_for_session():
    uc, repo, _ = _make_use_case(assigned={"sess-1", "sess-2"})
    list_uc = ListSessionFeedback(feedback_repo=repo)

    cmd1 = CreateFeedbackCommand(session_id="sess-1", student_id="stu-1", body="Note A")
    cmd2 = CreateFeedbackCommand(session_id="sess-2", student_id="stu-2", body="Note B")
    await uc.execute(cmd1, coach_id="coach-1")
    await uc.execute(cmd2, coach_id="coach-1")

    results = await list_uc.execute("sess-1")
    assert len(results) == 1
    assert results[0].body == "Note A"
